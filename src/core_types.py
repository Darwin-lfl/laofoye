from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Awaitable, Callable, Literal, Protocol


@dataclass(slots=True)
class Attachment:
    data: bytes
    media_type: str
    file_name: str | None = None


@dataclass(slots=True)
class RunRequest:
    text: str
    conversation_id: str
    chat_id: str
    attachments: list[Attachment] = field(default_factory=list)


@dataclass(slots=True)
class RunResponse:
    text: str
    thinking: str | None = None
    session_id: str | None = None
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    elapsed_ms: int | None = None
    model: str | None = None


@dataclass(slots=True)
class AgentStreamEvent:
    type: Literal["thinking_delta", "text_delta", "tool_use", "tool_result", "done"]
    text: str | None = None
    name: str | None = None
    tool_input: dict[str, Any] | None = None
    response: RunResponse | None = None


@dataclass(slots=True)
class InboundMessage:
    id: str
    text: str
    chat_id: str
    gateway_kind: str
    thread_root_id: str | None = None
    author_id: str | None = None
    author_name: str | None = None
    attachments: list[Attachment] = field(default_factory=list)


ReplyFn = Callable[[RunResponse], Awaitable[None]]
StreamHandler = Callable[[AsyncGenerator[AgentStreamEvent, None]], Awaitable[None]]
MessageHandler = Callable[[InboundMessage, ReplyFn, StreamHandler | None], Awaitable[None]]


class Agent(Protocol):
    kind: str
    model: str

    async def run(self, request: RunRequest) -> RunResponse: ...

    async def stream(self, request: RunRequest) -> AsyncGenerator[AgentStreamEvent, None]: ...

    def get_workspace_dir(self, conversation_id: str) -> str: ...

    async def clear_conversation(self, conversation_id: str) -> None: ...

    async def dispose(self) -> None: ...


class Gateway(Protocol):
    kind: str

    async def start(self, handler: MessageHandler) -> None: ...

    async def stop(self) -> None: ...

    async def send(self, chat_id: str, response: RunResponse) -> None: ...
