# 老佛爷 (Laofoye)

中文 | [English](#english)

## 中文

### 1. 项目简介

`老佛爷` 不是“协作提效平台”，而是一套把职场荒诞感工程化的智能体系统。

> 向上汇报拉满，向下共情归零。  
> 结果要立刻，过程不重要。  
> 口号先上线，能力后补票。

人格讽刺底色（内置风格）：

- 向上汇报能力：`MAX`
- 技术理解：`MIN`
- 管理能力：`MIN`
- 压迫感与紧迫感：`MAX`

在实现层面，它依然是一个严肃的 Python agent 项目，核心链路为：

`Gateway -> Dispatcher -> Agent -> Memory/Scheduler`

主要能力：

- CLI 与飞书网关接入
- 流式输出（含飞书流式卡片）
- 会话记忆（每日日志 + 长期记忆提取）
- 定时任务（持久化 + 轮询触发）
- 工具调用（终端、文件、技能等）

---

### 2. 环境要求

- Python `>=3.11`
- `uv`（用于依赖与运行）
- 可选：飞书应用配置（如果使用飞书网关）

安装 `uv`：请参考 Astral 官方文档。

---

### 3. 快速开始

#### 3.1 安装依赖

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --extra dev
```

#### 3.2 配置环境变量

在项目根目录创建或编辑 `.env`：

```bash
OPENAI_API_KEY=your_api_key
# 可选
OPENAI_BASE_URL=https://your-proxy-or-openai-endpoint/v1
```

#### 3.3 初始化配置

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run empress-dowager onboard
```

该命令会生成默认配置文件（`config.json`）和工作区初始化内容。

---

### 4. 启动与停止（脚本）

已提供脚本：

- `scripts/start.sh`
- `scripts/stop.sh`

#### 4.1 启动

```bash
./scripts/start.sh
```

启动脚本特性：

- 防重复启动（检测 PID）
- 自动创建运行目录与日志目录
- 后台运行（`nohup`）
- 自动写入 PID 文件
- 默认设置 `EMPRESS_DOWAGER_LOG_FILE=./logs/laofoye.app.log`

输出文件（默认）：

- PID：`.run/laofoye.pid`
- 标准输出：`logs/laofoye.out.log`
- 应用日志：`logs/laofoye.app.log`

#### 4.2 停止

```bash
./scripts/stop.sh
```

停止脚本特性：

- 优先优雅停止（`SIGTERM`）
- 超时后强制停止（`SIGKILL`）
- 自动清理 PID 文件

---

### 5. 直接命令运行（不使用脚本）

前台运行：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run empress-dowager start
```

初始化向导：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run empress-dowager onboard
```

---

### 6. 配置说明

主要配置在 `config.json`，关键字段示例：

- `agent.model`：模型名
- `agent.system_prompt`：系统提示词
- `feishu.enabled`：是否启用飞书网关
- `feishu.app_id / feishu.app_secret`：飞书凭据
- `workspaces_dir`：工作区目录
- `skills_dir`：技能目录
- `log_level`：日志级别（如 `info/debug`）

常用环境变量覆盖：

- `EMPRESS_DOWAGER_LOG_LEVEL`
- `EMPRESS_DOWAGER_LOG_FILE`
- `EMPRESS_DOWAGER_MODEL`
- `EMPRESS_DOWAGER_WORKSPACES_DIR`
- `EMPRESS_DOWAGER_SKILLS_DIR`

兼容旧变量前缀 `RUNCLAW_*`。

---

### 7. 飞书模式说明

启用飞书时，请确保：

1. `feishu.enabled=true`
2. 配置了 `FEISHU_APP_ID` 与 `FEISHU_APP_SECRET`
3. 飞书应用权限与事件订阅已正确配置

流式卡片结束会通过 CardKit `settings` 接口关闭 `streaming_mode`。

---

### 8. 测试与验证

运行全量测试：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev pytest -q
```

---

### 9. 目录结构

```text
.
├── src/
│   ├── agent.py
│   ├── config.py
│   ├── dispatcher.py
│   ├── main.py
│   ├── gateway/
│   ├── memory/
│   ├── scheduler/
│   └── templates/
├── scripts/
│   ├── start.sh
│   └── stop.sh
├── tests/
├── workspaces/
├── config.json
└── README.md
```

---

### 10. 常见问题

1. 启动报 `Missing OPENAI_API_KEY`  
请检查 `.env` 是否包含 `OPENAI_API_KEY`。

2. `start.sh` 提示 `uv not found`  
请先安装 `uv` 并确认在 `PATH` 中。

3. 停止脚本提示 PID 文件不存在  
说明进程可能已停止，或此前不是通过脚本启动。

---

## English

### 1. Overview

`Laofoye` is not a "team productivity suite" but an engineered satire of corporate dysfunction.

> Upward reporting: maximum.  
> Downward empathy: zero.  
> "Go live today" first, real understanding later.

Built-in satirical persona contrast:

- Upward-management vocabulary: `MAX`
- Technical understanding: `MIN`
- Management capability: `MIN`
- Pressure and urgency tone: `MAX`

At the implementation level, it is still a serious Python agent stack with this core pipeline:

`Gateway -> Dispatcher -> Agent -> Memory/Scheduler`

Key capabilities:

- CLI and Feishu gateway integrations
- Streaming responses (including Feishu streaming cards)
- Conversation memory (daily logs + long-term extraction)
- Scheduled tasks (persistent store + polling executor)
- Tool use (terminal, files, skills, etc.)

---

### 2. Requirements

- Python `>=3.11`
- `uv` (dependency/runtime tool)
- Optional: Feishu app credentials (for Feishu gateway mode)

---

### 3. Quick Start

#### 3.1 Install dependencies

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --extra dev
```

#### 3.2 Configure environment

Create or edit `.env` at project root:

```bash
OPENAI_API_KEY=your_api_key
# optional
OPENAI_BASE_URL=https://your-proxy-or-openai-endpoint/v1
```

#### 3.3 Bootstrap config

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run empress-dowager onboard
```

---

### 4. Start/Stop Scripts

Provided scripts:

- `scripts/start.sh`
- `scripts/stop.sh`

#### 4.1 Start

```bash
./scripts/start.sh
```

What it does:

- Prevents duplicate startup by checking PID
- Creates runtime/log directories automatically
- Runs service in background via `nohup`
- Writes PID file
- Sets default `EMPRESS_DOWAGER_LOG_FILE=./logs/laofoye.app.log`

Default outputs:

- PID file: `.run/laofoye.pid`
- Stdout log: `logs/laofoye.out.log`
- App log: `logs/laofoye.app.log`

#### 4.2 Stop

```bash
./scripts/stop.sh
```

What it does:

- Sends graceful stop (`SIGTERM`) first
- Falls back to force kill (`SIGKILL`) after timeout
- Cleans stale PID file

---

### 5. Run without scripts

Run in foreground:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run empress-dowager start
```

Run onboarding wizard:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run empress-dowager onboard
```

---

### 6. Configuration

Main config file: `config.json`.

Important fields:

- `agent.model`
- `agent.system_prompt`
- `feishu.enabled`
- `feishu.app_id` / `feishu.app_secret`
- `workspaces_dir`
- `skills_dir`
- `log_level`

Common env overrides:

- `EMPRESS_DOWAGER_LOG_LEVEL`
- `EMPRESS_DOWAGER_LOG_FILE`
- `EMPRESS_DOWAGER_MODEL`
- `EMPRESS_DOWAGER_WORKSPACES_DIR`
- `EMPRESS_DOWAGER_SKILLS_DIR`

---

### 7. Feishu Mode

When Feishu mode is enabled, ensure:

1. `feishu.enabled=true`
2. `FEISHU_APP_ID` and `FEISHU_APP_SECRET` are set
3. Feishu app permissions and event subscriptions are configured correctly

At stream completion, the service closes card `streaming_mode` through CardKit `settings` API.

---

### 8. Tests

Run all tests:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev pytest -q
```

---

### 9. Project Layout

```text
.
├── src/
├── scripts/
├── tests/
├── workspaces/
├── config.json
└── README.md
```
