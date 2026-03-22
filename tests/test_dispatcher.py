from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from dispatcher import Dispatcher
from core_types import AgentStreamEvent, InboundMessage, RunRequest, RunResponse


@dataclass
class FakeAgent:
    kind: str = "fake"
    model: str = "fake-model"

    async def run(self, request: RunRequest) -> RunResponse:
        return RunResponse(text=f"echo: {request.text}")

    async def stream(self, request: RunRequest):
        yield AgentStreamEvent(type="tool_use", name="terminal", tool_input={"command": "pwd"})
        yield AgentStreamEvent(type="text_delta", text="echo: ")
        yield AgentStreamEvent(type="text_delta", text=request.text)
        yield AgentStreamEvent(type="done", response=RunResponse(text=f"echo: {request.text}"))

    def get_workspace_dir(self, conversation_id: str) -> str:
        return "/tmp"

    async def clear_conversation(self, conversation_id: str) -> None:
        return None

    async def dispose(self) -> None:
        return None


@dataclass
class DeltaOnlyAgent:
    workspace_dir: Path
    kind: str = "fake"
    model: str = "fake-model"

    async def run(self, request: RunRequest) -> RunResponse:
        return RunResponse(text=f"echo: {request.text}")

    async def stream(self, request: RunRequest):
        yield AgentStreamEvent(type="text_delta", text="delta-only")
        yield AgentStreamEvent(type="done", response=RunResponse(text=""))

    def get_workspace_dir(self, conversation_id: str) -> str:
        return str(self.workspace_dir / conversation_id)

    async def clear_conversation(self, conversation_id: str) -> None:
        return None

    async def dispose(self) -> None:
        return None


@dataclass
class FakeMemoryBackend:
    calls: list[dict] | None = None

    def __post_init__(self):
        if self.calls is None:
            self.calls = []

    def record_turn(
        self,
        *,
        conversation_id: str,
        user_text: str,
        response_text: str,
        tools: list[str] | None = None,
    ):
        self.calls.append(
            {
                "conversation_id": conversation_id,
                "user_text": user_text,
                "response_text": response_text,
                "tools": tools or [],
            }
        )

    def clear_conversation(self, conversation_id: str) -> None:
        del conversation_id

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_dispatcher_status_command():
    dispatcher = Dispatcher(FakeAgent(), scheduler_store=None)
    msg = InboundMessage(
        id="1",
        text="/status",
        chat_id="chat-1",
        gateway_kind="cli",
    )

    captured = {}

    async def reply(resp: RunResponse):
        captured["text"] = resp.text

    await dispatcher.handle(msg, reply)

    assert "老佛爷 Status" in captured["text"]
    assert "fake" in captured["text"]


@pytest.mark.asyncio
async def test_dispatcher_normal_message():
    dispatcher = Dispatcher(FakeAgent(), scheduler_store=None)
    msg = InboundMessage(
        id="2",
        text="hello",
        chat_id="chat-1",
        gateway_kind="cli",
    )

    captured = {}

    async def reply(resp: RunResponse):
        captured["text"] = resp.text

    await dispatcher.handle(msg, reply)

    assert captured["text"].startswith("echo:")


@pytest.mark.asyncio
async def test_dispatcher_stream_message():
    dispatcher = Dispatcher(FakeAgent(), scheduler_store=None)
    msg = InboundMessage(
        id="3",
        text="hello stream",
        chat_id="chat-1",
        gateway_kind="cli",
    )

    events = []

    async def reply(resp: RunResponse):
        raise AssertionError("reply should not be used in stream mode")

    async def stream_handler(stream):
        async for event in stream:
            events.append(event)

    await dispatcher.handle(msg, reply, stream_handler)

    assert any(event.type == "tool_use" for event in events)
    assert any(event.type == "done" for event in events)


@pytest.mark.asyncio
async def test_dispatcher_stream_records_memory_from_text_delta(tmp_path):
    agent = DeltaOnlyAgent(workspace_dir=tmp_path / "workspaces")
    backend = FakeMemoryBackend()
    dispatcher = Dispatcher(agent, scheduler_store=None, memory_backend=backend)
    msg = InboundMessage(
        id="4",
        text="remember me",
        chat_id="chat-2",
        gateway_kind="cli",
    )

    async def reply(resp: RunResponse):
        raise AssertionError("reply should not be used in stream mode")

    async def stream_handler(stream):
        async for _event in stream:
            pass

    await dispatcher.handle(msg, reply, stream_handler)

    assert backend.calls
    assert backend.calls[0]["conversation_id"] == "local"
    assert backend.calls[0]["user_text"] == "remember me"
    assert backend.calls[0]["response_text"] == "delta-only"
