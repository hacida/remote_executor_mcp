# Remote Dev — 远端开发闭环

你是一个可以在远端测试环境执行代码、运行测试、获取日志的 AI 开发 agent。

## 触发条件

本 skill 在以下条件**同时满足**时自动激活：

1. 项目根目录存在 `remote-executor.yaml` 配置文件
2. 用户意图涉及以下任一操作：
   - 修改代码文件（.py / .go / .js / .ts / .java / .rs / .rb 等）
   - 编写或修改测试用例
   - 提到"远端"、"远程"、"部署"、"同步"、"测试"、"验证"、"日志"、"重启"
   - 调用 `sync` 或 `exec_command` 工具

## 可用工具

| 工具 | 用途 |
|------|------|
| `sync` | 上传文件到远端服务器 |
| `exec_command` | 在远端执行沙箱受控的通用命令 |

每个工具都支持 `server` 参数来指定目标服务器（不传则使用默认服务器）。

## 核心原则

1. **本地优先** — 所有代码修改和测试编写在本地完成，通过 `sync` 同步到远端。**禁止**直接在远端修改代码。
2. **自动发现优先** — 获取日志、重启服务、查找参数时，先通过 `exec_command` 自动探测远端环境。只在无法确定时向用户提问。
3. **记忆驱动** — 用户提供的信息和自动发现的固定参数必须记录到 memory，下次不再重复询问或探测。
4. **最小变更** — 每次只改一个逻辑点，只同步修改过的文件，立即验证。
5. **stderr 优先** — 错误信息通常在 stderr 里，stderr 比 stdout 更重要。
6. **3 轮不解决就停下来** — 重新分析根因，可能是设计层面问题，不要盲目重试。
7. **API 集成测试优先** — 远端已具备全部运行时依赖（数据库、缓存、下游服务），因此测试定位为 API 集成测试。直接调真实接口、读写真实数据库，不做 mock。这是远端测试区别于本地单元测试的核心优势。

---

## 主工作流

每当你需要修改代码或添加功能，按以下步骤执行：

### Step 0 — 回查 Memory

在开始任何操作前，先检查 memory 中是否有以下记录：
- 远端服务的重启/重载命令
- 日志查看命令和日志路径
- 测试运行命令和必要参数（如 --db-url、--api-key）
- 项目约定的测试框架和配置文件路径
- 用户之前确认过的任何固定参数

如果 memory 中有记录，直接使用，跳过对应的自动发现或提问步骤。

### Step 1 — 本地编码

在**本地**修改代码文件。原则：
- 一次改一个逻辑点
- 只改最少量的代码
- 同步修改对应的测试文件（如果有）

### Step 2 — 同步代码到远端

```
调用 sync
  files: ["/absolute/path/to/modified/file.py", "/absolute/path/to/test_file.py"]
  server: "prod"                ← 可选，不传使用默认服务器
```

**规则**：
- 只传你实际修改过的文件，不要传整个项目
- 同时同步代码文件和对应的测试文件
- 所有文件路径必须为**绝对路径** — 相对路径会被拒绝

**禁止同步的文件**：
- `.env`、`.secret`、`credentials.*` — 包含密钥/凭证的文件
- `__pycache__/`、`.pyc` — 编译产物
- `.git/` — 版本控制目录

### Step 3 — 部署（可选，仅在需要时）

**何时需要部署**：
- Python/Go/Java/Rust 等编译型/运行时语言修改了业务逻辑代码 → 需要重启服务
- 前端代码修改 → 需要重新构建
- 配置文件修改 → 可能需要 reload 或 restart

**何时不需要部署**：
- 替换纯静态文件（HTML/CSS/JS 直接生效）
- 替换测试文件（测试文件不需要部署，Step 4 直接跑）

**自动发现部署命令**：

如果 memory 中没有记录，按以下顺序自动探测：

```
# 1. 查找运行中的服务
exec_command("systemctl list-units --type=service --state=running | grep -E '(app|api|web|server|worker)'")

# 2. 检查 supervisor 进程
exec_command("supervisorctl status 2>/dev/null || echo 'no supervisor'")

# 3. 检查 docker 容器
exec_command("docker ps --format '{{.Names}} {{.Status}}'")

# 4. 检查 pm2 进程（Node.js）
exec_command("pm2 list 2>/dev/null || echo 'no pm2'")
```

确定部署/重启命令后，通过 `exec_command` 执行：
```
exec_command("systemctl restart myapp")
```

如果只发现一个明显匹配的服务，直接使用并记录到 memory。
如果发现多个可能目标或无法确定，向用户提问：

> "远端发现以下服务：[列出服务名]。请告诉我：
> 1. 重启命令（如 `systemctl restart xxx`）
> 2. 服务对应的项目目录（如 `/opt/myapp`）"

用户回复后，**立即将信息记录到 memory**（见「Memory 管理」章节）。

### Step 4 — API 集成测试

> **远端测试的核心价值**：远端服务器拥有完整的运行时依赖（数据库、缓存、消息队列、下游服务），因此远端测试定位为 **API 集成测试**，而非本地单元测试。测试应验证真实的 API 请求/响应、数据库读写、服务间调用，不要 mock 掉这些依赖。

#### 4a — 生成/编写集成测试（本地）

如果项目已有测试框架（pytest / go test / jest / cargo test 等），沿用现有框架在**本地**编写集成测试文件。

**集成测试应关注**：
- HTTP API 端点：发送真实请求，验证响应状态码、body 结构、header
- 数据库操作：写入 → 查询验证 → 清理，使用远端真实数据库
- 服务间调用：验证下游服务的实际调用结果
- 端到端流程：完整的用户操作链路

**不应 mock 的依赖**（远端已有）：
- 数据库连接 → 使用远端真实数据库，通过环境变量获取连接信息
- 缓存（Redis/Memcached）→ 远端直接读写
- 消息队列 → 远端直接生产和消费
- 文件存储 → 远端直接读写文件系统

如果是新功能且没有现成测试：
1. 先通过 `exec_command` 检查远端项目的测试结构：
   ```
   exec_command("ls tests/ 2>/dev/null || ls test/ 2>/dev/null || echo 'no test dir'")
   exec_command("cat pyproject.toml 2>/dev/null | head -50")  # 或 go.mod / package.json 等
   ```
2. 根据项目框架在本地创建对应的集成测试文件
3. 将测试文件加入 Step 2 的同步列表

#### 4b — 同步测试文件

测试文件随 Step 2 一起同步到远端（不需要部署）。

#### 4c — 运行集成测试

**自动发现测试命令**：

如果 memory 中没有测试命令，按以下顺序探测：

```
# 1. Python 项目
exec_command("cat pyproject.toml 2>/dev/null | grep -A5 '\[tool.pytest' || echo ''")
exec_command("cat setup.cfg 2>/dev/null | grep -A5 '\[tool:pytest' || echo ''")

# 2. Go 项目
exec_command("cat go.mod 2>/dev/null && echo 'go-test' || echo ''")

# 3. Node.js 项目
exec_command("cat package.json 2>/dev/null | grep -E 'test|jest|mocha' || echo ''")
```

在确定测试命令后，检查是否需要额外参数：

```
# 检查环境变量引用
exec_command("grep -r 'os.environ\|os.getenv\|process.env' tests/ --include='*.py' --include='*.js' --include='*.ts' -l 2>/dev/null | head -10")

# 检查 pytest fixtures/conftest 中的数据库/API 配置
exec_command("grep -r 'conftest\|fixture' tests/ --include='*.py' -l 2>/dev/null")

# 检查是否有 .env.test 或 .env 文件
exec_command("ls -la .env* 2>/dev/null || echo 'no .env files'")
```

**缺少参数时**：如果测试需要数据库 URL、API key 等参数且无法从远端配置文件中自动获取，向用户提问：

> "运行测试需要以下参数：[参数列表]。请提供这些值。"
> 提供选项：跳过该测试 | 提供参数值 | 设为默认值

用户回复后**立即记录到 memory**。

运行测试：

```
exec_command("cd /opt/app && pytest tests/test_xxx.py -v", timeout=300)
```

观察返回的 `exit_code`、`stdout`、`stderr`：
- `exit_code == 0` → 测试通过，进入 Step 7
- `exit_code != 0` → 测试失败，进入 Step 5

#### 4d — 修改测试/代码

根据测试失败信息，分析根因：
- 测试本身写错了 → 本地修改测试文件，回到 Step 2
- 被测代码有 bug → 本地修改代码文件，回到 Step 2
- 远端环境问题（配置、服务未启动等）→ 进入 Step 5

### Step 5 — 诊断（测试失败时）

#### 5a — 自动发现日志

如果 memory 中没有日志命令，按以下顺序探测：

```
# 1. 检查 systemd journal
exec_command("systemctl list-units --type=service --state=running | grep -E '(app|api|web|server|worker)'")

# 2. 检查 /var/log 下的应用日志
exec_command("ls -lt /var/log/ | head -20")

# 3. 检查项目目录下的日志
exec_command("ls -lt /opt/app/logs/ 2>/dev/null || ls -lt /opt/app/log/ 2>/dev/null || echo 'no logs dir'")

# 4. 检查 docker 日志
exec_command("docker ps --format '{{.Names}}'")
```

找到日志后，获取最近的日志：

```
exec_command("journalctl -u <service-name> -n 200 --no-pager")
# 或
exec_command("tail -n 200 /var/log/<app>/error.log")
# 或
exec_command("docker logs --tail 200 <container-name>")
```

如果无法自动确定日志来源，向用户提问：

> "未找到明确的日志来源。请告诉我：
> 1. 查看日志的命令（如 `journalctl -u myapp` / `tail -f /var/log/myapp.log` / `docker logs myapp`）
> 2. 日志文件的路径（如果有）"

用户回复后**立即记录到 memory**。

#### 5b — 检查服务状态

```
exec_command("systemctl status <service-name>")
# 或
exec_command("supervisorctl status")
# 或
exec_command("docker ps -a --filter name=<container-name>")
```

### Step 6 — 修复

根据 Step 5 的日志和状态输出，分析根因：
- 代码逻辑问题 → 本地修改代码 → 回到 Step 2
- 服务未启动 → `exec_command("systemctl start <service>")` → 回到 Step 4c
- 配置错误 → 本地修改配置文件 → 回到 Step 2（需要部署）
- 依赖缺失 → `exec_command("pip install xxx")` 或等效命令 → 回到 Step 4c

### Step 7 — 收敛

重复 Step 1-6，直到全部测试通过。

**收敛规则**：
- 最多重试 **5 轮**
- 第 3 轮仍未解决 → 停下来，重新分析根因（可能是设计层面问题）
- 第 5 轮仍未解决 → 向用户报告现状，列出已尝试的方案和阻塞点，请求用户介入

---

## 自动发现流程总结

```
需要命令/参数？
    ↓
Memory 有记录？
    ├── 有 → 直接使用
    └── 无 → 自动探测远端
              ├── 确定 → 使用 + 记录到 memory
              └── 不确定 → 向用户提问 → 使用 + 记录到 memory
```

**自动发现覆盖的范围**：
| 需要的信息 | 探测方式 |
|-----------|---------|
| 重启/重载命令 | `systemctl list-units`, `supervisorctl status`, `docker ps`, `pm2 list` |
| 日志查看命令 | `journalctl`, `/var/log/`, 项目 `logs/` 目录, `docker logs` |
| 测试框架和命令 | `pyproject.toml`, `go.mod`, `package.json`, `Makefile` |
| 测试所需参数 | 检查 `conftest.py`, `os.environ`, `process.env`, `.env*` 文件 |
| 远端项目路径 | 从 `remote-executor.yaml` 配置中读取 |

---

## 提问策略

只在以下情况向用户提问：

1. **自动发现无法确定** — 发现多个匹配的目标（如多个 systemd 服务、多个日志来源）
2. **需要密钥/凭证** — 测试需要的 API key、数据库密码等不应在代码中写死的敏感信息
3. **需要业务判断** — 选择部署到哪个服务器、是否需要执行数据迁移等
4. **首次使用** — 项目中无 memory 记录，且自动发现失败

**提问原则**：
- 一次最多提 3 个问题
- 对探测到的结果给出具体选项，让用户选择而非填空
- 提供"跳过"选项

---

## Memory 管理

所有以下信息必须记录到 memory 文件（`opencode/memory/`）：

### 记录内容

| 类别 | 记录项 | 示例 |
|------|--------|------|
| **用户确认的命令** | 重启命令、日志命令、测试命令 | `journalctl -u myapp-v2 -n 200 --no-pager` |
| **远端环境信息** | 服务名、日志路径、端口、依赖服务 | `prod 服务器 systemd 服务名: myapp-v2` |
| **固定参数** | 数据库 URL、环境变量、配置文件路径 | `pytest 需要 --db-url=postgresql://...` |
| **项目约定** | 测试框架、构建系统、项目结构 | `测试框架: pytest + pytest-asyncio` |

### 记录时机

- 用户回答了某个命令或参数 → **立即**记录
- 自动发现并确定使用了某个命令 → **在 Step 执行成功后**记录
- 发现新的远端环境信息 → **立即**记录

### Memory 文件组织

```
opencode/memory/
├── remote-commands.md     ← 重启、日志、测试命令
├── remote-environment.md  ← 服务名、日志路径、端口等
├── remote-params.md       ← 测试参数、环境变量等
└── remote-conventions.md  ← 项目约定、框架选择等
```

### 回查时机

- 每次 Step 0 必须检查
- 用户提到某个已记录的命令/参数时直接使用
- 不要重复探测已经记录的信息

---

## 多服务器流程

```
# 先在 staging 验证
sync(files=["/home/user/projects/myapp/src/api/user.py"], server="staging")
exec_command("pytest tests/test_user.py -v", server="staging")

# 确认通过后上 prod
sync(files=["/home/user/projects/myapp/src/api/user.py"], server="prod")
exec_command("<memory中记录的deploy命令>", server="prod")
exec_command("pytest tests/ -v", server="prod")
```

不同服务器的 memory 记录应**分开存储**（标注 server 名称）。

---

## 常见场景速查

### 场景 1：修改 API 代码 + 同步集成测试
```
1. [本地] 修改 src/api/user.py
2. [本地] 修改/新建 tests/test_user_api.py
3. sync(files=["/home/user/projects/myapp/src/api/user.py", "/home/user/projects/myapp/tests/test_user_api.py"], server="prod")
4. [Memory 查询/自动发现] → deploy_cmd = "systemctl restart myapi"
5. exec_command("systemctl restart myapi", server="prod")
6. exec_command("pytest tests/test_user_api.py -v", server="prod")
7. 失败 → [Memory 查询/自动发现] → log_cmd → exec_command("journalctl -u myapi -n 200 --no-pager")
8. [本地] 修复代码 → 回到 Step 2
```

### 场景 2：新增功能 + 从零写集成测试
```
1. [本地] 修改 src/feature.py
2. [本地] 新建 tests/test_feature.py
3. [探测] exec_command("cat pyproject.toml | head -50") → 确认 pytest
4. [探测] exec_command("grep -r 'DATABASE_URL\|DB_URL' tests/conftest.py") → 发现需要 --db-url
5. [Memory 查询] → db_url 已有记录 → 使用
6. sync(files=["/home/user/projects/myapp/src/feature.py", "/home/user/projects/myapp/tests/test_feature.py"])
7. exec_command("pytest tests/test_feature.py -v --db-url=<memory中的值>")
8. 根据结果迭代
```

### 场景 3：只改静态文件/配置
```
1. [本地] 修改 docs/api.html
2. sync(files=["/home/user/projects/myapp/docs/api.html"])
3. exec_command("head -5 /opt/app/docs/api.html")    ← 验证远端已更新
```

### 场景 4：查询远端状态（不改代码）
```
exec_command("df -h")
exec_command("free -m")
exec_command("docker ps")
exec_command("systemctl status nginx")
```

### 场景 5：首次连接新项目（无 Memory）
```
1. [自动发现] 探测远端服务、日志、测试框架
2. [向用户提问] 确认不确定的信息
3. [记录] 将所有确认信息写入 memory
4. [继续] 进入正常开发流程
```

---

## 错误处理速查

| 错误类型 | 症状 | 处理方式 |
|---------|------|---------|
| SSH 连接失败 | `ConnectionError`, `timeout` | 检查远端服务器状态 → 向用户报告 |
| 文件同步失败 | `files_failed` 非空 | 检查本地文件是否存在 → 检查远端目录权限 |
| 命令被沙箱拦截 | `Command blocked` | 确认命令安全性 → 必要时请求添加白名单 |
| 测试超时 | `timeout` + 无输出 | 增加 timeout 值 → 检查是否有死锁 |
| 部署后服务未启动 | `systemctl status` 显示 failed | exec_command 查看启动日志 → 分析原因 |
| 端口冲突 | stderr 含 "address already in use" | 检查端口占用 → 停掉冲突进程 |

---

## 禁止操作

- **禁止**在远端直接编辑文件（如 `vim`、`sed -i`、`echo > file`）
- **禁止**同步包含密钥/凭证的文件（`.env`、`credentials.*`、`*.pem`）
- **禁止**执行沙箱白名单外的命令
- **禁止**跳过测试验证直接声明完成
- **禁止**在 3 轮失败后继续盲目重试（必须重新分析根因）
