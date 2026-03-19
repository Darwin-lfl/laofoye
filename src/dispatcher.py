from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from memory import LongTermMemoryWorker, append_daily_entry, consolidate
from scheduler.store import TaskStore
from core_types import Agent, InboundMessage, MessageHandler, RunRequest, RunResponse
from utils import ConversationLocks, get_logger

log = get_logger("dispatcher")


class Dispatcher:
    def __init__(
        self,
        agent: Agent,
        scheduler_store: TaskStore | None,
        long_term_memory_worker: LongTermMemoryWorker | None = None,
    ) -> None:
        self._agent = agent
        self._scheduler_store = scheduler_store
        self._long_term_memory_worker = long_term_memory_worker
        self._gateways = []
        self._locks = ConversationLocks()

    def add_gateway(self, gateway) -> None:
        self._gateways.append(gateway)
        log.info("Gateway registered in dispatcher (kind=%s)", getattr(gateway, "kind", "unknown"))

    async def start(self) -> None:
        if not self._gateways:
            raise RuntimeError("No gateways registered")
        gateways = ", ".join(getattr(gw, "kind", "unknown") for gw in self._gateways)
        log.info("Dispatcher starting with gateways: %s", gateways)
        await asyncio.gather(*(gateway.start(self.handle) for gateway in self._gateways))

    async def stop(self) -> None:
        log.info("Dispatcher stopping")
        for gateway in self._gateways:
            await gateway.stop()
        await self._agent.dispose()
        if self._long_term_memory_worker is not None:
            self._long_term_memory_worker.stop()
        log.info("Dispatcher stopped")

    async def handle(self, msg: InboundMessage, reply, stream_handler=None) -> None:
        key = self._conversation_key(msg)
        log.info(
            "Handling inbound message (id=%s, gateway=%s, chat_id=%s, conversation=%s)",
            msg.id,
            msg.gateway_kind,
            msg.chat_id,
            key,
        )
        async with self._locks.hold(key):
            try:
                command = self._parse_command(msg.text)
                if command:
                    log.info("Executing slash command (command=%s, conversation=%s)", command, key)
                    await reply(self._exec_command(command, key, msg.text))
                    return

                now = datetime.now().isoformat()
                context = f"[current_time: {now}, current_chat_id: {msg.chat_id}]\n"
                request = RunRequest(
                    text=context + msg.text,
                    conversation_id=key,
                    chat_id=msg.chat_id,
                    attachments=msg.attachments,
                )
                response_text = ""
                streamed_text_parts: list[str] = []
                tools_used: list[str] = []

                if stream_handler:
                    log.debug("Using streaming response path (conversation=%s)", key)
                    agent_stream = self._agent.stream(request)

                    async def tracked_stream():
                        nonlocal response_text
                        async for event in agent_stream:
                            if event.type == "tool_use" and event.name:
                                tools_used.append(event.name)
                            if event.type == "text_delta" and event.text:
                                streamed_text_parts.append(event.text)
                            if event.type == "done" and event.response:
                                response_text = event.response.text
                            yield event

                    await stream_handler(tracked_stream())
                else:
                    log.debug("Using non-streaming response path (conversation=%s)", key)
                    response = await self._agent.run(request)
                    response_text = response.text
                    await reply(response)

                if not response_text and streamed_text_parts:
                    response_text = "".join(streamed_text_parts).strip()

                if response_text:
                    log.info(
                        "Response completed (conversation=%s, chars=%d, tools=%s)",
                        key,
                        len(response_text),
                        ",".join(tools_used) if tools_used else "none",
                    )
                    workspace_dir = Path(self._agent.get_workspace_dir(key))
                    append_daily_entry(
                        workspace_dir=workspace_dir,
                        user_text=msg.text,
                        response_text=response_text,
                        tools=tools_used if tools_used else None,
                    )
                    if self._long_term_memory_worker is not None:
                        self._long_term_memory_worker.submit(
                            workspace_dir=workspace_dir,
                            user_text=msg.text,
                            response_text=response_text,
                            tools=tools_used if tools_used else None,
                        )
                    log.debug("Conversation persisted to workspace (conversation=%s)", key)
                else:
                    log.warning("No response text generated (conversation=%s)", key)
            except Exception as exc:  # noqa: BLE001
                log.exception("Failed to handle message: %s", exc)
                await reply(RunResponse(text=f"Error: {exc}"))

    def _conversation_key(self, msg: InboundMessage) -> str:
        if msg.thread_root_id:
            return f"{msg.chat_id}_thread_{msg.thread_root_id}"
        return msg.chat_id

    @staticmethod
    def _parse_command(text: str) -> str | None:
        raw = text.strip()
        if not raw.startswith("/"):
            return None
        name = raw[1:].split()[0].lower()
        if name in {"clear", "new", "status", "help", "schedule"}:
            return name
        return None

    def _exec_command(self, name: str, conv_key: str, raw_text: str) -> RunResponse:
        if name in {"clear", "new"}:
            asyncio.create_task(self._agent.clear_conversation(conv_key))
            consolidate(Path(self._agent.get_workspace_dir(conv_key)))
            return RunResponse(text="Context cleared. Memory consolidation started.")

        if name == "status":
            gateways = ", ".join(getattr(gw, "kind", "unknown") for gw in self._gateways) or "none"
            return RunResponse(
                text="\n".join(
                    [
                        "**老佛爷 Status**",
                        f"- Agent: {self._agent.kind}",
                        f"- Gateways: {gateways}",
                    ]
                )
            )

        if name == "help":
            return RunResponse(
                text="\n".join(
                    [
                        "**Commands**",
                        "- `/clear` or `/new` — Start fresh",
                        "- `/schedule list` — List tasks",
                        "- `/schedule remove <id>` — Remove task",
                        "- `/status` — Show system status",
                        "- `/help` — Show help",
                    ]
                )
            )

        if name == "schedule":
            return self._handle_schedule(raw_text)

        return RunResponse(text=f"Unknown command: /{name}")

    def _handle_schedule(self, raw_text: str) -> RunResponse:
        if self._scheduler_store is None:
            return RunResponse(text="Scheduler is disabled.")

        parts = raw_text.strip().split()
        sub = parts[1].lower() if len(parts) > 1 else "list"

        if sub == "list":
            tasks = [task for task in self._scheduler_store.load() if task.status != "completed"]
            if not tasks:
                return RunResponse(text="No scheduled tasks.")
            lines = [
                f"- `{task.id[:8]}` {task.schedule_type} `{task.schedule_value}` -> {task.prompt[:60]}"
                for task in tasks
            ]
            return RunResponse(text="**Scheduled Tasks**\n" + "\n".join(lines))

        if sub in {"remove", "rm", "delete"}:
            if len(parts) < 3:
                return RunResponse(text="Usage: `/schedule remove <id>`")
            task_id = parts[2]
            return RunResponse(text=f"Task `{task_id}` removed." if self._scheduler_store.remove(task_id) else f"Task `{task_id}` not found.")

        return RunResponse(text="Usage: `/schedule list` or `/schedule remove <id>`")


__all__ = ["Dispatcher", "MessageHandler"]
