"""High-level remote operations — sync, deploy, exec."""

import logging
import time
from pathlib import Path
from typing import Any

from .config import MultiServerConfig, ServerConfig
from .models import CommandResult, SyncResult
from .sandbox import check_allowed, is_sensitive, sanitize_for_log
from .transport import ConnectionPool, run_remote

logger = logging.getLogger(__name__)


class RemoteExecutor:
    """Manages per-server connection pools and exposes remote operations."""

    def __init__(self, config: MultiServerConfig):
        self.config = config
        self._pools: dict[str, ConnectionPool] = {}

    async def start(self) -> None:
        """Create and health-check a pool for every configured server."""
        for name in self.config.server_names:
            pool = ConnectionPool(self.config.servers[name])
            ok = await pool.health_check()
            if not ok:
                raise ConnectionError(
                    f"Failed health check for server '{name}' "
                    f"({self.config.servers[name].remote_host}) — "
                    f"check credentials and network"
                )
            self._pools[name] = pool
            logger.info("Server '%s' ready: %s@%s:%d -> %s",
                        name,
                        self.config.servers[name].remote_user,
                        self.config.servers[name].remote_host,
                        self.config.servers[name].remote_port,
                        self.config.servers[name].remote_project_dir)

    async def stop(self) -> None:
        for name, pool in self._pools.items():
            await pool.close()
        self._pools.clear()

    def _resolve_server(self, server: str | None) -> tuple[str, ServerConfig, ConnectionPool]:
        """Return (name, ServerConfig, ConnectionPool) for the given server."""
        name = server or self.config.default_server
        if name not in self._pools:
            raise ValueError(
                f"Unknown server '{name}'. Available: {', '.join(self.config.server_names)}"
            )
        return name, self.config.servers[name], self._pools[name]

    # ── sync_and_deploy ────────────────────────────────────────────

    async def sync_and_deploy(
        self,
        files: list[str],
        deploy_script: str | None = None,
        local_dir: str | None = None,
        remote_dir: str | None = None,
        server: str | None = None,
    ) -> dict[str, Any]:
        """Sync local files to remote, then optionally run deploy script."""
        server_name, srv_config, pool = self._resolve_server(server)
        local_base = Path(local_dir or self.config.local_project_dir)
        remote_base = remote_dir or srv_config.remote_project_dir

        t0 = time.perf_counter()
        synced: list[str] = []
        failed: list[dict[str, str]] = []
        total_bytes = 0

        conn = await pool.get()
        try:
            sftp = await conn.start_sftp_client()
            try:
                for rel_path in files:
                    local_path = local_base / rel_path
                    remote_path = f"{remote_base}/{rel_path}"

                    if not local_path.exists():
                        failed.append({"file": rel_path, "error": f"Local file not found: {local_path}"})
                        continue

                    try:
                        remote_parent = remote_path.rsplit("/", 1)[0]
                        await conn.run(f"mkdir -p {remote_parent}", timeout=30)
                        await sftp.put(str(local_path), remote_path)
                        synced.append(rel_path)
                        total_bytes += local_path.stat().st_size
                        logger.debug("[%s] Synced %s -> %s", server_name, rel_path, remote_path)
                    except Exception as e:
                        failed.append({"file": rel_path, "error": str(e)})
            finally:
                sftp.exit()

            deploy_result = None
            if deploy_script:
                ok, reason = check_allowed(deploy_script)
                if not ok:
                    deploy_result = CommandResult.from_error(
                        f"Deploy command blocked: {reason}",
                        deploy_script, srv_config.remote_host, remote_base,
                    )
                else:
                    logger.info("[%s] Deploying: %s", server_name, deploy_script)
                    deploy_result, _ = await run_remote(
                        pool, deploy_script,
                        timeout=self.config.default_timeout, cwd=remote_base,
                    )
            else:
                logger.info("[%s] No deploy_script — files synced, skipping deploy", server_name)

            duration_ms = (time.perf_counter() - t0) * 1000
            return SyncResult(
                files_synced=synced, files_failed=failed,
                deploy_result=deploy_result, total_bytes=total_bytes,
                duration_ms=duration_ms,
            ).to_dict()
        finally:
            await pool.put(conn)

    # ── exec_command (generic, sandboxed) ──────────────────────────

    async def exec_command(
        self,
        command: str,
        timeout: int | None = None,
        cwd: str | None = None,
        server: str | None = None,
    ) -> dict[str, Any]:
        """Execute a sandboxed command on the named remote server."""
        server_name, srv_config, pool = self._resolve_server(server)
        timeout = timeout or self.config.default_timeout
        cwd = cwd or srv_config.remote_project_dir

        ok, reason = check_allowed(command)
        if not ok:
            return CommandResult.from_error(
                f"Command blocked: {reason}", command, srv_config.remote_host, cwd,
            ).to_dict()

        logger.info("[%s] Exec: %s", server_name, sanitize_for_log(command))
        if is_sensitive(command):
            logger.warning("[%s] Sensitive command: %s", server_name, sanitize_for_log(command))

        result, conn = await run_remote(pool, command, timeout=timeout, cwd=cwd)
        if conn:
            await pool.put(conn)
        return result.to_dict()
