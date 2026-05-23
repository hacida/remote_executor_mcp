"""Structured result types for remote execution feedback.

Every tool returns a CommandResult — the LLM parses this to decide next actions.
"""

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class CommandResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    command: str
    host: str
    cwd: str | None = None
    truncated_stdout: bool = False
    truncated_stderr: bool = False

    MAX_OUTPUT_LEN = 80_000

    @classmethod
    def from_ssh_result(cls, result: Any, command: str, host: str, cwd: str | None,
                        duration_ms: float) -> "CommandResult":
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        truncated_stdout = len(stdout) > cls.MAX_OUTPUT_LEN
        truncated_stderr = len(stderr) > cls.MAX_OUTPUT_LEN
        if truncated_stdout:
            stdout = stdout[-cls.MAX_OUTPUT_LEN:]
        if truncated_stderr:
            stderr = stderr[-cls.MAX_OUTPUT_LEN:]
        return cls(
            success=(result.exit_status or result.returncode or 0) == 0,
            exit_code=result.exit_status or result.returncode or 0,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            command=command,
            host=host,
            cwd=cwd,
            truncated_stdout=truncated_stdout,
            truncated_stderr=truncated_stderr,
        )

    @classmethod
    def from_error(cls, error: str, command: str, host: str,
                   cwd: str | None = None) -> "CommandResult":
        return cls(
            success=False,
            exit_code=-1,
            stdout="",
            stderr=error,
            duration_ms=0,
            command=command,
            host=host,
            cwd=cwd,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SyncResult:
    files_synced: list[str]
    files_failed: list[dict[str, str]]
    total_bytes: int
    duration_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
