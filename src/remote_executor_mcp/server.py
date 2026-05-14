"""MCP Server — bridges OpenCode to remote execution environment.

Provides 5 tools:
  - sync_and_deploy  : upload files + run deploy script
  - run_test         : execute tests on remote
  - get_logs         : fetch service/container logs
  - get_status       : check service health
  - exec_command     : generic sandboxed remote command
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .config import Config
from .executor import RemoteExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,  # stderr does not interfere with MCP stdio
)
logger = logging.getLogger("remote-executor-mcp")

# ── Tool definitions ────────────────────────────────────────────────

TOOLS = [
    Tool(
        name="sync_and_deploy",
        description=(
            "将本地修改的文件同步到远端服务器，可选执行部署命令。\n"
            "大多数情况下只做文件替换，不需要部署脚本。如：\n"
            "- 替换静态HTML/配置文件 → 不传 deploy_script，只同步\n"
            "- 替换 Python/Go 代码并重启服务 → deploy_script 传 'systemctl restart myapp'\n"
            "- 替换前端资源并构建 → deploy_script 传 'npm run build'\n"
            "如果不确定要不要部署，先不传 deploy_script，只同步文件。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要同步的文件列表，使用相对于项目根目录的路径。例如 ['src/main.py', 'tests/test_api.py']",
                },
                "deploy_script": {
                    "type": "string",
                    "description": "远端部署命令。不传则只替换文件，不做任何部署操作。仅在需要重启服务、重新构建等场景才传。",
                },
                "local_dir": {
                    "type": "string",
                    "description": "本地项目目录的绝对路径。不填则使用配置的默认值。",
                },
                "remote_dir": {
                    "type": "string",
                    "description": "远端项目目录的绝对路径。不填则使用配置的默认值。",
                },
            },
            "required": ["files"],
        },
    ),
    Tool(
        name="run_test",
        description=(
            "在远端服务器上执行测试命令，返回结构化测试结果（exit_code、stdout、stderr、耗时）。"
            "支持 pytest、unittest、npm test 等任何测试命令。"
            "当测试失败时，你必须调用 get_logs 获取更多上下文，然后再修复代码。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "test_command": {
                    "type": "string",
                    "description": "测试命令，例如 'pytest tests/test_api.py -v' 或 'npm test'。",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数，默认 300 秒。",
                    "default": 300,
                },
                "cwd": {
                    "type": "string",
                    "description": "远端工作目录。不填则使用配置的远端项目目录。",
                },
            },
            "required": ["test_command"],
        },
    ),
    Tool(
        name="get_logs",
        description=(
            "从远端服务器获取服务日志。支持三种格式：\n"
            "1. systemd journal: 'journalctl -u my-service'\n"
            "2. Docker logs: 'docker logs my-container'\n"
            "3. 文件路径: '/var/log/app.log'\n"
            "日志末尾会被截断到指定的行数。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "日志来源。支持: journalctl -u <服务名>, docker logs <容器名>, 或 /var/log/xxx.log",
                },
                "lines": {
                    "type": "integer",
                    "description": "返回的行数，默认 500。",
                    "default": 500,
                },
                "cwd": {
                    "type": "string",
                    "description": "远端工作目录。不填则使用配置的远端项目目录。",
                },
            },
            "required": ["source"],
        },
    ),
    Tool(
        name="get_status",
        description=(
            "检查远端服务器上某个服务的运行状态。"
            "自动识别 systemd 服务或 docker 容器，返回 active 状态、uptime、PID 等信息。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "服务名称，例如 'nginx'、'my-app'、'docker-nginx'。",
                },
            },
            "required": ["service"],
        },
    ),
    Tool(
        name="exec_command",
        description=(
            "在远端服务器上执行一个沙箱受控的命令。命令会经过白名单和危险模式检查。"
            "允许的命令包括: pytest, python, systemctl, docker, kubectl, git, tail, cat, grep 等。"
            "危险命令（如 rm -rf /）会被自动拦截。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的命令。",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数，默认 60 秒。",
                    "default": 60,
                },
                "cwd": {
                    "type": "string",
                    "description": "远端工作目录。",
                },
            },
            "required": ["command"],
        },
    ),
]

# ── Server setup ────────────────────────────────────────────────────

server = Server("remote-executor")

_executor: RemoteExecutor | None = None


def get_executor() -> RemoteExecutor:
    if _executor is None:
        raise RuntimeError("Executor not initialized — server not configured")
    return _executor


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    executor = get_executor()
    logger.info("Tool called: %s(%s)", name, json.dumps(arguments, ensure_ascii=False, default=str)[:200])

    try:
        match name:
            case "sync_and_deploy":
                result = await executor.sync_and_deploy(
                    files=arguments.get("files", []),
                    deploy_script=arguments.get("deploy_script"),
                    local_dir=arguments.get("local_dir"),
                    remote_dir=arguments.get("remote_dir"),
                )
            case "run_test":
                result = await executor.run_test(
                    test_command=arguments["test_command"],
                    timeout=arguments.get("timeout"),
                    cwd=arguments.get("cwd"),
                )
            case "get_logs":
                result = await executor.get_logs(
                    source=arguments["source"],
                    lines=arguments.get("lines"),
                    cwd=arguments.get("cwd"),
                )
            case "get_status":
                result = await executor.get_status(
                    service=arguments["service"],
                )
            case "exec_command":
                result = await executor.exec_command(
                    command=arguments["command"],
                    timeout=arguments.get("timeout"),
                    cwd=arguments.get("cwd"),
                )
            case _:
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"Unknown tool: {name}",
                }, ensure_ascii=False))]

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    except Exception as e:
        logger.exception("Tool %s failed", name)
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": str(e),
            "tool": name,
        }, ensure_ascii=False))]


# ── Entry point ─────────────────────────────────────────────────────

async def main() -> None:
    config = Config()

    errors = config.validate()
    if errors:
        for err in errors:
            logger.error("Config error: %s", err)
        logger.error("Fix the errors above and restart. Required env vars: "
                     "REMOTE_HOST, REMOTE_USER, REMOTE_KEY_PATH (or REMOTE_PASSWORD)")
        sys.exit(1)

    logger.info("Starting remote-executor MCP server")
    logger.info("Remote: %s@%s:%d -> %s",
                config.remote_user, config.remote_host, config.remote_port,
                config.remote_project_dir)
    logger.info("Local project: %s", config.local_project_dir)

    global _executor
    _executor = RemoteExecutor(config)
    await _executor.start()

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        await _executor.stop()


if __name__ == "__main__":
    asyncio.run(main())
