# 项目说明（Project Notes）

本文档面向维护者，描述当前代码中的真实组件边界、运行数据流和存储落盘位置。

## 1. 总览

- 入口：`src/main.py`
- 核心运行对象：
  - `LangGraphAgent`（`src/agent.py`）
  - `Dispatcher`（`src/dispatcher.py`）
  - `Scheduler`（`src/scheduler/engine.py`）
  - `MemoryBackend`（默认 OpenViking 或 Noop）

启动后运行关系：

1. `main._start()` 读取配置并初始化 `TaskStore`、`MemoryBackend`、`LangGraphAgent`、网关。
2. `Dispatcher` 接收网关消息并调用 `agent.run/agent.stream`。
3. `Scheduler` 后台轮询到期任务，复用 `Dispatcher.handle` 执行任务。

## 2. 消息处理链路

### 2.1 实时消息

`Gateway -> Dispatcher.handle -> Agent.run/stream -> reply`

关键行为：

- `Dispatcher` 为同一会话加锁（防止并发交错）
- `runtime_context` 注入当前时间与 chat_id
- 响应成功后将 turn 写入 memory backend（`record_turn`）

### 2.2 定时任务

`Scheduler._loop -> TaskStore.get_due -> Dispatcher.handle`

关键行为：

- 一次性任务执行后删除
- cron 任务执行后更新 `last_run/last_result/next_run`

## 3. Agent Payload 组成

`LangGraphAgent._build_payload()` 每轮构建以下内容：

1. 模块化系统提示（`_build_system_prompt`）
2. OpenViking 检索上下文块（`memory_backend.build_context`）
3. 历史摘要块（Conversation Summary）
4. 裁剪后的 recent history
5. 本轮用户消息（可附 runtime context tag）

额外机制：

- preflight 历史压缩（估算 token 后主动压缩）
- context length 错误自动重试（压缩后再调用）
- runtime context 入 payload、出 history（存储前剥离）

## 4. 系统提示（Prompt）模块化

系统提示改为稳定模块渲染：

- 顶部 `# System Instructions`
- 随后多个 `<module ...>` 块（固定属性与顺序）

当前模块顺序：

1. `core.system`
2. `profile.agents`
3. `profile.soul`
4. `profile.identity`
5. `profile.user`
6. `skills.catalog`

作用：

- 便于快照测试与 diff
- 保持人类可读与程序可机读

## 5. 工具系统

`agent._build_tools()` 默认注册 14 个工具：

- memory：`memory_search`, `memory_save`
- scheduler：`schedule_task`, `list_scheduled_tasks`, `remove_scheduled_task`
- skills：`skill_read`
- execution：`terminal`, `python_repl`
- files：`read_file`, `write_file`, `list_files`, `glob_files`
- web：`web_search`, `web_fetch`

安全边界：

- 文件工具限制在 workspace 根目录（部分支持只读 skills 目录）
- 非白名单工具可通过 `agent.allowed_tools` 禁用

## 6. OpenViking 存储映射

当 `agent.openviking_enabled=true` 时，使用 `OpenVikingMemoryBackend`。

### 6.1 代码读写点

- 检索：`search(...)`, `build_context(...)`
- 写入会话：`record_turn(...)` -> `session.add_message(...)` + `session.commit()`
- 手动记忆：`save_memory(...)` -> `[Memory Snapshot]...`
- 清会话：`clear_conversation(...)` -> `client.rm(viking://session/{id}/, recursive=True)`

### 6.2 典型目录

- `.openviking/_system/queue/`：内部 SQLite 队列
- `.openviking/vectordb/context/`：向量索引与 KV 存储
- `.openviking/viking/default/session/default/<conv>/history/archive_*/messages.jsonl`：归档消息
- `.openviking/viking/default/user/default/memories/`：用户记忆目录

## 7. 配置关键点

配置来源：

1. `config.json`
2. `.env` 与系统环境变量覆盖

支持两套前缀：

- `EMPRESS_DOWAGER_*`（新）
- `RUNCLAW_*`（兼容）

OpenViking 配置文件查找顺序：

1. `OPENVIKING_CONFIG_FILE`
2. `<repo>/ov.conf`
3. `~/.openviking/ov.conf`
4. `/etc/openviking/ov.conf`

## 8. 当前边界

- `Dispatcher._conversation_key` 当前固定返回 `"local"`
- `memory/daily.py` 与 `memory/long_term.py` 尚未接入主运行链路
- Feishu 网关依赖 `lark-oapi`，未配置时建议使用 CLI

## 9. 变更建议（文档维护）

当以下代码变更时，请同步更新 `README.md` 与本文档：

- `agent._build_tools()`（工具集合变化）
- `config.AgentConfig`（配置项变化）
- `memory/openviking_backend.py`（检索/存储路径变化）
- `dispatcher._parse_command()`（命令变化）
- `scheduler/engine.py`（执行策略变化）
