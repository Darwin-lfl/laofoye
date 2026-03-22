from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class MemoryHit:
    uri: str
    abstract: str
    context_type: str = "memory"
    score: float | None = None


class MemoryBackend(Protocol):
    def build_context(self, *, conversation_id: str, query: str, limit: int | None = None) -> str: ...

    def search(self, *, conversation_id: str, query: str, limit: int = 5) -> list[MemoryHit]: ...

    def record_turn(
        self,
        *,
        conversation_id: str,
        user_text: str,
        response_text: str,
        tools: list[str] | None = None,
    ) -> None: ...

    def save_memory(self, *, conversation_id: str, content: str) -> None: ...

    def clear_conversation(self, conversation_id: str) -> None: ...

    def close(self) -> None: ...


class NoopMemoryBackend:
    def build_context(self, *, conversation_id: str, query: str, limit: int | None = None) -> str:
        del conversation_id, query, limit
        return ""

    def search(self, *, conversation_id: str, query: str, limit: int = 5) -> list[MemoryHit]:
        del conversation_id, query, limit
        return []

    def record_turn(
        self,
        *,
        conversation_id: str,
        user_text: str,
        response_text: str,
        tools: list[str] | None = None,
    ) -> None:
        del conversation_id, user_text, response_text, tools

    def save_memory(self, *, conversation_id: str, content: str) -> None:
        del conversation_id, content

    def clear_conversation(self, conversation_id: str) -> None:
        del conversation_id

    def close(self) -> None:
        return None


def render_context_block(hits: list[MemoryHit]) -> str:
    if not hits:
        return ""

    lines = ["## Retrieved Context (OpenViking)"]
    for idx, hit in enumerate(hits, start=1):
        score = f"{hit.score:.2f}" if isinstance(hit.score, (float, int)) else "n/a"
        ctype = (hit.context_type or "context").strip().lower()
        uri = hit.uri.strip() or "(unknown-uri)"
        lines.append(f"{idx}. [{ctype}] {uri} (score={score})")
        summary = hit.abstract.strip()
        if summary:
            lines.append(summary)
    return "\n".join(lines)


__all__ = [
    "MemoryBackend",
    "MemoryHit",
    "NoopMemoryBackend",
    "render_context_block",
]
