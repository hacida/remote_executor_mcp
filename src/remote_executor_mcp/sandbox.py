"""Command sandbox — whitelist-based safety layer.

Every command executed on the remote host passes through this layer.
"""

import re
import shlex


ALLOWED_COMMANDS: set[str] = {
    # Testing
    "pytest", "tox", "nose2", "unittest",
    # Interpreters (flags restricted below)
    "python", "python3", "node", "ruby", "perl", "php",
    # Service management (restricted)
    "systemctl", "journalctl", "supervisorctl",
    # Containers
    "docker", "docker-compose", "podman",
    # Orchestration (read-only preferred)
    "kubectl", "helm",
    # Package managers
    "npm", "npx", "yarn", "pnpm", "pip", "pip3", "poetry", "cargo", "go",
    # Build tools
    "make", "cmake", "ninja", "meson", "cargo",
    # Version control
    "git",
    # File transfer
    "rsync", "scp", "sftp",
    # Read-only file operations
    "ls", "cat", "head", "tail", "grep", "find", "wc", "stat", "file",
    "du", "df", "tree", "less", "zcat", "zgrep",
    # Process inspection
    "ps", "pgrep", "pidof", "lsof", "top", "htop", "iotop",
    # Network inspection
    "ss", "netstat", "curl", "wget", "ping", "nc", "nmap",
    # System info
    "uname", "hostname", "whoami", "uptime", "date", "env", "printenv",
    # Shell (with extra scrutiny)
    "bash", "sh", "dash",
}

# Commands allowed but with extra logging/audit
SENSITIVE_COMMANDS: set[str] = {
    "systemctl", "docker", "docker-compose", "podman",
    "kubectl", "helm",
    "bash", "sh",
    "pip", "pip3", "npm", "npx", "yarn", "pnpm",
}

# Patterns that are ALWAYS blocked regardless of command whitelist
BLOCKED_PATTERNS: list[re.Pattern] = [
    re.compile(p) for p in [
        r"rm\s+-rf\s+/",
        r"rm\s+-rf\s+~",
        r"rm\s+-rf\s+\$HOME",
        r">\s*/dev/sd[a-z]",
        r">\s*/dev/nvme",
        r">\s*/dev/mmcblk",
        r"dd\s+if=.*\s+of=/dev/",
        r"mkfs\.\w+\s+/dev/",
        r"chmod\s+(-R\s+)?777\s+/",
        r"chown\s+(-R\s+)?\S+\s+/",
        r":\(\)\s*\{\s*:\|:&\s*\};:",  # fork bomb
        r"fdisk\s+/dev/",
        r"parted\s+/dev/",
        r"mount\s+/dev/",
        r"umount\s+/",
        r"iptables\s+-F",
        r"reboot",
        r"shutdown",
        r"halt",
        r"poweroff",
        r"init\s+[0-6]",
        r"telinit\s+[0-6]",
        r"wget\s+\S+\s+-O\s+/etc/",
        r"curl\s+\S+\s+-o\s+/etc/",
    ]
]

# Sub-commands blocked for otherwise-allowed top-level commands
BLOCKED_SUBCOMMANDS: dict[str, list[str]] = {
    "docker": ["rm -f $(docker", "system prune", "volume prune"],
    "systemctl": ["disable", "mask", "set-default"],
    "kubectl": ["delete namespace", "delete pv", "delete pvc --all"],
}


def check_allowed(command: str) -> tuple[bool, str]:
    """Check if a command is allowed. Returns (allowed, reason)."""
    stripped = command.strip()

    if not stripped:
        return False, "Empty command"

    # Check blocked patterns first
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(stripped):
            return False, f"Blocked pattern matched: {pattern.pattern}"

    # Parse the command to get the base executable
    try:
        parts = shlex.split(stripped)
    except ValueError as e:
        return False, f"Invalid shell syntax: {e}"

    if not parts:
        return False, "Empty command after parsing"

    base_cmd = parts[0]
    # Strip path prefix: /usr/bin/python -> python
    if "/" in base_cmd:
        base_cmd = base_cmd.rsplit("/", 1)[-1]

    if base_cmd not in ALLOWED_COMMANDS:
        return False, f"Command '{base_cmd}' is not in the allowed list"

    # Check blocked subcommands for otherwise-allowed commands
    if base_cmd in BLOCKED_SUBCOMMANDS:
        cmd_lower = stripped.lower()
        for blocked_sub in BLOCKED_SUBCOMMANDS[base_cmd]:
            if blocked_sub.lower() in cmd_lower:
                return False, f"Blocked subcommand for {base_cmd}: {blocked_sub}"

    return True, "ok"


def is_sensitive(command: str) -> bool:
    """Check if a command is in the sensitive category (needs extra audit)."""
    try:
        parts = shlex.split(command.strip())
    except ValueError:
        return True  # Treat unparseable as sensitive
    if not parts:
        return False
    base_cmd = parts[0].rsplit("/", 1)[-1] if "/" in parts[0] else parts[0]
    return base_cmd in SENSITIVE_COMMANDS


def sanitize_for_log(command: str) -> str:
    """Strip potential secrets before logging."""
    # Strip password-like arguments
    sanitized = re.sub(r'(--password[= ])\S+', r'\1***', command, flags=re.IGNORECASE)
    sanitized = re.sub(r'(--pass[= ])\S+', r'\1***', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'(--secret[= ])\S+', r'\1***', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'(--token[= ])\S+', r'\1***', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'(PASSWORD[= ])\S+', r'\1***', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'(SECRET[= ])\S+', r'\1***', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'(TOKEN[= ])\S+', r'\1***', sanitized, flags=re.IGNORECASE)
    return sanitized
