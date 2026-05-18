# Remote Executor MCP —— 使用文档

让本地 AI Agent（运行在 Windows / macOS / Linux）具备远端 Linux 服务器的代码部署、命令执行能力，实现 **修改 → 部署 → 测试 → 修复** 全自动闭环。

---

## 目录

- [1. 架构概览](#1-架构概览)
- [2. 前置条件](#2-前置条件)
- [3. 安装](#3-安装)
- [4. 配置](#4-配置)
- [5. OpenCode 配置](#5-opencode-配置)
- [6. 验证](#6-验证)
- [7. 使用方式](#7-使用方式)
- [8. 工具参考](#8-工具参考)
- [9. 安全模型](#9-安全模型)
- [10. AI Skill 配置](#10-ai-skill-配置)
- [11. 常见问题](#11-常见问题)

---

## 1. 架构概览

```
┌─────────────────┐      MCP (stdio)       ┌──────────────────┐      SSH/SFTP       ┌──────────────────┐
│   AI Agent      │ ◄──────────────────────►│  remote-executor │ ◄───────────────────►│  Remote Linux    │
│  (OpenCode/     │                        │  MCP Server      │                      │  Server          │
│   Claude Code)  │   sync_and_deploy      │  (本机运行)       │   ConnectionPool     │  (目标服务器)     │
│                 │   exec_command         │                  │   Sandbox            │                  │
│   本机 (可 Windows)                       │  端口: stdio      │   端口: SSH 22       │   必须 Linux      │
└─────────────────┘                        └──────────────────┘                      └──────────────────┘
```

**核心约束**：
- AI Agent 和 MCP Server 运行在**本机**（Windows / macOS / Linux 均可）
- 远端服务器必须是 **Linux**（通过 SSH 连接）
- 代码修改在**本机**完成，通过 `sync_and_deploy` 同步到远端
- 远端命令执行受**沙箱白名单**控制

---

## 2. 前置条件

### 本机要求

| 项目 | Windows | macOS / Linux |
|------|---------|---------------|
| Python | 3.11+ ([python.org](https://python.org) 下载或 `winget install python`) | 3.11+ |
| Shell | **Git Bash**（推荐）或 WSL | 系统自带 |
| SSH Key | `%USERPROFILE%\.ssh\id_rsa`（或 Git Bash 下 `~/.ssh/id_rsa`） | `~/.ssh/id_rsa` |
| OpenCode | `iwr -Uri https://opencode.dev/install.ps1 \| iex`（PowerShell） | `curl -sSL https://opencode.dev/install.sh \| bash` |

> **Windows 用户强烈建议使用 Git Bash**：
> ```powershell
> winget install Git.Git
> ```
> 安装后在 Git Bash 中执行所有命令。Git Bash 提供 Unix 风格的 shell 环境，路径用 `/c/Users/...` 格式。

### 远端服务器要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Linux（任何发行版） |
| SSH | 可通过 SSH 免密登录 |
| 项目目录 | 代码已部署在远端，如 `/opt/myapp` |
| 权限 | 对项目目录有读写权限，能重启服务（可能需要 sudo） |

### 检查 SSH 连通性

**Windows（Git Bash）**：
```bash
ssh deploy@192.168.1.100 "whoami && pwd && ls /opt/myapp"
```

**macOS / Linux**：
```bash
ssh deploy@192.168.1.100 "whoami && pwd && ls /opt/myapp"
```

必须能免密登录并看到远端项目目录。如果提示输入密码，先配置 SSH Key：

```bash
# 生成密钥（如果还没有）
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N ""

# 上传公钥到远端
ssh-copy-id deploy@192.168.1.100
```

**Windows 特别注意**：
- Git Bash 中的 `~` 展开为 `%USERPROFILE%`（即 `C:\Users\<用户名>`）
- SSH Key 文件权限：Git Bash 中密钥权限通常会自动处理；如果遇到 "permissions are too open" 错误：
  ```bash
  chmod 600 ~/.ssh/id_rsa
  ```

---

## 3. 安装

### Windows（Git Bash）

```bash
cd /d/WorkSpace/company_project   # Git Bash 路径格式

# 安装 Python 依赖
pip install -e .

# 确认安装成功
python -m remote_executor_mcp 2>&1 || true
```

也可以使用一键脚本（Git Bash 中）：
```bash
bash setup.sh
```

如果 `pip` 或 `python` 找不到，检查 Python 是否在 PATH 中：
```bash
# 确认 Python 路径
which python3 || which python

# 或使用 Windows 原生路径
/c/Users/$USERNAME/AppData/Local/Programs/Python/Python312/python -m pip install -e .
```

### macOS / Linux

```bash
cd /path/to/company_project

# 安装 Python 依赖
pip install -e .

# 确认安装成功
python -m remote_executor_mcp --help 2>&1 || true
```

或者使用一键脚本：
```bash
chmod +x setup.sh
./setup.sh
```

---

## 4. 配置

在项目根目录创建 `remote-executor.yaml`（可以从 `remote-executor.yaml.example` 复制）。

### 4.1 基础配置

```yaml
local_project_dir: /d/WorkSpace/myapp      # 本机项目路径（Windows Git Bash 用 /d/ 格式）
default_timeout: 300

servers:
  prod:
    host: 192.168.1.100
    port: 22
    user: deploy
    key_path: ~/.ssh/id_rsa
    project_dir: /opt/myapp                 # 远端项目路径（必须是 Linux 路径格式）

  staging:
    host: 192.168.1.101
    port: 22
    user: deploy
    key_path: ~/.ssh/id_rsa
    project_dir: /opt/staging
```

不传 `server` 参数时使用第一个配置的服务器。

### 4.2 Windows 下配置注意事项

**`local_project_dir` 路径格式**（Git Bash）：
```yaml
# Git Bash 风格的绝对路径
local_project_dir: /d/WorkSpace/company_project

# 或使用 Windows 原生路径（需要转义反斜杠或使用正斜杠）
local_project_dir: D:/WorkSpace/company_project
```
推荐使用 `D:/...` 格式，兼容性最好。

**`key_path`**：
```yaml
# Git Bash 风格（推荐）
key_path: ~/.ssh/id_rsa

# 或 Windows 绝对路径
key_path: C:/Users/你的用户名/.ssh/id_rsa

# 注意：反斜杠在 YAML 中需要转义
key_path: C:\\Users\\你的用户名\\.ssh\\id_rsa   # 不推荐，用正斜杠更简单
```

### 4.3 完整配置参考

| YAML 字段 | 默认值 | 说明 |
|-----------|--------|------|
| `local_project_dir` | 当前目录 | 本机项目根目录 |
| `default_timeout` | `300` | 命令默认超时秒数 |
| `servers.<name>.host` | — **必填** | 远端服务器 IP/域名 |
| `servers.<name>.user` | `root` | SSH 用户名 |
| `servers.<name>.key_path` | — | SSH 私钥路径（与 `password` 二选一） |
| `servers.<name>.password` | — | SSH 密码（不配置 `key_path` 时使用） |
| `servers.<name>.port` | `22` | SSH 端口 |
| `servers.<name>.project_dir` | `/opt/app` | 远端项目根目录 |
| `servers.<name>.become_user` | — | SSH 登录后通过 sudo 切换到的用户（如 `root`） |
| `servers.<name>.become_password` | — | sudo 提权密码（需 `become_user` 同时配置），免密 sudo 则不填 |
| `servers.<name>.connection_pool_size` | `3` | SSH 连接池大小 |

配置文件路径也可以通过环境变量指定：

**Windows（Git Bash / PowerShell）**：
```bash
# Git Bash
export REMOTE_EXECUTOR_CONFIG=/d/WorkSpace/company_project/my-config.yaml

# PowerShell
$env:REMOTE_EXECUTOR_CONFIG = "D:\WorkSpace\company_project\my-config.yaml"
```

---

## 5. OpenCode 配置

要让 OpenCode 启动时自动加载 remote-executor MCP Server，需要在项目根目录创建 `opencode.json` 文件。

### 5.1 创建 opencode.json

从示例文件复制：

```bash
cp opencode.json.example opencode.json
```

内容如下：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcpServers": {
    "remote-executor": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "remote_executor_mcp"]
    }
  }
}
```

| 字段 | 说明 |
|------|------|
| `type` | `"stdio"` — 通过标准输入/输出与 MCP Server 通信 |
| `command` | 启动 MCP Server 的命令 |
| `args` | 命令参数，`-m remote_executor_mcp` 表示以模块方式运行 |

### 5.2 Windows 下的配置

如果 `python` 不在 PATH 中，使用完整路径：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcpServers": {
    "remote-executor": {
      "type": "stdio",
      "command": "C:/Users/你的用户名/AppData/Local/Programs/Python/Python312/python",
      "args": ["-m", "remote_executor_mcp"]
    }
  }
}
```

**查找 Python 路径**（Git Bash / PowerShell）：
```bash
# Git Bash
which python

# PowerShell
(Get-Command python).Source
```

如果使用虚拟环境，指向 venv 中的 Python：
```json
{
  "command": "./venv/Scripts/python",
  "args": ["-m", "remote_executor_mcp"]
}
```

### 5.3 指定配置文件路径

如果你的 `remote-executor.yaml` 不在项目根目录，通过环境变量指定：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcpServers": {
    "remote-executor": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "remote_executor_mcp"],
      "env": {
        "REMOTE_EXECUTOR_CONFIG": "D:/WorkSpace/company_project/remote-executor.yaml"
      }
    }
  }
}
```

### 5.4 配置权限

在 `opencode.json` 中为 MCP 工具设置权限级别：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcpServers": {
    "remote-executor": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "remote_executor_mcp"]
    }
  },
  "permission": {
    "mcp:remote-executor:sync_and_deploy": "allow",
    "mcp:remote-executor:exec_command": "ask"
  }
}
```

**权限级别**：

| 级别 | 行为 |
|------|------|
| `allow` | 无需确认，直接执行 |
| `ask` | 每次执行前弹出确认对话框 |
| `deny` | 禁止执行 |

**建议**：
- `sync_and_deploy` → `allow`（文件上传相对安全）
- `exec_command` → `ask`（远端命令执行应保持审查）

---

## 6. 验证

### 6.1 确认 OpenCode 加载了 MCP

启动 OpenCode 后，输入：

```
/list-tools
```

如果看到以下 2 个工具，说明配置成功：

```
remote-executor:sync_and_deploy
remote-executor:exec_command
```

### 6.2 手动测试远端连通性

在 OpenCode 对话框中输入：

> 在远端执行 hostname && pwd

期望返回：

```json
{
  "success": true,
  "exit_code": 0,
  "stdout": "deploy\n/opt/myapp\n",
  "stderr": "",
  ...
}
```

### 6.3 MCP 启动失败排查

**Windows 常见问题**：

```bash
# 手动启动看完整错误日志
REMOTE_EXECUTOR_CONFIG=./remote-executor.yaml python -m remote_executor_mcp
```

常见报错：
- `No config file found` → 检查 YAML 文件路径
- `SSH key not found` → 检查 `key_path`，Windows 下确认使用正斜杠格式
- `Failed health check` → 检查 SSH 连通性、网络、防火墙

---

## 7. 使用方式

### 7.1 自然语言驱动（推荐）

直接在 AI Agent 中用中文描述任务，Agent 会自动选择合适的 Tool：

> 帮我修复用户登录接口的 500 错误。先看一下远端服务状态，然后改代码，部署测试。

Agent 的执行序列：

1. `exec_command("systemctl status myapp")` → 确认服务在运行
2. `exec_command("journalctl -u myapp -n 200 --no-pager")` → 看近期日志
3. 读取本机 `src/api/login.py` → 分析代码
4. **在本机**修改 `src/api/login.py` → 修复 bug
5. `sync_and_deploy(files=["src/api/login.py"], deploy_script="systemctl restart myapp")` → 上传并部署
6. `exec_command("pytest tests/test_login.py -v", server="prod")` → 跑测试
7. 如果失败 → 看日志 → 分析 → **本机**修复 → 回到步骤 5

> **关键**：所有代码修改都在**本机**完成，远端只负责执行。Agent 绝不会在远端直接编辑文件。

### 7.2 多服务器切换

```
# 先在 staging 上测试
sync_and_deploy(files=["src/api/user.py"], server="staging")
exec_command("pytest tests/test_user.py -v", server="staging")

# 确认通过后再上 prod
sync_and_deploy(files=["src/api/user.py"], deploy_script="systemctl restart myapp", server="prod")
exec_command("pytest tests/test_user.py -v", server="prod")
```

---

## 8. 工具参考

### `sync_and_deploy`

同步本机文件到远端并可选执行部署命令。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | `string[]` | 是 | 要同步的文件，相对于项目根目录 |
| `deploy_script` | `string` | 否 | 远端部署命令，留空则只同步不部署 |
| `local_dir` | `string` | 否 | 本机项目目录（绝对路径） |
| `remote_dir` | `string` | 否 | 远端项目目录（绝对路径） |
| `server` | `string` | 否 | 目标服务器名称，不填使用默认服务器 |

**返回**：

```json
{
  "files_synced": ["src/api/user.py", "tests/test_user.py"],
  "files_failed": [],
  "total_bytes": 12345,
  "deploy_result": {
    "success": true,
    "exit_code": 0,
    "stdout": "Restarting myapp... OK",
    "stderr": "",
    "duration_ms": 2340
  },
  "duration_ms": 3450
}
```

**注意**：
- 文件路径必须相对于项目根目录
- 远端父目录不存在时会自动创建
- 使用 SFTP 上传，每次全量传
- 不传 `deploy_script` 则只上传文件，不执行任何部署操作
- **禁止**同步 `.env`、`credentials.*`、`*.pem` 等包含密钥的文件

### `exec_command`

在远端服务器上执行沙箱受控的命令。命令会经过白名单和危险模式检查。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `command` | `string` | 是 | 要执行的命令 |
| `timeout` | `integer` | 否 | 超时秒数，默认 60 |
| `cwd` | `string` | 否 | 远端工作目录 |
| `server` | `string` | 否 | 目标服务器名称，不填使用默认服务器 |

**返回**：

```json
{
  "success": false,
  "exit_code": 1,
  "stdout": "tests/test_api.py::test_login FAILED\n...",
  "stderr": "AssertionError: expected 200, got 500",
  "duration_ms": 12300,
  "command": "pytest tests/test_api.py -v",
  "host": "192.168.1.100",
  "cwd": "/opt/myapp"
}
```

**常用命令示例**：

| 场景 | 命令 |
|------|------|
| 全量测试 | `pytest tests/ -v` |
| 单个文件 | `pytest tests/test_api.py -v` |
| 单个用例 | `pytest tests/test_api.py::test_login -v` |
| 查看日志 | `journalctl -u myapp -n 200 --no-pager` |
| Docker 日志 | `docker logs myapp --tail 200` |
| 日志文件 | `tail -n 200 /var/log/app.log` |
| 检查服务 | `systemctl status myapp` |
| 磁盘/内存 | `df -h` / `free -m` |
| 进程列表 | `ps aux --sort=-%mem \| head -10` |

---

## 9. 安全模型

```
用户请求
    │
    ▼
AI Agent 权限检查 (allow / ask / deny)
    │
    ▼
MCP Server (stdio)
    │
    ▼
Sandbox ──────────────────────┐
│  1. 命令解析 (shlex)        │
│  2. 白名单检查 (40+ 命令)    │
│  3. 危险模式匹配 (15+ 正则)  │
│  4. 敏感命令审计日志         │
│  5. 密钥脱敏                │
└────────────┬────────────────┘
             │
             ▼
      ConnectionPool
             │
             ▼
       SSH → 远端服务器
```

**允许的命令**：

| 类别 | 命令 |
|------|------|
| 测试 | pytest, tox, unittest |
| 解释器 | python, python3, node, ruby |
| 服务管理 | systemctl, journalctl |
| 容器 | docker, docker-compose, podman |
| 编排 | kubectl, helm |
| 包管理 | pip, pip3, npm, yarn, pnpm, poetry, cargo, go |
| 构建 | make, cmake, ninja |
| 版本控制 | git |
| 只读文件 | ls, cat, head, tail, grep, find, wc, stat, du, df |
| 进程 | ps, pgrep, top, htop |
| 网络 | ss, netstat, curl, wget, ping |

**永远被拦截的命令**：

- `rm -rf /` 及变体
- `dd if=... of=/dev/...`
- `mkfs.*`、`fdisk`、`parted`
- `chmod 777 /`、`chown -R /`
- `reboot`、`shutdown`、`halt`
- fork bomb
- 写入 `/etc/` 的 curl/wget

**在 OpenCode 中配置权限**：

```json
{
  "permission": {
    "mcp:remote-executor:sync_and_deploy": "allow",
    "mcp:remote-executor:exec_command": "ask"
  }
}
```

建议 `exec_command` 设为 `ask`（每次确认），`sync_and_deploy` 设为 `allow`。

---

## 10. AI Skill 配置

本项目包含一个 AI Skill 文件 `opencode/skills/remote-dev/SKILL.md`，定义了远端开发的完整工作流：

- **触发条件**：检测到 `remote-executor.yaml` 且用户涉及代码修改/测试/部署
- **本地优先**：所有代码修改在本机完成，通过 `sync_and_deploy` 同步到远端
- **自动发现**：自动探测远端服务、日志、测试框架和参数
- **Memory 驱动**：用户确认的信息和固定参数自动记录，下次直接使用
- **测试闭环**：本地生成测试 → 同步 → 远端执行 → 修复迭代

Skill 会在 AI Agent 中自动激活，无需手动调用。

---

## 11. 常见问题

### Q1: OpenCode 启动时报 "Failed to start MCP server"

**Linux / macOS** — 可能原因：

1. **Python 环境问题**：确认 Python 3.11+
2. **依赖未安装**：运行 `pip install -e .` 重新安装
3. **远端连不上**：MCP Server 启动时会做健康检查，远端不通会直接退出
4. **SSH 认证失败**：检查 Key 路径、权限（`chmod 600 ~/.ssh/id_rsa`）

**Windows** — 额外检查：

1. Python 是否在 PATH 中？尝试使用完整路径：`C:/Users/.../AppData/Local/Programs/Python/Python312/python -m remote_executor_mcp`
2. SSH Key 路径在 YAML 中是否使用了正斜杠格式？（不要用 `\`）
3. Git Bash 中能否直接 `ssh user@host` 连通？

调试方法（所有平台）：
```bash
REMOTE_EXECUTOR_CONFIG=./remote-executor.yaml python -m remote_executor_mcp 2>&1
# 或 Windows PowerShell:
# $env:REMOTE_EXECUTOR_CONFIG = ".\remote-executor.yaml"
# python -m remote_executor_mcp 2>&1
```

### Q2: sync_and_deploy 成功但部署没生效

检查 `deploy_script` 是否正确：
- `systemctl restart myapp` 需要 sudo → 确认远端用户有 sudo 免密权限，或配置了 `become_user`
- 部署脚本路径是相对于远端 `project_dir` 的

```bash
ssh deploy@192.168.1.100 "cd /opt/myapp && sudo systemctl restart myapp"
```

### Q3: Windows 下 YAML 配置的 `key_path` 怎么写

推荐使用正斜杠：
```yaml
key_path: C:/Users/你的用户名/.ssh/id_rsa
# 或 Git Bash 风格（在 Git Bash 中有效）
key_path: ~/.ssh/id_rsa
```

### Q4: 想执行一个不在白名单里的命令

编辑 `src/remote_executor_mcp/sandbox.py` 中的 `ALLOWED_COMMANDS`。

### Q5: 如何去掉 exec_command 的每次确认

在 `opencode.json` 中设置：

```json
{
  "permission": {
    "mcp:remote-executor:exec_command": "allow"
  }
}
```

但不推荐，`exec_command` 是最危险的接口，建议保持 `ask`。

### Q6: 如何添加第二台服务器

在 YAML 配置文件中的 `servers` 下添加新的配置块即可，代码无需任何改动。示例见 [4.1 基础配置](#41-基础配置)。

### Q7: Windows Git Bash vs WSL 如何选择

| 场景 | 推荐 |
|------|------|
| 日常开发命令行 | **Git Bash**（轻量、启动快、与 VS Code / PyCharm 集成好） |
| 需要完整的 Linux 环境 | **WSL**（如项目依赖 Linux-only 的包） |

两种方式都经过验证可用。YAML 配置中的路径格式略有不同：
- Git Bash: `local_project_dir: /d/WorkSpace/myapp`
- WSL: `local_project_dir: /mnt/d/WorkSpace/myapp`

### Q8: Windows 防火墙阻止 SSH 连接

如果远端连接超时，检查 Windows 防火墙出站规则：
```powershell
# PowerShell 管理员权限
New-NetFirewallRule -DisplayName "SSH Out" -Direction Outbound -Protocol TCP -RemotePort 22 -Action Allow
```

---

## 附录：快速检查清单

- [ ] 本机 SSH 免密登录远端正常：`ssh deploy@host "echo ok"`
- [ ] 远端项目目录存在且有写权限：`ssh deploy@host "ls /opt/myapp"`
- [ ] Python 3.11+: `python --version`
- [ ] 依赖安装：`pip list | grep -E "mcp\|asyncssh\|yaml"`
- [ ] 已创建 `remote-executor.yaml`（从 `.example` 复制并编辑）
- [ ] **Windows**: YAML 中路径使用正斜杠格式（`D:/WorkSpace/...` 或 Git Bash 风格）
- [ ] OpenCode 启动后 `/list-tools` 可以看到 2 个 remote-executor 工具
- [ ] `exec_command "hostname"` 返回远端主机名
- [ ] `sync_and_deploy` + `exec_command` 端到端走通
