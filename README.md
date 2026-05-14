# Remote Executor MCP —— 使用文档

让本地 AI Agent (OpenCode) 具备远端代码部署、测试执行、日志采集能力，实现 **修改 → 部署 → 测试 → 日志 → 修复** 全自动闭环。

---

## 目录

- [1. 前置条件](#1-前置条件)
- [2. 安装](#2-安装)
- [3. 配置 OpenCode](#3-配置-opencode)
- [4. 验证](#4-验证)
- [5. 使用方式](#5-使用方式)
- [6. 工作流示例](#6-工作流示例)
- [7. 工具参考](#7-工具参考)
- [8. 环境变量参考](#8-环境变量参考)
- [9. 安全模型](#9-安全模型)
- [10. 常见问题](#10-常见问题)

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
# (MCP server 不是命令行工具，会报错是正常的，确认 import 不报错即可)
```

或者使用一键脚本：

```bash
chmod +x setup.sh
./setup.sh
```

---

## 3. 配置 OpenCode

### 3.1 找到配置文件

OpenCode 配置文件位置（优先级从高到低）：

| 文件 | 作用范围 |
|------|---------|
| `项目根目录/.opencode/opencode.json` | 当前项目 |
| `~/.config/opencode/opencode.json` | 当前用户（全局） |
| `~/.opencode.json` | 当前用户（旧版路径） |

选择其中一个即可。推荐放在项目级配置中（`项目根目录/.opencode/opencode.json`）。

### 3.2 添加 MCP Server 配置

```json
{
  "mcpServers": {
    "remote-executor": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "remote_executor_mcp"],
      "env": {
        "REMOTE_HOST": "192.168.1.100",
        "REMOTE_PORT": "22",
        "REMOTE_USER": "deploy",
        "REMOTE_KEY_PATH": "/home/you/.ssh/id_rsa",
        "LOCAL_PROJECT_DIR": "/home/you/projects/myapp",
        "REMOTE_PROJECT_DIR": "/opt/myapp",
        "DEFAULT_TIMEOUT": "300",
        "MAX_LOG_LINES": "500"
      }
    }
  }
}
```

### 3.3 按你的环境修改这些值

| 变量 | 含义 | 示例 |
|------|------|------|
| `REMOTE_HOST` | 远端服务器 IP/域名 | `192.168.1.100` |
| `REMOTE_USER` | SSH 用户名 | `deploy` |
| `REMOTE_KEY_PATH` | SSH 私钥路径 | `/home/you/.ssh/id_rsa` |
| `LOCAL_PROJECT_DIR` | 本地项目根目录 | `/home/you/projects/myapp` |
| `REMOTE_PROJECT_DIR` | 远端项目根目录 | `/opt/myapp` |
| `DEPLOY_SCRIPT` | 远端部署脚本名 | `./deploy.sh` |

### 3.4 安装 Skill（可选但推荐）

将 `opencode/skills/remote-dev/` 目录复制到项目：

```bash
cp -r opencode/skills/remote-dev 你的项目/.opencode/skills/
```

Skill 让 Agent 自动遵循正确的工作流，不需要每次手动指导。

---

## 4. 验证

### 4.1 确认 OpenCode 加载了 MCP

启动 OpenCode 后，输入：

```
/list-tools
```

如果看到以下 5 个工具，说明配置成功：

```
remote-executor:sync_and_deploy
remote-executor:run_test
remote-executor:get_logs
remote-executor:get_status
remote-executor:exec_command
```

### 4.2 手动测试远端连通性

在 OpenCode 中执行：

```
sync_and_deploy 上传一个测试文件
```

或者直接对话：

> 帮我测试一下远端连接是否正常，用 exec_command 在远端执行 `whoami` 和 `pwd`

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

### 方式一：自然语言驱动（推荐）

直接在 OpenCode 中用中文描述任务，Agent 会自动选择合适的 Tool：

> 帮我修复用户登录接口的 500 错误。先看一下远端服务状态，然后改代码，部署测试。

Agent 的执行序列：

1. `get_status(service="myapp")` → 确认服务在运行
2. `get_logs(source="journalctl -u myapp", lines=200)` → 看近期日志
3. 读取本地 `src/api/login.py` → 分析代码
4. 修改 `src/api/login.py` → 修复 bug
5. `sync_and_deploy(files=["src/api/login.py"], deploy_script="systemctl restart myapp")` → 上传部署
6. `run_test(test_command="pytest tests/test_login.py -v")` → 跑测试
7. 如果失败 → `get_logs(...)` → 分析 → 修复 → 回到步骤 5

### 方式二：直接调用 Tool

如果你装了 remote-dev Skill，可以直接用自然语言。但也可以手动指定工具。在 OpenCode 中键入 `/` 触发命令面板，选择对应 Tool。

### 方式三：编写自定义 Command

在 `~/.config/opencode/commands/deploy-test.md`：

```markdown
# Deploy and test the current changes
# 部署当前修改并运行测试

请执行以下步骤：
1. 找出 git 中有变更的文件
2. 调用 sync_and_deploy 上传所有变更文件，并执行部署
3. 调用 run_test 运行全量测试
4. 如果测试失败，调用 get_logs 获取错误日志并分析原因
```

使用：`Ctrl+K` → `user:deploy-test`

---

## 6. 工作流示例

### 6.1 修复单个 Bug

**场景**：API 返回 500，定位到 `src/api/user.py` 的 `get_user` 函数有问题。

```
用户: 帮我修复 get_user 的 500 错误

Agent:
  1. get_logs(source="journalctl -u myapi", lines=100)
     → 发现: KeyError: 'email'

  2. 读取 src/api/user.py:42
     → 发现: user_data['email'] 但数据库没返回 email 字段

  3. 修改代码: user_data.get('email', '')

  4. sync_and_deploy(files=["src/api/user.py"],
                      deploy_script="systemctl restart myapi")
     → 12 files synced, deploy OK

  5. run_test(test_command="pytest tests/test_user.py -v")
     → 8 passed, 0 failed, exit_code=0 ✓

  6. [完成] get_user 500 错误已修复，测试全部通过。
```

### 6.2 开发一个新接口

**场景**：新增 `POST /api/logout` 接口。

```
用户: 帮我实现 POST /api/logout 接口，包括测试

Agent:
  1. [设计并编写代码]
     - src/api/logout.py  (新增)
     - src/api/__init__.py (注册路由)
     - tests/test_logout.py (新增)

  2. sync_and_deploy(files=[
       "src/api/logout.py",
       "src/api/__init__.py",
       "tests/test_logout.py"
     ], deploy_script="systemctl reload myapi")
     → 3 files synced, deploy OK

  3. run_test(test_command="pytest tests/test_logout.py -v")
     → 4 passed, 0 failed ✓

  4. run_test(test_command="pytest tests/ -v")
     → 32 passed, 0 failed ✓   (全量回归通过)

  5. [完成] logout 接口已实现，测试全部通过。
```

### 6.3 排查线上问题

**场景**：不知道什么问题，需要先摸清情况。

```
用户: 远端服务好像不太对，帮我看看

Agent:
  1. get_status(service="myapp")
     → active: true, uptime: 3 days

  2. exec_command(command="df -h")
     → 磁盘正常

  3. exec_command(command="free -m")
     → 内存使用 92%，有问题

  4. get_logs(source="journalctl -u myapp", lines=300)
     → 发现: MemoryError at line 156

  5. exec_command(command="ps aux --sort=-%mem | head -10")
     → myapp 进程占了 4GB

  6. [分析] 可能是内存泄漏。建议增加 swap 并用 memory-profiler 定位。
```

### 6.4 多轮自动修复（Agent 自主循环）

**场景**：一个复杂 bug，Agent 需要多次尝试。

```
用户: 帮我修复 test_payment 的失败，自己部署测试直到通过

Agent:
  Round 1:
    sync_and_deploy(files=["src/payment.py"])  → 部署
    run_test("pytest tests/test_payment.py")   → FAILED (3/5 passed)
    get_logs("journalctl -u myapp", lines=100) → AssertionError: amount mismatch

  Round 2:
    修复金额计算逻辑
    sync_and_deploy(files=["src/payment.py"])  → 部署
    run_test("pytest tests/test_payment.py")   → FAILED (4/5 passed)
    get_logs(...) → 货币精度问题

  Round 3:
    使用 Decimal 替代 float
    sync_and_deploy(files=["src/payment.py"])  → 部署
    run_test("pytest tests/test_payment.py")   → 5/5 passed ✓

  [3 轮后完成]
```

### 6.5 只替换文件不部署

**场景**：修改静态文件、配置文件、文档，不需要重启服务。

```
用户: 帮我把 docs/api.html 里的版本号从 1.0 改成 2.0

Agent:
  1. Read docs/api.html → 找到版本号 "1.0.0"
  2. 修改 docs/api.html → 替换为 "2.0.0"
  3. sync_and_deploy(files=["docs/api.html"])
     → deploy_script 不传，只上传文件
     → 1 file synced, deploy_result: null (跳过部署)

  [完成] 文件已替换，无需重启。
```

**常见不需要部署脚本的场景**：

| 文件类型 | 说明 |
|---------|------|
| `*.html`, `*.css`, `*.js` | 静态资源，Nginx 直接 serve |
| `*.md`, `*.rst` | 文档，构建时自动生效 |
| `*.yaml`, `*.toml`, `*.json` | 配置文件（如果服务自动 reload） |
| `*.txt`, `*.csv` | 数据文件 |
| `templates/*` | 模板文件（如果模板引擎有缓存需注意） |

**如何判断要不要部署脚本**：
- 文件替换后，远端服务能自动检测变更 → 不需要 deploy_script
- 文件替换后，需要重启/重载/reload 才能生效 → 传 deploy_script

---

## 7. 工具参考

### `sync_and_deploy`

同步本地文件到远端并执行部署。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | `string[]` | 是 | 要同步的文件，相对于项目根目录 |
| `deploy_script` | `string` | 否 | 远端部署命令，留空则只同步不部署 |
| `local_dir` | `string` | 否 | 本地项目目录（绝对路径），不填使用配置 |
| `remote_dir` | `string` | 否 | 远端项目目录（绝对路径），不填使用配置 |

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

---

### `run_test`

在远端执行测试命令。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `test_command` | `string` | 是 | 测试命令 |
| `timeout` | `integer` | 否 | 超时秒数，默认 300 |
| `cwd` | `string` | 否 | 远端工作目录，不填使用配置 |

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

**常用命令**：

| 场景 | 命令 |
|------|------|
| 全量测试 | `pytest tests/ -v` |
| 单个文件 | `pytest tests/test_api.py -v` |
| 单个用例 | `pytest tests/test_api.py::test_login -v` |
| 带标记 | `pytest tests/ -m "not slow" -v` |
| 带覆盖率 | `pytest tests/ --cov=src --cov-report=term` |
| npm | `npm test -- --testPathPattern=Login` |
| go | `go test ./... -v` |

---

### `get_logs`

获取远端服务日志。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | `string` | 是 | 日志来源 |
| `lines` | `integer` | 否 | 返回行数，默认 500 |
| `cwd` | `string` | 否 | 远端工作目录 |

**source 三种写法**：

| 类型 | 示例 | 实际执行 |
|------|------|---------|
| systemd | `journalctl -u myapp` | `journalctl -u myapp -n 500 --no-pager` |
| Docker | `docker logs nginx` | `docker logs nginx --tail 500` |
| 文件 | `/var/log/myapp/error.log` | `tail -n 500 /var/log/myapp/error.log` |

**返回**：与 `run_test` 相同的 `CommandResult` 结构，日志内容在 `stdout` 中。

---

### `get_status`

检查远端服务状态。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `service` | `string` | 是 | 服务名或容器名 |

**返回**：

```json
{
  "service": {
    "service_name": "myapp",
    "active": true,
    "status_text": "● myapp.service - MyApp\n   Active: active (running) since Mon 2026-05-12 10:30:00 CST; 2 days ago\n   Main PID: 12345 (python3)",
    "uptime": "Mon 2026-05-12 10:30:00 CST",
    "pid": 12345
  },
  "raw_exit_code": 0
}
```

**注意**：
- 优先使用 `systemctl` 检测
- 如果服务名包含 `docker` 或 `container`，会自动切换到 Docker 检测
- 远端没有 `systemctl` 时，回退到 `ps aux | grep` 方式

---

### `exec_command`

在远端执行受沙箱控制的通用命令。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `command` | `string` | 是 | 要执行的命令 |
| `timeout` | `integer` | 否 | 超时秒数，默认 60 |
| `cwd` | `string` | 否 | 远端工作目录 |

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

---

## 8. 环境变量参考

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REMOTE_HOST` | — **必填** | 远端服务器 IP/域名 |
| `REMOTE_PORT` | `22` | SSH 端口 |
| `REMOTE_USER` | `root` | SSH 用户名 |
| `REMOTE_KEY_PATH` | `~/.ssh/id_rsa` | SSH 私钥路径 |
| `REMOTE_PASSWORD` | — | SSH 密码（不推荐，优先用 Key） |
| `REMOTE_KNOWN_HOSTS` | `~/.ssh/known_hosts` | known_hosts 路径，设为空字符串禁用 |
| `LOCAL_PROJECT_DIR` | 当前工作目录 | 本地项目根目录 |
| `REMOTE_PROJECT_DIR` | `/opt/app` | 远端项目根目录 |
| `DEPLOY_SCRIPT` | `""` (不部署) | 远端默认部署命令，留空则只同步文件不部署 |
| `DEFAULT_TIMEOUT` | `300` | 命令默认超时秒数 |
| `MAX_LOG_LINES` | `500` | 日志默认行数 |
| `CONNECTION_POOL_SIZE` | `3` | SSH 连接池大小 |

---

## 9. 安全模型

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

**在 OpenCode 中配置权限**（按需调整）：

```json
{
  "permission": {
    "mcp:remote-executor:sync_and_deploy": "allow",
    "mcp:remote-executor:run_test": "allow",
    "mcp:remote-executor:get_logs": "allow",
    "mcp:remote-executor:get_status": "allow",
    "mcp:remote-executor:exec_command": "ask"
  }
}
```

建议 `exec_command` 设为 `ask`（每次确认），其他 4 个设为 `allow`。

---

## 10. 常见问题

### Q: OpenCode 启动时报 "Failed to start MCP server"

**可能原因**：

1. **Python 环境问题**：确认 `which python` 指向正确的 Python 3.11+
2. **依赖未安装**：运行 `pip install -e .` 重新安装
3. **远端连不上**：MCP Server 启动时会做健康检查，远端不通会直接退出
4. **SSH 认证失败**：检查 Key 路径、权限（chmod 600 ~/.ssh/id_rsa）

**调试方法**：

```bash
# 手动启动 MCP Server，看 stderr 输出
REMOTE_HOST=192.168.1.100 REMOTE_USER=deploy \
  python -m remote_executor_mcp 2>&1
```

### Q: sync_and_deploy 成功但部署没生效

检查 `deploy_script` 是否正确。常见问题：

- `systemctl restart myapp` 需要 sudo → 确认远端用户有 sudo 免密权限
- 部署脚本路径错误 → 部署脚本是相对于 `REMOTE_PROJECT_DIR` 的

```bash
# 在远端验证
ssh deploy@192.168.1.100 "cd /opt/myapp && ./deploy.sh"
```

### Q: 测试超时怎么办

增大 `timeout` 参数：

```
run_test(test_command="pytest tests/slow/ -v", timeout=600)
```

或者在配置中修改默认超时 `DEFAULT_TIMEOUT=600`。

### Q: 想执行一个不在白名单里的命令

两种方式：

1. **修改白名单**：编辑 `src/remote_executor_mcp/sandbox.py` 中的 `ALLOWED_COMMANDS`
2. **通过 allowed 命令变通**：例如 `sh -c "your_command"` —— 但 sh/bash 本身在白名单中

### Q: 日志里有敏感信息

`sandbox.py` 的 `sanitize_for_log()` 会自动脱敏 `--password`、`--token`、`--secret` 等。如果你有特殊敏感参数，在 `sanitize_for_log` 中添加对应的正则即可。

### Q: 如何去掉 exec_command 的每次确认

在 `opencode.json` 中设置：

```json
{
  "permission": {
    "mcp:remote-executor:exec_command": "allow"
  }
}
```

但**不推荐**，`exec_command` 是最危险的接口，建议保持 `ask`。

---

## 附录：快速检查清单

部署后逐项确认：

- [ ] SSH 免密登录远端正常：`ssh deploy@host "echo ok"`
- [ ] 远端项目目录存在且有写权限：`ssh deploy@host "ls /opt/myapp"`
- [ ] Python 3.11+: `python --version`
- [ ] 依赖安装：`pip list | grep -E "mcp|asyncssh"`
- [ ] opencode.json 中 REMOTE_HOST 等变量已修改为实际值
- [ ] OpenCode 启动后 `/list-tools` 可以看到 5 个 remote-executor 工具
- [ ] `exec_command "whoami"` 返回远端用户名
- [ ] `sync_and_deploy` + `run_test` 端到端走通
