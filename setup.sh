#!/usr/bin/env bash
# ── Remote Executor MCP — 一键安装脚本 ──────────────────────────────
set -euo pipefail

echo "=== Remote Executor MCP — 安装 ==="

# 1. 检查 Python
PYTHON=$(which python3 2>/dev/null || which python 2>/dev/null || echo "")
if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.11+ required but not found."
    exit 1
fi
echo "✓ Python: $PYTHON ($($PYTHON --version))"

# 2. 检查 SSH key
if [ -n "${REMOTE_KEY_PATH:-}" ] && [ -f "$REMOTE_KEY_PATH" ]; then
    echo "✓ SSH key: $REMOTE_KEY_PATH"
elif [ -f "$HOME/.ssh/id_rsa" ]; then
    echo "✓ SSH key: $HOME/.ssh/id_rsa (auto-detected)"
else
    echo "WARNING: No SSH key found at ~/.ssh/id_rsa. Set REMOTE_KEY_PATH or generate one."
fi

# 3. 安装 Python 依赖
echo ""
echo "Installing dependencies..."
cd "$(dirname "$0")"
$PYTHON -m pip install -e .

# 4. 检查连通性
echo ""
echo "=== Connectivity check ==="
if [ -n "${REMOTE_HOST:-}" ]; then
    echo "Testing SSH to ${REMOTE_USER:-root}@$REMOTE_HOST..."
    ssh -o ConnectTimeout=5 -o BatchMode=yes "${REMOTE_USER:-root}@$REMOTE_HOST" "echo 'SSH OK' && pwd && ls -la ${REMOTE_PROJECT_DIR:-/opt/app}" 2>&1 || {
        echo "WARNING: SSH test failed. Check REMOTE_HOST, REMOTE_USER, REMOTE_KEY_PATH."
        echo "You can still proceed, but tools may fail at runtime."
    }
else
    echo "REMOTE_HOST not set — skipping connectivity check."
    echo "Set it in opencode.json's mcpServers config."
fi

echo ""
echo "=== Done ==="
echo ""
echo "Next steps:"
echo "1. Copy opencode.json.example to ~/.config/opencode/opencode.json (or your project's .opencode/opencode.json)"
echo "2. Edit the env values to match your remote environment"
echo "3. Start OpenCode and the remote-executor tools will be available"
echo ""
echo "Or test directly:"
echo "  REMOTE_HOST=x.x.x.x REMOTE_USER=deploy python -m remote_executor_mcp"
