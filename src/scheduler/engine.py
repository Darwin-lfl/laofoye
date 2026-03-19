from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime

from scheduler.store import TaskStore, compute_next_run
from core_types import Agent, Gateway, InboundMessage, RunResponse
from utils import get_logger

log = get_logger("scheduler")


class Scheduler:
    def __init__(
        self,
        *,
        agent: Agent,
        gateways: list[Gateway],
        dispatcher: "DispatcherProtocol",
        store: TaskStore,
        poll_interval_seconds: int = 30,
    ) -> None:
        self._agent = agent
        self._gateways = gateways
        self._dispatcher = dispatcher
        self._store = store
        self._poll_interval_seconds = poll_interval_seconds
        self._runner: asyncio.Task[None] | None = None
        self._running = False

    def start(self) -> None:
        if self._runner is not None:
            return
        self._running = True
        self._runner = asyncio.create_task(self._loop())
        log.info("Scheduler loop started (poll_interval=%ss)", self._poll_interval_seconds)

    async def stop(self) -> None:
        self._running = False
        if self._runner:
            self._runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._runner
        self._runner = None
        log.info("Scheduler loop stopped")

    async def _loop(self) -> None:
        while self._running:
            await self._poll_once()
            await asyncio.sleep(self._poll_interval_seconds)

    async def _poll_once(self) -> None:
        due = self._store.get_due(datetime.now(UTC))
        if due:
            log.info("Scheduler found %d due task(s)", len(due))
        for task in due:
            await self._execute(task.id, task.chat_id, task.prompt, task.schedule_type, task.schedule_value)

    async def _execute(
        self,
        task_id: str,
        chat_id: str,
        prompt: str,
        schedule_type: str,
        schedule_value: str,
    ) -> None:
        log.info(
            "Executing scheduled task (id=%s, chat_id=%s, type=%s, value=%s)",
            task_id,
            chat_id,
            schedule_type,
            schedule_value,
        )
        message = InboundMessage(
            id=f"sched-{task_id}",
            text=prompt,
            chat_id=chat_id,
            gateway_kind="scheduler",
        )

        last_response: str = ""

        async def reply_fn(response: RunResponse) -> None:
            nonlocal last_response
            last_response = response.text
            for gateway in self._gateways:
                await gateway.send(chat_id, response)

        try:
            await self._dispatcher.handle(message, reply_fn)
            now = datetime.now(UTC)
            if schedule_type == "once":
                self._store.remove(task_id)
            else:
                self._store.update(
                    task_id,
                    last_run=now,
                    last_result=last_response[:200],
                    next_run=compute_next_run(schedule_type, schedule_value, now),
                )
            log.info("Scheduled task completed (id=%s, response_chars=%d)", task_id, len(last_response))
        except Exception as exc:  # noqa: BLE001
            log.error("Task execution failed for %s: %s", task_id, exc)
            self._store.update(task_id, last_run=datetime.now(UTC), last_result=f"Error: {exc}")


class DispatcherProtocol:
    async def handle(self, message: InboundMessage, reply_fn, stream_handler=None) -> None: ...
