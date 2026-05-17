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
if [ -f "$HOME/.ssh/id_rsa" ]; then
    echo "✓ SSH key: $HOME/.ssh/id_rsa (auto-detected)"
else
    echo "WARNING: No SSH key found at ~/.ssh/id_rsa. Generate one or set key_path in remote-executor.yaml."
fi

# 3. 安装 Python 依赖
echo ""
echo "Installing dependencies..."
cd "$(dirname "$0")"
$PYTHON -m pip install -e .

# 4. 检查配置文件
echo ""
echo "=== Configuration ==="
if [ -f "remote-executor.yaml" ]; then
    echo "✓ remote-executor.yaml found"
else
    echo "Copy remote-executor.yaml.example to remote-executor.yaml and edit it:"
    echo "  cp remote-executor.yaml.example remote-executor.yaml"
fi

echo ""
echo "=== Done ==="
echo ""
echo "Next steps:"
echo "1. Create remote-executor.yaml from the example and edit server details"
echo "2. Configure OpenCode to launch this MCP server (see README)"
echo "3. Start OpenCode and the remote-executor tools will be available"
