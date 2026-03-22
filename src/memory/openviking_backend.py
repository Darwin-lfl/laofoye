from __future__ import annotations

import importlib
import inspect
import json
import os
from pathlib import Path
from typing import Any

from config import AgentConfig, project_root
from memory.backend import MemoryHit, NoopMemoryBackend, render_context_block
from utils import get_logger

log = get_logger("memory.openviking")


class OpenVikingMemoryBackend:
    def __init__(
        self,
        *,
        path: Path,
        search_limit: int = 5,
        commit_every_turn: bool = True,
    ) -> None:
        self._path = path.expanduser().resolve()
        self._path.mkdir(parents=True, exist_ok=True)
        self._search_limit = max(1, int(search_limit))
        self._commit_every_turn = bool(commit_every_turn)
        self._pending_contexts: dict[str, list[str]] = {}
        self._client = self._build_client(self._path)

    @staticmethod
    def _build_client(path: Path):
        try:
            ov = importlib.import_module("openviking")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "OpenViking is enabled but Python package `openviking` is not installed. "
                "Run: pip install openviking"
            ) from exc

        client = ov.OpenViking(path=str(path))
        client.initialize()
        return client

    @staticmethod
    def _make_text_part(text: str) -> Any:
        try:
            module = importlib.import_module("openviking.message")
            text_part_cls = getattr(module, "TextPart")
            return text_part_cls(text=text)
        except Exception:  # noqa: BLE001
            # Fallback for SDK variants that accept plain dict parts.
            return {"type": "text", "text": text}

    def _session(self, conversation_id: str):
        session = self._client.session(session_id=conversation_id)
        self._ensure_session_loaded(session, conversation_id=conversation_id)
        return session

    def _ensure_session_loaded(self, session: Any, *, conversation_id: str) -> None:
        loader = getattr(session, "load", None)
        if not callable(loader):
            return

        try:
            maybe_coro = loader()
            if inspect.isawaitable(maybe_coro):
                try:
                    from openviking_cli.utils import run_async as ov_run_async

                    ov_run_async(maybe_coro)
                except Exception:  # noqa: BLE001
                    close_coro = getattr(maybe_coro, "close", None)
                    if callable(close_coro):
                        close_coro()
                    log.debug(
                        "OpenViking session.load() awaitable could not be executed "
                        "(conversation=%s)",
                        conversation_id,
                        exc_info=True,
                    )
        except Exception:  # noqa: BLE001
            log.warning(
                "OpenViking session.load() failed (conversation=%s)",
                conversation_id,
                exc_info=True,
            )

    def build_context(self, *, conversation_id: str, query: str, limit: int | None = None) -> str:
        hits = self.search(
            conversation_id=conversation_id,
            query=query,
            limit=limit if limit is not None else self._search_limit,
        )
        self._pending_contexts[conversation_id] = [
            hit.uri for hit in hits if hit.uri and hit.context_type != "session_context"
        ]
        return render_context_block(hits)

    def search(self, *, conversation_id: str, query: str, limit: int = 5) -> list[MemoryHit]:
        q = (query or "").strip()
        if not q:
            return []
        n = max(1, int(limit))
        session = self._session(conversation_id)
        session_uri = f"viking://session/default/{conversation_id}"
        result: Any
        try:
            try:
                result = self._client.search(q, session=session, limit=n)
            except TypeError:
                result = self._client.search(q, session=session)
        except Exception:  # noqa: BLE001
            log.warning(
                "OpenViking search() failed, falling back to find() (conversation=%s)",
                conversation_id,
                exc_info=True,
            )
            result = self._fallback_find(
                q=q,
                n=n,
                conversation_id=conversation_id,
                target_uri=session_uri,
            )
            if result is None:
                return []

        hits = self._collect_hits(result)
        if not hits:
            fallback = self._fallback_find(
                q=q,
                n=n,
                conversation_id=conversation_id,
                target_uri=session_uri,
            )
            if fallback is not None:
                hits = self._collect_hits(fallback)
        if not hits:
            fallback = self._fallback_find(
                q=q,
                n=n,
                conversation_id=conversation_id,
            )
            if fallback is not None:
                hits = self._collect_hits(fallback)
        if not hits:
            hits = self._fallback_archive_hits(
                conversation_id=conversation_id,
                query=q,
                limit=n,
            )
        if not hits:
            session_context = _extract_session_context(result)
            if session_context:
                hits = [
                    MemoryHit(
                        uri=session_uri,
                        abstract=session_context,
                        context_type="session_context",
                        score=None,
                    )
                ]
        return hits[:n]

    def record_turn(
        self,
        *,
        conversation_id: str,
        user_text: str,
        response_text: str,
        tools: list[str] | None = None,
    ) -> None:
        session = self._session(conversation_id)
        user = (user_text or "").strip()
        assistant = (response_text or "").strip()
        if not user and not assistant:
            return

        if user:
            session.add_message("user", [self._make_text_part(user)])
        if assistant:
            tool_suffix = f"\n\n[tools] {', '.join(tools)}" if tools else ""
            session.add_message("assistant", [self._make_text_part(assistant + tool_suffix)])

        used_contexts = self._pending_contexts.pop(conversation_id, [])
        if used_contexts:
            try:
                session.used(contexts=used_contexts)
            except Exception:  # noqa: BLE001
                log.debug("Session.used() failed (conversation=%s)", conversation_id, exc_info=True)

        if self._commit_every_turn:
            session.commit()

    def save_memory(self, *, conversation_id: str, content: str) -> None:
        payload = (content or "").strip()
        if not payload:
            return
        session = self._session(conversation_id)
        session.add_message(
            "assistant",
            [self._make_text_part(f"[Memory Snapshot]\n{payload}")],
        )
        if self._commit_every_turn:
            session.commit()

    def clear_conversation(self, conversation_id: str) -> None:
        self._pending_contexts.pop(conversation_id, None)
        uri = f"viking://session/{conversation_id}/"
        try:
            self._client.rm(uri, recursive=True)
        except Exception:  # noqa: BLE001
            log.debug("Failed to delete OpenViking session %s", conversation_id, exc_info=True)

    def close(self) -> None:
        self._pending_contexts.clear()
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            log.debug("Failed to close OpenViking client", exc_info=True)

    @staticmethod
    def _collect_hits(result: Any) -> list[MemoryHit]:
        hits: list[MemoryHit] = []
        for bucket_name in ("memories", "resources", "skills"):
            for item in _bucket_items(result, bucket_name):
                hit = _to_memory_hit(item, default_type=bucket_name[:-1])
                if hit is not None:
                    hits.append(hit)
        return hits

    def _fallback_find(
        self,
        *,
        q: str,
        n: int,
        conversation_id: str,
        target_uri: str = "",
    ) -> Any | None:
        try:
            if target_uri:
                try:
                    return self._client.find(q, target_uri=target_uri, limit=n)
                except TypeError:
                    return self._client.find(q, limit=n)
            return self._client.find(q, limit=n)
        except Exception:  # noqa: BLE001
            log.warning(
                "OpenViking find() fallback failed (conversation=%s, target_uri=%s)",
                conversation_id,
                target_uri or "(global)",
                exc_info=True,
            )
            return None

    def _fallback_archive_hits(
        self,
        *,
        conversation_id: str,
        query: str,
        limit: int,
    ) -> list[MemoryHit]:
        session_dir = (
            self._path
            / "viking"
            / "default"
            / "session"
            / "default"
            / conversation_id
            / "history"
        )
        if not session_dir.exists():
            return []

        archives = sorted(
            [p for p in session_dir.iterdir() if p.is_dir() and p.name.startswith("archive_")],
            key=lambda p: p.name,
            reverse=True,
        )
        normalized_query = _normalize_for_match(query)
        if not normalized_query:
            return []

        candidates: list[tuple[float, MemoryHit]] = []
        for archive in archives:
            msg_file = archive / "messages.jsonl"
            if not msg_file.exists():
                continue
            try:
                rows = [
                    json.loads(line)
                    for line in msg_file.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            except Exception:  # noqa: BLE001
                continue

            combined_lines: list[str] = []
            for row in rows:
                role = str(row.get("role", "")).strip().lower()
                for part in row.get("parts", []) if isinstance(row.get("parts"), list) else []:
                    if not isinstance(part, dict):
                        continue
                    text = str(part.get("text", "")).strip()
                    if not text:
                        continue
                    prefix = "User" if role == "user" else "Assistant"
                    combined_lines.append(f"{prefix}: {text}")
            if not combined_lines:
                continue

            combined = "\n".join(combined_lines)
            score = _query_similarity(normalized_query, _normalize_for_match(combined))
            if score <= 0:
                continue
            snippet = combined[:500]
            candidates.append(
                (
                    score,
                    MemoryHit(
                        uri=f"viking://session/default/{conversation_id}/history/{archive.name}/messages.jsonl",
                        abstract=snippet,
                        context_type="archive",
                        score=score,
                    ),
                )
            )

        candidates.sort(key=lambda item: item[0], reverse=True)
        return [hit for _, hit in candidates[:limit]]


def _bucket_items(container: Any, key: str) -> list[Any]:
    if isinstance(container, dict):
        value = container.get(key, [])
    else:
        value = getattr(container, key, [])
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return list(value)
    except TypeError:
        return []


def _to_memory_hit(item: Any, *, default_type: str) -> MemoryHit | None:
    if isinstance(item, dict):
        uri = str(item.get("uri", "")).strip()
        abstract = str(item.get("abstract", "")).strip()
        context_type = str(item.get("context_type", default_type) or default_type)
        score_raw = item.get("score")
    else:
        uri = str(getattr(item, "uri", "")).strip()
        abstract = str(getattr(item, "abstract", "")).strip()
        context_type = str(getattr(item, "context_type", default_type) or default_type)
        score_raw = getattr(item, "score", None)

    if not uri and not abstract:
        return None
    score: float | None
    if isinstance(score_raw, (float, int)):
        score = float(score_raw)
    else:
        score = None
    return MemoryHit(
        uri=uri or "(unknown-uri)",
        abstract=abstract,
        context_type=context_type,
        score=score,
    )


def _extract_session_context(result: Any) -> str:
    if isinstance(result, dict):
        query_plan = result.get("query_plan")
    else:
        query_plan = getattr(result, "query_plan", None)
    if query_plan is None:
        return ""

    if isinstance(query_plan, dict):
        session_context = query_plan.get("session_context")
    else:
        session_context = getattr(query_plan, "session_context", "")
    text = str(session_context or "").strip()
    if not text:
        return ""
    return text[:2000]


def _normalize_for_match(text: str) -> str:
    lowered = (text or "").lower().strip()
    if not lowered:
        return ""
    # Keep Chinese chars, latin letters and digits for tolerant matching.
    return "".join(ch for ch in lowered if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _query_similarity(query: str, content: str) -> float:
    if not query or not content:
        return 0.0
    if query in content:
        return 1.0
    q_chars = set(query)
    c_chars = set(content)
    if not q_chars or not c_chars:
        return 0.0
    overlap = len(q_chars & c_chars)
    if overlap == 0:
        return 0.0
    return overlap / max(1, len(q_chars))


def build_memory_backend(*, config: AgentConfig, workspaces_dir: Path):
    if not bool(getattr(config, "openviking_enabled", False)):
        return NoopMemoryBackend()

    _ensure_openviking_config_file()

    configured_path = Path(str(getattr(config, "openviking_path", "")).strip() or ".openviking")
    if configured_path.is_absolute():
        backend_path = configured_path
    else:
        backend_path = (workspaces_dir.parent / configured_path).resolve()

    return OpenVikingMemoryBackend(
        path=backend_path,
        search_limit=int(getattr(config, "openviking_search_limit", 5)),
        commit_every_turn=bool(getattr(config, "openviking_commit_every_turn", True)),
    )


def _ensure_openviking_config_file() -> Path:
    raw = str(os.getenv("OPENVIKING_CONFIG_FILE", "")).strip()
    root = project_root()

    if raw:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if not candidate.exists():
            raise RuntimeError(
                "OPENVIKING_CONFIG_FILE points to a missing file: "
                f"{candidate}. Please create it (you can use `{root / 'ov.conf'}` as template)."
            )
        os.environ["OPENVIKING_CONFIG_FILE"] = str(candidate)
        return candidate

    candidates = [
        (root / "ov.conf").resolve(),
        Path.home().resolve() / ".openviking" / "ov.conf",
        Path("/etc/openviking/ov.conf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            os.environ["OPENVIKING_CONFIG_FILE"] = str(candidate)
            return candidate

    raise RuntimeError(
        "OpenViking config file not found. "
        "Please create one at project root `ov.conf`, "
        "or set OPENVIKING_CONFIG_FILE to an absolute existing path."
    )


__all__ = ["OpenVikingMemoryBackend", "build_memory_backend"]
