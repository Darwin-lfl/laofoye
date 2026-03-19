# Empress Dowager Design

## Goal

实现一个仿照 RunClaw 架构的 Python 版智能体系统，使用 uv + LangChain/LangGraph 1.x。

## Architecture

- Gateway 层：负责消息接入与发送（当前实现 CLI Gateway）
- Dispatcher 层：命令路由、串行化会话处理、消息上下文注入
- Agent 层：LangGraph ReAct agent，挂载 memory/scheduler tools
- Memory 层：每日对话日志 + 长期记忆文件
- Scheduler 层：JSON 持久化 + 轮询触发任务

## Data Flow

1. Gateway 收到输入消息
2. Dispatcher 根据会话 key 加锁串行处理
3. 普通消息送入 LangGraphAgent，slash 命令本地执行
4. 响应返回 Gateway，Q&A 记录进入 daily memory
5. Scheduler 定时创建合成消息交给 Dispatcher 复用同一路径

## Error Handling

- Dispatcher 对消息处理异常统一兜底并回复错误
- Scheduler 对任务执行失败记录 `last_result`
- TaskStore 使用临时文件替换保证写入原子性

## Testing Strategy

- 配置合并优先级
- 调度任务存取与 due 过滤
- 记忆写入与 summary 读取
- Dispatcher 命令和普通消息路径
