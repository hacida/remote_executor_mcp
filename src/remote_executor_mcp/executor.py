"""High-level remote operations — sync, test, log, deploy, status."""

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any

import asyncssh

from .config import Config
from .models import CommandResult, ServiceStatus, SyncResult
from .sandbox import check_allowed, is_sensitive, sanitize_for_log
from .transport import ConnectionPool, run_remote

logger = logging.getLogger(__name__)


class RemoteExecutor:
    """All remote operations exposed as structured tools for the MCP server."""

    def __init__(self, config: Config):
        self.config = config
        self._pool: ConnectionPool | None = None

    async def start(self) -> None:
        self._pool = ConnectionPool(self.config)
        ok = await self._pool.health_check()
        if not ok:
            raise ConnectionError(
                f"Failed health check to {self.config.remote_host} — "
                f"check REMOTE_HOST, credentials, and network"
            )
        logger.info("RemoteExecutor started — pool ready")

    async def stop(self) -> None:
        if self._pool:
            await self._pool.close()

    @property
    def pool(self) -> ConnectionPool:
        if self._pool is None:
            raise RuntimeError("RemoteExecutor not started — call start() first")
        return self._pool

    # ── sync_and_deploy ────────────────────────────────────────────

    async def sync_and_deploy(
        self,
        files: list[str],
        deploy_script: str | None = None,
        local_dir: str | None = None,
        remote_dir: str | None = None,
    ) -> dict[str, Any]:
        """Sync local files to remote, then run deploy script."""
        local_base = Path(local_dir or self.config.local_project_dir)
        remote_base = remote_dir or self.config.remote_project_dir
        deploy_cmd = deploy_script or self.config.deploy_script

        t0 = time.perf_counter()
        synced: list[str] = []
        failed: list[dict[str, str]] = []
        total_bytes = 0

        conn = await self.pool.get()
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
                        # Ensure remote parent dirs exist
                        remote_parent = remote_path.rsplit("/", 1)[0]
                        await conn.run(f"mkdir -p {remote_parent}", timeout=30)

                        await sftp.put(str(local_path), remote_path)
                        synced.append(rel_path)
                        total_bytes += local_path.stat().st_size
                        logger.debug("Synced %s -> %s", rel_path, remote_path)
                    except Exception as e:
                        failed.append({"file": rel_path, "error": str(e)})
            finally:
                sftp.exit()

            # Run deploy script (only if explicitly configured or passed)
            deploy_result = None
            if deploy_cmd:
                ok, reason = check_allowed(deploy_cmd)
                if not ok:
                    deploy_result = CommandResult.from_error(
                        f"Deploy command blocked: {reason}",
                        deploy_cmd, self.config.remote_host, remote_base,
                    )
                else:
                    logger.info("Deploying: %s", deploy_cmd)
                    deploy_result, _ = await run_remote(
                        self.pool, deploy_cmd,
                        timeout=self.config.default_timeout, cwd=remote_base,
                    )
            else:
                logger.info("No deploy_script configured — files synced, skipping deploy")

            duration_ms = (time.perf_counter() - t0) * 1000
            return SyncResult(
                files_synced=synced, files_failed=failed,
                deploy_result=deploy_result, total_bytes=total_bytes,
                duration_ms=duration_ms,
            ).to_dict()
        finally:
            await self.pool.put(conn)

    # ── run_test ────────────────────────────────────────────────────

    async def run_test(self, test_command: str, timeout: int | None = None,
                       cwd: str | None = None) -> dict[str, Any]:
        """Execute a test command on the remote host."""
        timeout = timeout or self.config.default_timeout
        cwd = cwd or self.config.remote_project_dir

        ok, reason = check_allowed(test_command)
        if not ok:
            return CommandResult.from_error(
                f"Test command blocked: {reason}",
                test_command, self.config.remote_host, cwd,
            ).to_dict()

        logger.info("Running test: %s (timeout=%ds)", sanitize_for_log(test_command), timeout)
        if is_sensitive(test_command):
            logger.warning("Sensitive test command: %s", sanitize_for_log(test_command))

        result, conn = await run_remote(self.pool, test_command, timeout=timeout, cwd=cwd)
        if conn:
            await self.pool.put(conn)
        return result.to_dict()

    # ── get_logs ────────────────────────────────────────────────────

    async def get_logs(self, source: str, lines: int | None = None,
                       cwd: str | None = None) -> dict[str, Any]:
        """Fetch logs from the remote host.

        source can be:
          - "journalctl -u <service>"  (systemd journal)
          - "docker logs <container>" (docker logs)
          - "/var/log/app.log"        (file path — resolved to tail)

        The function auto-detects the source type.
        """
        lines = lines or self.config.max_log_lines
        cwd = cwd or self.config.remote_project_dir

        log_cmd = _build_log_command(source, lines)

        ok, reason = check_allowed(log_cmd)
        if not ok:
            return CommandResult.from_error(
                f"Log command blocked: {reason}",
                log_cmd, self.config.remote_host, cwd,
            ).to_dict()

        result, conn = await run_remote(self.pool, log_cmd, timeout=30, cwd=cwd)
        if conn:
            await self.pool.put(conn)
        return result.to_dict()

    # ── get_status ──────────────────────────────────────────────────

    async def get_status(self, service: str) -> dict[str, Any]:
        """Check if a service is running on the remote host.

        Auto-detects systemd services vs docker containers.
        """
        # Try systemctl first
        cmd = f"systemctl is-active {service} 2>/dev/null && systemctl status {service} --no-pager -l 2>/dev/null || true"
        ok, reason = check_allowed(cmd)
        if not ok:
            return CommandResult.from_error(
                f"Status check blocked: {reason}", cmd, self.config.remote_host,
            ).to_dict()

        result, conn = await run_remote(self.pool, cmd, timeout=15)
        if conn:
            await self.pool.put(conn)

        # Parse into structured ServiceStatus
        active = "active" in result.stdout.lower() or "running" in result.stdout.lower()
        uptime = None
        pid = None

        # Try to extract uptime from systemctl output
        m = re.search(r'Active:.*?since\s+(.+?)(?:;|\n)', result.stdout)
        if m:
            uptime = m.group(1).strip()
        # Try to extract PID
        m = re.search(r'Main PID:\s+(\d+)', result.stdout)
        if m:
            pid = int(m.group(1))

        status = ServiceStatus(
            service_name=service,
            active=active,
            status_text=result.stdout[:2000],
            uptime=uptime,
            pid=pid,
        )

        return {
            "service": status.to_dict(),
            "raw_exit_code": result.exit_code,
        }

    # ── exec_command (generic, restricted) ──────────────────────────

    async def exec_command(self, command: str, timeout: int | None = None,
                           cwd: str | None = None) -> dict[str, Any]:
        """Generic remote command execution (subject to sandbox whitelist)."""
        timeout = timeout or self.config.default_timeout
        cwd = cwd or self.config.remote_project_dir

        ok, reason = check_allowed(command)
        if not ok:
            return CommandResult.from_error(
                f"Command blocked: {reason}", command, self.config.remote_host, cwd,
            ).to_dict()

        logger.info("Exec: %s", sanitize_for_log(command))
        if is_sensitive(command):
            logger.warning("Sensitive command executed: %s", sanitize_for_log(command))

        result, conn = await run_remote(self.pool, command, timeout=timeout, cwd=cwd)
        if conn:
            await self.pool.put(conn)
        return result.to_dict()


def _build_log_command(source: str, lines: int) -> str:
    """Build the appropriate log-fetching command based on the source string."""
    s = source.strip()

    if s.startswith("journalctl"):
        return f"{s} -n {lines} --no-pager"
    if s.startswith("docker logs") or s.startswith("docker-compose logs"):
        tail_flag = "--tail" if "docker-compose" not in s.split()[0] else "--tail"
        return f"{s} {tail_flag} {lines} 2>&1"
    if s.startswith("/") or s.startswith("./"):
        return f"tail -n {lines} {s} 2>&1"
    # Default: treat as a raw command with line limit
    return f"{s} 2>&1 | tail -n {lines}"
