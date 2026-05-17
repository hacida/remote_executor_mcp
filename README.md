# Remote Executor MCP —— 使用文档

让本地 AI Agent 具备远端代码部署、命令执行能力，实现 **修改 → 部署 → 测试 → 修复** 全自动闭环。

---

## 目录

- [1. 前置条件](#1-前置条件)
- [2. 安装](#2-安装)
- [3. 配置](#3-配置)
- [4. 验证](#4-验证)
- [5. 使用方式](#5-使用方式)
- [6. 工具参考](#6-工具参考)
- [7. 安全模型](#7-安全模型)
- [8. 常见问题](#8-常见问题)

---

## 1. 前置条件

| 项目 | 要求 |
|------|------|
| Python | 3.11+ |
| OpenCode | 最新版 (`curl -sSL https://opencode.dev/install.sh \| bash`) |
| 远端服务器 | Linux，可通过 SSH 免密登录 |
| SSH Key | 本地已有 `~/.ssh/id_rsa`，且公钥已添加到远端 `~/.ssh/authorized_keys` |
| 远端项目目录 | 代码已部署在远端，例如 `/opt/myapp` |

### 1.1 检查 SSH 连通性

```bash
ssh deploy@192.168.1.100 "whoami && pwd && ls /opt/myapp"
```

必须能免密登录并看到远端项目目录。如果不能，先配置 SSH：

```bash
ssh-copy-id deploy@192.168.1.100
```

---

## 2. 安装

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

## 3. 配置

在项目根目录创建 `remote-executor.yaml`：

```yaml
local_project_dir: /home/you/projects/myapp
default_timeout: 300

servers:
  prod:
    host: 192.168.1.100
    port: 22
    user: deploy
    key_path: ~/.ssh/id_rsa
    project_dir: /opt/myapp

  staging:
    host: 192.168.1.101
    port: 22
    user: deploy
    key_path: ~/.ssh/id_rsa
    project_dir: /opt/staging
```

服务器按名字引用，工具调用时通过 `server` 参数指定目标：

```
exec_command(command="pytest tests/ -v", server="prod")
exec_command(command="pytest tests/ -v", server="staging")
```

不传 `server` 则使用第一个配置的服务器。

配置文件路径也可以通过环境变量 `REMOTE_EXECUTOR_CONFIG` 指定。

| YAML 字段 | 默认值 | 说明 |
|-----------|--------|------|
| `local_project_dir` | 当前目录 | 本地项目根目录 |
| `default_timeout` | `300` | 命令默认超时秒数 |
| `servers.<name>.host` | — **必填** | 远端服务器 IP/域名 |
| `servers.<name>.user` | `root` | SSH 用户名 |
| `servers.<name>.key_path` | — | SSH 私钥路径 |
| `servers.<name>.password` | — | SSH 密码（不配置 key_path 时使用） |
| `servers.<name>.port` | `22` | SSH 端口 |
| `servers.<name>.project_dir` | `/opt/app` | 远端项目根目录 |
| `servers.<name>.become_user` | — | 通过 sudo 切换到的用户（如 `root`），SSH 登录后再提权 |
| `servers.<name>.become_password` | — | sudo 提权时的密码（需要 `become_user` 也配置）。不填则假定 sudo 免密 |
| `servers.<name>.connection_pool_size` | `3` | SSH 连接池大小 |

---

## 4. 验证

### 4.1 确认 OpenCode 加载了 MCP

启动 OpenCode 后，输入：

```
/list-tools
```

如果看到以下 2 个工具，说明配置成功：

```
remote-executor:sync_and_deploy
remote-executor:exec_command
```

### 4.2 手动测试远端连通性

在 OpenCode 中执行：

```
exec_command "hostname && pwd"
```

期望输出：

```json
{
  "success": true,
  "exit_code": 0,
  "stdout": "deploy\n/opt/myapp\n",
  "stderr": "",
  ...
}
```

---

## 5. 使用方式

### 自然语言驱动（推荐）

直接在 OpenCode 中用中文描述任务，Agent 会自动选择合适的 Tool：

> 帮我修复用户登录接口的 500 错误。先看一下远端服务状态，然后改代码，部署测试。

Agent 的执行序列：

1. `exec_command("systemctl status myapp")` → 确认服务在运行
2. `exec_command("journalctl -u myapp -n 200 --no-pager")` → 看近期日志
3. 读取本地 `src/api/login.py` → 分析代码
4. 修改 `src/api/login.py` → 修复 bug
5. `sync_and_deploy(files=["src/api/login.py"], deploy_script="systemctl restart myapp")` → 上传部署
6. `exec_command("pytest tests/test_login.py -v", server="prod")` → 跑测试
7. 如果失败 → `exec_command("journalctl -u myapp -n 200 --no-pager")` → 分析 → 修复 → 回到步骤 5

### 多服务器切换

```
# 先在 staging 上测试
sync_and_deploy(files=["src/api/user.py"], server="staging")
exec_command("pytest tests/test_user.py -v", server="staging")

# 确认通过后再上 prod
sync_and_deploy(files=["src/api/user.py"], deploy_script="systemctl restart myapp", server="prod")
exec_command("pytest tests/test_user.py -v", server="prod")
```

---

## 6. 工具参考

### `sync_and_deploy`

同步本地文件到远端并可选执行部署命令。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | `string[]` | 是 | 要同步的文件，相对于项目根目录 |
| `deploy_script` | `string` | 否 | 远端部署命令，留空则只同步不部署 |
| `local_dir` | `string` | 否 | 本地项目目录（绝对路径） |
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
- SFTP 上传，不是 rsync（每次都全量传）
- 不传 `deploy_script` 则只上传文件，不执行任何部署操作

---

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

## 7. 安全模型

```
用户请求
    │
    ▼
OpenCode 权限检查 (allow / ask / deny)
    │
    ▼
MCP Server
    │
    ▼
Sandbox ──────────────────────┐
│  1. 命令解析 (shlex)         │
│  2. 白名单检查 (40+ 命令)     │
│  3. 危险模式匹配 (15+ 正则)   │
│  4. 敏感命令审计日志          │
│  5. 密钥脱敏                 │
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

## 8. 常见问题

### Q: OpenCode 启动时报 "Failed to start MCP server"

可能原因：

1. **Python 环境问题**：确认 Python 3.11+
2. **依赖未安装**：运行 `pip install -e .` 重新安装
3. **远端连不上**：MCP Server 启动时会做健康检查，远端不通会直接退出
4. **SSH 认证失败**：检查 Key 路径、权限（chmod 600 ~/.ssh/id_rsa）

调试方法：

```bash
REMOTE_EXECUTOR_CONFIG=/path/to/remote-executor.yaml python -m remote_executor_mcp 2>&1
```

### Q: sync_and_deploy 成功但部署没生效

检查 `deploy_script` 是否正确：
- `systemctl restart myapp` 需要 sudo → 确认远端用户有 sudo 免密权限
- 部署脚本路径是相对于远端 `project_dir` 的

```bash
ssh deploy@192.168.1.100 "cd /opt/myapp && ./deploy.sh"
```

### Q: 想执行一个不在白名单里的命令

编辑 `src/remote_executor_mcp/sandbox.py` 中的 `ALLOWED_COMMANDS`。

### Q: 如何去掉 exec_command 的每次确认

在 `opencode.json` 中设置：

```json
{
  "permission": {
    "mcp:remote-executor:exec_command": "allow"
  }
}
```

但不推荐，`exec_command` 是最危险的接口，建议保持 `ask`。

### Q: 如何添加第二台服务器

使用 YAML 配置文件（方式一），在 `servers` 下添加新的配置块即可。代码无需任何改动。

---

## 附录：快速检查清单

- [ ] SSH 免密登录远端正常：`ssh deploy@host "echo ok"`
- [ ] 远端项目目录存在且有写权限：`ssh deploy@host "ls /opt/myapp"`
- [ ] Python 3.11+: `python --version`
- [ ] 依赖安装：`pip list | grep -E "mcp|asyncssh|yaml"`
- [ ] 已创建 `remote-executor.yaml` 或配置了环境变量
- [ ] OpenCode 启动后 `/list-tools` 可以看到 2 个 remote-executor 工具
- [ ] `exec_command "hostname"` 返回远端主机名
- [ ] `sync_and_deploy` + `exec_command` 端到端走通
