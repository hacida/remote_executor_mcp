"""SSH connection management — pool, reconnect, health checks."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import asyncssh

from .config import Config

logger = logging.getLogger(__name__)


class ConnectionPool:
    """A small pool of reusable SSH connections."""

    def __init__(self, config: Config):
        self.config = config
        self._connections: list[asyncssh.SSHClientConnection] = []
        self._lock = asyncio.Lock()
        self._closed = False

    async def _create_connection(self) -> asyncssh.SSHClientConnection:
        connect_kwargs: dict = {
            "host": self.config.remote_host,
            "port": self.config.remote_port,
            "username": self.config.remote_user,
            "known_hosts": self._resolve_known_hosts(),
        }
        if self.config.remote_key_path and Path(self.config.remote_key_path).exists():
            connect_kwargs["client_keys"] = [self.config.remote_key_path]
        elif self.config.remote_password:
            connect_kwargs["password"] = self.config.remote_password
        else:
            raise ValueError("No authentication method configured. "
                             "Set REMOTE_KEY_PATH or REMOTE_PASSWORD.")

        try:
            conn = await asyncio.wait_for(
                asyncssh.connect(**connect_kwargs),
                timeout=15,
            )
            logger.info("SSH connected to %s@%s:%d",
                        self.config.remote_user, self.config.remote_host, self.config.remote_port)
            return conn
        except asyncio.TimeoutError:
            raise ConnectionError(
                f"SSH connection timed out after 15s: "
                f"{self.config.remote_user}@{self.config.remote_host}:{self.config.remote_port}"
            )
        except asyncssh.Error as e:
            raise ConnectionError(f"SSH connection failed: {e}")

    def _resolve_known_hosts(self):
        """Resolve known_hosts handling — None means accept new hosts (auto-add)."""
        if self.config.known_hosts_path and Path(self.config.known_hosts_path).exists():
            return self.config.known_hosts_path
        # Auto-accept: only use if you trust the target network
        return None

    async def get(self) -> asyncssh.SSHClientConnection:
        async with self._lock:
            if self._closed:
                raise RuntimeError("Connection pool is closed")
            # Return an existing healthy connection
            while self._connections:
                conn = self._connections.pop()
                if not conn.is_closed():
                    return conn
            # All dead or empty — create new
            return await self._create_connection()

    async def put(self, conn: asyncssh.SSHClientConnection) -> None:
        async with self._lock:
            if self._closed or conn.is_closed():
                return
            if len(self._connections) < self.config.connection_pool_size:
                self._connections.append(conn)
            else:
                conn.close()

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            for conn in self._connections:
                conn.close()
            self._connections.clear()

    async def health_check(self) -> bool:
        """Test connectivity — returns True if we can connect and run a command."""
        try:
            conn = await self._create_connection()
            result = await conn.run("echo ok", timeout=10)
            conn.close()
            return result.exit_status == 0
        except Exception:
            return False


@asynccontextmanager
async def remote_session(pool: ConnectionPool, cwd: str | None = None):
    """Context manager that yields a connected SSH client with an optional working dir."""
    conn = await pool.get()
    try:
        if cwd:
            # Verify cwd exists
            r = await conn.run(f"test -d {cwd}", timeout=10)
            if r.exit_status != 0:
                raise ValueError(f"Remote working directory does not exist: {cwd}")
        yield conn
    except asyncssh.Error as e:
        raise ConnectionError(f"SSH session error: {e}")
    finally:
        await pool.put(conn)


async def run_remote(
    pool: ConnectionPool,
    command: str,
    timeout: int = 300,
    cwd: str | None = None,
) -> tuple["CommandResult", asyncssh.SSHClientConnection | None]:
    """Execute a command on the remote host. Returns (result, connection).

    Import here to avoid circular imports.
    """
    from .models import CommandResult

    full_cmd = f"cd {cwd} && {command}" if cwd else command
    t0 = time.perf_counter()

    conn: asyncssh.SSHClientConnection | None = None
    try:
        conn = await pool.get()
        ssh_result = await asyncio.wait_for(
            conn.run(full_cmd),
            timeout=timeout + 5,  # slight extra for SSH overhead
        )
        duration_ms = (time.perf_counter() - t0) * 1000
        result = CommandResult.from_ssh_result(
            ssh_result, command, pool.config.remote_host, cwd, duration_ms,
        )
        return result, conn
    except asyncio.TimeoutError:
        duration_ms = (time.perf_counter() - t0) * 1000
        result = CommandResult(
            success=False, exit_code=-1, stdout="", duration_ms=duration_ms,
            stderr=f"Command timed out after {timeout}s", command=command,
            host=pool.config.remote_host, cwd=cwd,
        )
        return result, conn
    except Exception as e:
        duration_ms = (time.perf_counter() - t0) * 1000
        result = CommandResult.from_error(
            str(e), command, pool.config.remote_host, cwd,
        )
        result.duration_ms = duration_ms
        return result, conn
