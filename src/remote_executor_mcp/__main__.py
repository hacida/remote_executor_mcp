"""Entry point for `python -m remote_executor_mcp`."""

import asyncio

if __name__ == "__main__":
    try:
        from .server import main
    except ImportError:
        from remote_executor_mcp.server import main  # type: ignore[no-redef]
    asyncio.run(main())
