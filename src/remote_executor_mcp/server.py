"""MCP Server — bridges an MCP client to a remote execution environment.

Provides 2 tools:
  - sync_and_deploy  : upload files + run deploy script
  - exec_command     : generic sandboxed remote command
"""

import asyncio
import json
import logging
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .config import MultiServerConfig
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
                "server": {
                    "type": "string",
                    "description": "目标服务器名称。不填则使用默认服务器。可用服务器列表见服务启动日志。",
                },
            },
            "required": ["files"],
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
                "server": {
                    "type": "string",
                    "description": "目标服务器名称。不填则使用默认服务器。",
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
                    server=arguments.get("server"),
                )
            case "exec_command":
                result = await executor.exec_command(
                    command=arguments["command"],
                    timeout=arguments.get("timeout"),
                    cwd=arguments.get("cwd"),
                    server=arguments.get("server"),
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
    config = MultiServerConfig.from_env()

    errors = config.validate()
    if errors:
        for err in errors:
            logger.error("Config error: %s", err)
        logger.error("Fix the errors above and restart.")
        logger.error("Create a remote-executor.yaml config file in your project root, "
                     "or set REMOTE_EXECUTOR_CONFIG to point to one.")
        sys.exit(1)

    logger.info("Starting remote-executor MCP server")
    logger.info("Servers: %s", ", ".join(config.server_names))
    for name, srv in config.servers.items():
        logger.info("  [%s] %s@%s:%d -> %s",
                    name, srv.remote_user, srv.remote_host,
                    srv.remote_port, srv.remote_project_dir)
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
