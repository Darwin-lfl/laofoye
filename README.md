# 老佛爷 (Laofoye)

中文 | [English](#english)

## 中文

### 1. 项目定位

`老佛爷` 是一个可本地运行的 Python 智能体服务，支持 CLI 与飞书双网关，内置工具调用、会话调度、OpenViking 记忆检索与持久化。

当前主链路：

`Gateway -> Dispatcher -> LangGraphAgent -> (Tools / OpenViking / Scheduler)`

> 说明：项目保留了“角色化风格”设定，但在工程实现上是标准的可测试 Agent Runtime。

---

### 2. 当前技术栈（代码实际在用）

- Python `>=3.11`
- `langchain` / `langgraph` / `langchain-openai`
- `pydantic`（配置建模）
- `croniter`（cron 调度计算）
- `lark-oapi`（飞书网关）
- `openviking`（memory/context 检索与会话存储）
- `langfuse`（可选链路追踪）
- `uv`（依赖与运行）

依赖定义见 `pyproject.toml`。

---

### 3. 核心组件

#### 3.1 Gateway

- CLI：终端交互，支持流式输出、工具调用回显
- Feishu：长连接事件接入 + 卡片流式更新

#### 3.2 Dispatcher

- 负责网关消息编排、命令分发、串行会话锁
- 每轮完成后将 user/assistant turn 写入 memory backend
- 支持命令：`/clear` `/new` `/status` `/help` `/schedule`

#### 3.3 LangGraphAgent

- 通过 `create_agent(...)` 运行模型与工具
- 每轮请求前构建 payload：
  - 模块化系统提示（`<module ...>`）
  - OpenViking 检索上下文
  - 历史摘要（超窗后压缩）
  - runtime metadata（如 current_time/current_chat_id）
- 历史在内存中按阈值压缩，避免 context length 溢出

#### 3.4 Memory（OpenViking）

- 启用后，查询时注入检索命中，回答后持久化 turn
- 检索失败时有 archive `messages.jsonl` 本地回退检索
- `memory_save` 工具会写入 `[Memory Snapshot]` 消息

> 说明：`src/memory/daily.py` 与 `src/memory/long_term.py` 提供了“每日记忆/长期记忆提取”能力，但当前 `main -> dispatcher` 主链路默认未自动接入这两套逻辑。

#### 3.5 Scheduler

- 存储：`schedules.json`（`workspaces_dir` 的上级目录）
- 轮询执行到期任务，并通过网关回传结果
- 支持 `once` 与 `cron`

---

### 4. 内置工具（Agent 可调用）

默认可用工具：

- `memory_search`
- `memory_save`
- `schedule_task`
- `list_scheduled_tasks`
- `remove_scheduled_task`
- `skill_read`
- `terminal`
- `python_repl`
- `read_file`
- `write_file`
- `list_files`
- `glob_files`
- `web_search`
- `web_fetch`

可通过 `agent.allowed_tools` 白名单限制。

---

### 5. 快速开始

#### 5.1 安装依赖

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --extra dev
```

#### 5.2 配置环境变量

在项目根目录创建 `.env`：

```bash
OPENAI_API_KEY=your_api_key
# 可选
OPENAI_BASE_URL=https://your-proxy-or-openai-endpoint/v1
```

#### 5.3 初始化配置

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run empress-dowager onboard
```

#### 5.4 启动 / 停止

```bash
./scripts/start.sh
./scripts/stop.sh
```

前台运行：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run empress-dowager start
```

---

### 6. 配置说明（`config.json`）

常用字段：

- `agent.model`
- `agent.system_prompt`
- `agent.allowed_tools`
- `agent.history_keep_messages`
- `agent.history_compact_threshold`
- `agent.history_summary_max_chars`
- `agent.context_window_tokens`
- `agent.web_search_provider` (`duckduckgo/brave/tavily/searxng/jina`)
- `agent.web_search_api_key`
- `agent.web_search_base_url`（主要用于 searxng）
- `agent.web_fetch_jina_api_key`
- `agent.langfuse_enabled/langfuse_public_key/langfuse_secret_key/langfuse_host`
- `agent.openviking_enabled`
- `agent.openviking_path`
- `agent.openviking_search_limit`
- `agent.openviking_commit_every_turn`
- `agent.openviking_payload_history_keep_messages`
- `agent.openviking_payload_token_budget`
- `feishu.enabled`、`feishu.app_id`、`feishu.app_secret`
- `workspaces_dir`
- `skills_dir`
- `log_level`、`log_file`

环境变量覆盖前缀：

- 新前缀：`EMPRESS_DOWAGER_*`
- 兼容旧前缀：`RUNCLAW_*`

---

### 7. OpenViking 接入说明

启用最小配置：

```json
{
  "agent": {
    "openviking_enabled": true,
    "openviking_path": "./.openviking",
    "openviking_search_limit": 5,
    "openviking_commit_every_turn": true
  }
}
```

另外必须提供 OpenViking 运行配置文件（例如 `ov.conf`），用于 embedding/vlm 配置。

`OPENVIKING_CONFIG_FILE` 解析顺序：

1. 环境变量显式指定路径
2. 项目根目录 `ov.conf`
3. `~/.openviking/ov.conf`
4. `/etc/openviking/ov.conf`

`.openviking` 目录中常见数据：

- `_system/queue/*.db`：内部队列元数据
- `vectordb/context/*`：向量集合与索引
- `viking/default/session/.../history/archive_*/messages.jsonl`：会话归档消息
- `viking/default/user/default/memories/*`：用户记忆目录

---

### 8. 飞书模式

启用飞书网关时，请确保：

1. `feishu.enabled=true`
2. `feishu.app_id` / `feishu.app_secret` 已配置
3. 飞书应用权限与事件订阅正确

飞书模式支持：

- 文本流式回复
- 工具事件透传到卡片文本流
- 结束时关闭卡片 `streaming_mode`

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
├── tests/
├── skills/
├── workspaces/
├── .openviking/               # 启用 OpenViking 后生成
├── config.json
└── README.md
```

补充文档：`PROJECT.md`（维护者视角的架构与数据流说明）。

---

### 10. 测试

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev pytest -q
```

---

### 11. 当前边界与已知行为

- 会话键当前固定为 `local`（`Dispatcher._conversation_key`）
- OpenViking 开启时会额外压缩 payload 历史窗口（减少 token 压力）
- Prompt 已模块化输出（`<module id=...>`），便于调试和快照测试

---

## English

### 1. What this project is

`Laofoye` is a Python agent runtime with:

- CLI + Feishu gateways
- tool calling
- OpenViking-backed memory/context retrieval
- scheduler execution loop
- optional Langfuse tracing

Main pipeline:

`Gateway -> Dispatcher -> LangGraphAgent -> (Tools / OpenViking / Scheduler)`

### 2. Quick start

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --extra dev
UV_CACHE_DIR=/tmp/uv-cache uv run empress-dowager onboard
./scripts/start.sh
```

### 3. Key docs

- `README.md`: user-facing setup and operation
- `PROJECT.md`: architecture, data flow, storage mapping

### 4. Test

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev pytest -q
```
