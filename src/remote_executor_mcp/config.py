"""Configuration via environment variables with sensible defaults."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # --- Remote connection ---
    remote_host: str = field(default_factory=lambda: os.environ.get("REMOTE_HOST", ""))
    remote_port: int = field(default_factory=lambda: int(os.environ.get("REMOTE_PORT", "22")))
    remote_user: str = field(default_factory=lambda: os.environ.get("REMOTE_USER", "root"))
    remote_key_path: str = field(default_factory=lambda: os.environ.get(
        "REMOTE_KEY_PATH", str(Path.home() / ".ssh" / "id_rsa")
    ))
    remote_password: str = field(default_factory=lambda: os.environ.get("REMOTE_PASSWORD", ""))
    known_hosts_path: str = field(default_factory=lambda: os.environ.get(
        "REMOTE_KNOWN_HOSTS", str(Path.home() / ".ssh" / "known_hosts")
    ))

    # --- Paths ---
    local_project_dir: str = field(default_factory=lambda: os.environ.get(
        "LOCAL_PROJECT_DIR", str(Path.cwd())
    ))
    remote_project_dir: str = field(default_factory=lambda: os.environ.get(
        "REMOTE_PROJECT_DIR", "/opt/app"
    ))

    # --- Deployment ---
    deploy_script: str = field(default_factory=lambda: os.environ.get(
        "DEPLOY_SCRIPT", ""
    ))

    # --- Limits ---
    default_timeout: int = field(default_factory=lambda: int(os.environ.get("DEFAULT_TIMEOUT", "300")))
    max_log_lines: int = field(default_factory=lambda: int(os.environ.get("MAX_LOG_LINES", "500")))
    connection_pool_size: int = field(default_factory=lambda: int(os.environ.get("CONNECTION_POOL_SIZE", "3")))

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.remote_host:
            errors.append("REMOTE_HOST is required")
        if not self.remote_user:
            errors.append("REMOTE_USER is required")
        if self.remote_key_path:
            if not Path(self.remote_key_path).exists():
                errors.append(f"SSH key not found: {self.remote_key_path}")
        if self.remote_password and self.remote_key_path:
            errors.append("Both REMOTE_PASSWORD and REMOTE_KEY_PATH set — "
                          "REMOTE_KEY_PATH takes precedence, REMOTE_PASSWORD ignored")
        if not Path(self.local_project_dir).exists():
            errors.append(f"LOCAL_PROJECT_DIR does not exist: {self.local_project_dir}")
        return errors
