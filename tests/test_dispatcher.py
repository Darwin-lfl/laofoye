from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from dispatcher import Dispatcher
from core_types import AgentStreamEvent, InboundMessage, RunRequest, RunResponse
from memory import MemoryExtraction, MemoryItem, apply_long_term_memory


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
class FakeMemoryWorker:
    calls: list[dict] | None = None

    def __post_init__(self):
        if self.calls is None:
            self.calls = []

    def submit(self, *, workspace_dir: Path, user_text: str, response_text: str, tools=None):
        self.calls.append(
            {
                "workspace_dir": workspace_dir,
                "user_text": user_text,
                "response_text": response_text,
                "tools": tools or [],
            }
        )
        # Simulate async worker side effect deterministically for unit test.
        apply_long_term_memory(
            workspace_dir,
            MemoryExtraction(
                semantic=[MemoryItem(content="semantic-from-worker")],
                procedural=[MemoryItem(content="procedural-from-worker")],
                episodic=[MemoryItem(content=f"Q: {user_text} | A: {response_text}")],
            ),
        )
        return True

    def stop(self):
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
    worker = FakeMemoryWorker()
    dispatcher = Dispatcher(agent, scheduler_store=None, long_term_memory_worker=worker)
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

    files = list((tmp_path / "workspaces" / "local" / "memory").glob("*.md"))
    assert files, "daily memory file should be created"
    content = files[0].read_text(encoding="utf-8")
    assert "**Q:** remember me" in content
    assert "**A:** delta-only" in content

    assert worker.calls
    assert worker.calls[0]["workspace_dir"] == tmp_path / "workspaces" / "local"
    long_mem = (tmp_path / "workspaces" / "local" / "MEMORY.md").read_text(encoding="utf-8")
    assert "## Episodic Memory" in long_mem
    assert "Q: remember me" in long_mem
