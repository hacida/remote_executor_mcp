"""Configuration — per-server settings and multi-server YAML loader."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ServerConfig:
    """Connection details for a single remote server."""

    remote_host: str = ""
    remote_port: int = 22
    remote_user: str = "root"
    remote_key_path: str = ""
    remote_password: str = ""
    known_hosts_path: str = ""
    remote_project_dir: str = "/opt/app"
    remote_become_user: str = ""
    remote_become_password: str = ""
    connection_pool_size: int = 3

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.remote_host:
            errors.append("remote_host is required")
        if not self.remote_user:
            errors.append("remote_user is required")
        if self.remote_key_path and not Path(self.remote_key_path).expanduser().exists():
            errors.append(f"SSH key not found: {self.remote_key_path}")
        return errors


@dataclass
class MultiServerConfig:
    """Top-level config: server definitions + shared settings."""

    servers: dict[str, ServerConfig] = field(default_factory=dict)
    local_project_dir: str = ""
    default_timeout: int = 300

    @property
    def server_names(self) -> list[str]:
        return list(self.servers.keys())

    @property
    def default_server(self) -> str:
        return self.server_names[0] if self.server_names else "default"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.servers:
            errors.append("No servers configured")
        if not Path(self.local_project_dir).exists():
            errors.append(f"LOCAL_PROJECT_DIR does not exist: {self.local_project_dir}")
        for name, cfg in self.servers.items():
            for err in cfg.validate():
                errors.append(f"[{name}] {err}")
        return errors

    @classmethod
    def from_env(cls, config_path: str | None = None) -> "MultiServerConfig":
        """Load configuration from a YAML file.

        Resolution order:
        1. Explicit ``config_path`` argument
        2. ``REMOTE_EXECUTOR_CONFIG`` env var
        3. ``./remote-executor.yaml`` in CWD
        """
        path = config_path or os.environ.get("REMOTE_EXECUTOR_CONFIG", "")
        if not path:
            candidate = Path.cwd() / "remote-executor.yaml"
            if candidate.exists():
                path = str(candidate)

        if not path:
            raise FileNotFoundError(
                "No config file found. Create a remote-executor.yaml in your project root, "
                "or set REMOTE_EXECUTOR_CONFIG to the path of your config file."
            )

        return cls._from_yaml(path)

    @classmethod
    def _from_yaml(cls, path: str) -> "MultiServerConfig":
        import yaml

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        servers: dict[str, ServerConfig] = {}
        for name, srv in data.get("servers", {}).items():
            servers[name] = ServerConfig(
                remote_host=str(srv.get("host", "")),
                remote_port=int(srv.get("port", 22)),
                remote_user=str(srv.get("user", "root")),
                remote_key_path=str(srv.get("key_path", "")),
                remote_password=str(srv.get("password", "")),
                known_hosts_path=str(srv.get("known_hosts", "")),
                remote_project_dir=str(srv.get("project_dir", "/opt/app")),
                remote_become_user=str(srv.get("become_user", "")),
                remote_become_password=str(srv.get("become_password", "")),
                connection_pool_size=int(srv.get("connection_pool_size", 3)),
            )

        return cls(
            servers=servers,
            local_project_dir=data.get("local_project_dir", str(Path.cwd())),
            default_timeout=int(data.get("default_timeout", 300)),
        )
