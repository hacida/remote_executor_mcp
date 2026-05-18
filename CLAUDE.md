# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

`remote-executor-mcp` is an MCP (Model Context Protocol) server that bridges a local AI agent to a remote Linux server via SSH. It provides 2 tools: `sync_and_deploy` (SFTP upload + optional deploy script) and `exec_command` (sandboxed remote command execution). Together they enable a **modify → deploy → test → fix** closed loop.

The server works with any MCP client (Claude Code, OpenCode, etc.).

Package layout: `src/remote_executor_mcp/` (source).

## Commands

```bash
# Install in editable mode
pip install -e .

# Run the MCP server (as a child process of an MCP client)
python -m remote_executor_mcp

# Run tests (when test suite exists)
pytest tests/ -v
```

## AI Skill

The project includes an AI skill at `opencode/skills/remote-dev/SKILL.md` that defines the complete remote development workflow:
local coding → sync → deploy → test → diagnose → fix loop. It covers auto-discovery of
remote services/logs/params, memory-driven configuration, and test generation cycles.

## Architecture

The server is launched as a child process by an MCP client and communicates over stdio via the `mcp` library.

**Startup flow** (`__main__.py` → `server.main()`):
1. `MultiServerConfig.from_env()` loads `remote-executor.yaml` (or the path in `REMOTE_EXECUTOR_CONFIG` env var).
2. `MultiServerConfig.validate()` checks SSH key existence, local dir existence, required fields for every server.
3. `RemoteExecutor.start()` creates a `ConnectionPool` per server and runs a health check on each. Fails fast if any remote is unreachable.
4. `stdio_server()` opens read/write streams and the `mcp.Server` handles the MCP lifecycle.

**Tool dispatch** (`server.py`): `call_tool` receives tool name + arguments, dispatches to `RemoteExecutor` methods via `match/case`. Both tools (`sync_and_deploy` and `exec_command`) route to the remote host.

**`RemoteExecutor`** (`executor.py`): High-level operations layer. Each method:
1. Validates the command through `sandbox.check_allowed()`.
2. Calls `run_remote(pool, command, ...)` which borrows a connection from the pool, runs the command on the remote host, and returns a `CommandResult`.

**`ConnectionPool`** (`transport.py`): Small reuse pool of `asyncssh.SSHClientConnection` objects. `get()` returns healthy connections or creates new ones; `put()` returns them to the pool. Configurable size per server via `connection_pool_size` in the YAML config (default 3).

**`sandbox`** (`sandbox.py`): Command whitelist + blocked-pattern safety layer. Every remote command passes through `check_allowed()` which:
- Parses the command with `shlex.split()`.
- Checks the base command against `ALLOWED_COMMANDS` (40+ whitelisted commands).
- Rejects commands matching `BLOCKED_PATTERNS` (15+ regexes like `rm -rf /`, fork bombs, `dd`).
- Rejects blocked subcommands (e.g., `docker system prune`).

## Key dependencies

- `mcp>=1.0.0` — MCP protocol library (server + stdio transport).
- `asyncssh>=2.14.0` — Async SSH client (connection pool, SFTP, command execution).
- `pytest>=8.0` + `pytest-asyncio>=0.24` — testing (dev only).

## Configuration

Configuration is read from `remote-executor.yaml` in the project root (override path via `REMOTE_EXECUTOR_CONFIG` env var):

```yaml
local_project_dir: /home/user/projects/myapp
default_timeout: 300

servers:
  prod:
    host: 10.0.0.1
    port: 22
    user: deploy
    key_path: ~/.ssh/id_rsa
    project_dir: /opt/myapp
```

Each server block defines one remote host. Tools accept an optional `server` parameter to target a specific server; omit it to use the first one listed.
