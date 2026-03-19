from __future__ import annotations

import json
import queue
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from utils import get_logger

log = get_logger("memory.long_term")

SEMANTIC_SECTION = "Semantic Memory"
PROCEDURAL_SECTION = "Procedural Memory"
EPISODIC_SECTION = "Episodic Memory"
POLICY_SECTION = "Memory Policy"
LEGACY_SECTION = "Legacy Notes"

MAX_SEMANTIC_ITEMS = 120
MAX_PROCEDURAL_ITEMS = 120
MAX_EPISODIC_ITEMS = 200
MAX_TTL_HOURS = 24 * 365
MEMORY_STORE_FILE = ".long_term_memory.json"

DEFAULT_MEMORY_POLICY = (
    "What to keep:\n"
    "- Stable preferences\n"
    "- Durable decisions\n"
    "- Important context that should survive restarts\n"
    "- Lessons and patterns worth remembering\n"
    "\n"
    "What not to keep:\n"
    "- Raw logs (put those in `memory/YYYY-MM-DD.md`)\n"
    "- Sensitive details unless explicitly requested\n"
    "- One-off noise\n"
    "\n"
    "Keep this concise and regularly prune outdated items."
)


@dataclass(slots=True)
class MemoryItem:
    content: str
    ttl_hours: int | None = None
    valid_until: str | None = None
    decay: str = "hard_expire"
    confidence: float | None = None


@dataclass(slots=True)
class MemoryExtraction:
    semantic: list[MemoryItem]
    procedural: list[MemoryItem]
    episodic: list[MemoryItem]


class MemoryExtractor(Protocol):
    def extract(
        self,
        *,
        user_text: str,
        response_text: str,
        tools: list[str] | None = None,
        policy_text: str | None = None,
    ) -> MemoryExtraction: ...


class LLMLongTermMemoryExtractor:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str | None = None,
        llm: object | None = None,
    ) -> None:
        self._llm = llm or ChatOpenAI(
            model=model,
            temperature=0,
            api_key=api_key,
            base_url=base_url,
        )

    def extract(
        self,
        *,
        user_text: str,
        response_text: str,
        tools: list[str] | None = None,
        policy_text: str | None = None,
    ) -> MemoryExtraction:
        payload = {
            "user_text": user_text,
            "assistant_response": response_text,
            "tools": tools or [],
        }
        messages: list[BaseMessage] = [
            SystemMessage(
                content=(
                    "You extract long-term memory from one conversation turn.\n"
                    "Return STRICT JSON only (no markdown, no commentary):\n"
                    "{\n"
                    '  "semantic_memory": [{"content":"...", "ttl_hours": null, "valid_until": null, "decay": "soft_decay", "confidence": 0.0}],\n'
                    '  "procedural_memory": [{"content":"...", "ttl_hours": null, "valid_until": null, "decay": "hard_expire", "confidence": 0.0}],\n'
                    '  "episodic_memory": [{"content":"...", "ttl_hours": 24, "valid_until": null, "decay": "hard_expire", "confidence": 0.0}]\n'
                    "}\n"
                    "Rules:\n"
                    "- semantic_memory: stable user preferences/identity/durable facts.\n"
                    "- procedural_memory: durable instructions/rules for assistant behavior.\n"
                    "- episodic_memory: key event/decision summaries from this turn.\n"
                    "- Temporal facts (weather/news/stock/current status) MUST have short ttl_hours or valid_until.\n"
                    "- If memory is valid only for 'today', set valid_until to end of today.\n"
                    "- Keep content <=160 chars, max 3 items each list, no duplicates.\n"
                    "- If nothing applies for a list, return [].\n"
                    "- Keep original language.\n"
                    "\n"
                    "Memory Policy:\n"
                    f"{(policy_text or DEFAULT_MEMORY_POLICY).strip()}"
                )
            ),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ]

        result = self._llm.invoke(messages)
        text = _message_text(result)
        parsed = _parse_json_object(text)
        if parsed is None:
            log.warning("LLM memory extraction returned non-JSON payload; skip turn.")
            return MemoryExtraction(semantic=[], procedural=[], episodic=[])

        return MemoryExtraction(
            semantic=_clean_extracted_items(parsed.get("semantic_memory", []), max_items=3),
            procedural=_clean_extracted_items(parsed.get("procedural_memory", []), max_items=3),
            episodic=_clean_extracted_items(parsed.get("episodic_memory", []), max_items=3),
        )


@dataclass(slots=True)
class MemoryTask:
    workspace_dir: Path
    user_text: str
    response_text: str
    tools: list[str] | None


class LongTermMemoryWorker:
    def __init__(
        self,
        *,
        extractor: MemoryExtractor,
        queue_size: int = 256,
    ) -> None:
        self._extractor = extractor
        self._queue: queue.Queue[MemoryTask | None] = queue.Queue(maxsize=max(1, queue_size))
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run_loop,
                name="long-term-memory-worker",
                daemon=True,
            )
            self._thread.start()

    def submit(
        self,
        *,
        workspace_dir: Path,
        user_text: str,
        response_text: str,
        tools: list[str] | None = None,
    ) -> bool:
        task = MemoryTask(
            workspace_dir=workspace_dir,
            user_text=user_text,
            response_text=response_text,
            tools=tools,
        )
        try:
            self._queue.put_nowait(task)
            return True
        except queue.Full:
            log.warning("Long-term memory queue is full; dropping task.")
            return False

    def stop(self, timeout_seconds: float = 5.0) -> None:
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            while True:
                try:
                    self._queue.put(None, timeout=0.1)
                    break
                except queue.Full:
                    continue
            thread.join(timeout=timeout_seconds)
            self._thread = None

    def _run_loop(self) -> None:
        while True:
            task = self._queue.get()
            try:
                if task is None:
                    return
                extraction = self._extractor.extract(
                    user_text=task.user_text,
                    response_text=task.response_text,
                    tools=task.tools,
                    policy_text=read_memory_policy(task.workspace_dir),
                )
                apply_long_term_memory(task.workspace_dir, extraction)
            except Exception:  # noqa: BLE001
                log.exception("Failed to process long-term memory task")
            finally:
                self._queue.task_done()


def apply_long_term_memory(
    workspace_dir: Path,
    extraction: MemoryExtraction,
    *,
    now: datetime | None = None,
) -> None:
    now_dt = _coerce_now(now)
    path = workspace_dir / "MEMORY.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    sections, legacy_notes, policy_text = _parse_sections(existing)

    records = _load_store(workspace_dir)
    if not records:
        records = _bootstrap_records_from_sections(sections, now_dt)

    _merge_records(records, "semantic", extraction.semantic, now_dt)
    _merge_records(records, "procedural", extraction.procedural, now_dt)
    _merge_records(records, "episodic", extraction.episodic, now_dt)
    records = _prune_invalid_records(records)
    legacy_notes = _clean_legacy_notes(legacy_notes)
    _mark_expired(records, now_dt)
    _trim_records(records)

    _save_store(workspace_dir, records)
    _write_memory_md(workspace_dir, records, policy_text, legacy_notes)


def sync_long_term_memory(workspace_dir: Path, *, now: datetime | None = None) -> None:
    now_dt = _coerce_now(now)
    path = workspace_dir / "MEMORY.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    sections, legacy_notes, policy_text = _parse_sections(existing)

    records = _load_store(workspace_dir)
    if not records and any(sections.values()):
        records = _bootstrap_records_from_sections(sections, now_dt)
    records = _prune_invalid_records(records)
    legacy_notes = _clean_legacy_notes(legacy_notes)
    _mark_expired(records, now_dt)
    _trim_records(records)
    _save_store(workspace_dir, records)
    _write_memory_md(workspace_dir, records, policy_text, legacy_notes)


def read_memory_policy(workspace_dir: Path) -> str:
    path = workspace_dir / "MEMORY.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    _, _, policy_text = _parse_sections(existing)
    return policy_text


def _write_memory_md(
    workspace_dir: Path,
    records: list[dict[str, object]],
    policy_text: str,
    legacy_notes: list[str],
) -> None:
    sections: dict[str, list[str]] = {
        SEMANTIC_SECTION: [],
        PROCEDURAL_SECTION: [],
        EPISODIC_SECTION: [],
    }
    for record in records:
        if record.get("status") != "active":
            continue
        bucket = str(record.get("memory_type", ""))
        content = str(record.get("content", "")).strip()
        if not content:
            continue
        valid_until = record.get("valid_until")
        if isinstance(valid_until, str) and valid_until:
            content = f"{content} [valid_until: {valid_until}]"
        if bucket == "semantic":
            sections[SEMANTIC_SECTION].append(content)
        elif bucket == "procedural":
            sections[PROCEDURAL_SECTION].append(content)
        elif bucket == "episodic":
            sections[EPISODIC_SECTION].append(content)

    rendered = _render_sections(sections, legacy_notes, policy_text)
    (workspace_dir / "MEMORY.md").write_text(rendered, encoding="utf-8")


def _load_store(workspace_dir: Path) -> list[dict[str, object]]:
    path = workspace_dir / MEMORY_STORE_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, object]] = []
    for item in data:
        if isinstance(item, dict):
            out.append(dict(item))
    return out


def _save_store(workspace_dir: Path, records: list[dict[str, object]]) -> None:
    path = workspace_dir / MEMORY_STORE_FILE
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _bootstrap_records_from_sections(
    sections: dict[str, list[str]],
    now_dt: datetime,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for content in sections.get(SEMANTIC_SECTION, []):
        if content == "(none yet)":
            continue
        records.append(_make_record("semantic", MemoryItem(content=_strip_valid_suffix(content)), now_dt))
    for content in sections.get(PROCEDURAL_SECTION, []):
        if content == "(none yet)":
            continue
        records.append(_make_record("procedural", MemoryItem(content=_strip_valid_suffix(content)), now_dt))
    for content in sections.get(EPISODIC_SECTION, []):
        if content == "(none yet)":
            continue
        records.append(_make_record("episodic", MemoryItem(content=_strip_valid_suffix(content)), now_dt))
    return records


def _strip_valid_suffix(text: str) -> str:
    return re.sub(r"\s*\[valid_until:\s*[^\]]+\]\s*$", "", text).strip()


def _merge_records(
    records: list[dict[str, object]],
    memory_type: str,
    items: list[MemoryItem],
    now_dt: datetime,
) -> None:
    for item in items:
        content = _compact(item.content.strip(), max_len=160)
        if not content:
            continue
        if _is_invalid_memory_content(content):
            continue
        norm = _normalize(content)
        match: dict[str, object] | None = None
        for record in records:
            if record.get("memory_type") != memory_type:
                continue
            if _normalize(str(record.get("content", ""))) != norm:
                continue
            match = record
            break

        valid_until = _resolve_valid_until(item, now_dt)
        if match is None:
            records.append(_make_record(memory_type, item, now_dt, content=content, valid_until=valid_until))
            continue

        match["updated_at"] = _dt_to_iso(now_dt)
        match["status"] = "active"
        if valid_until:
            prev_dt = _parse_dt(match.get("valid_until"))
            new_dt = _parse_dt(valid_until)
            if new_dt and (prev_dt is None or new_dt > prev_dt):
                match["valid_until"] = valid_until
        if item.confidence is not None:
            match["confidence"] = float(item.confidence)
        if item.decay:
            match["decay"] = item.decay


def _make_record(
    memory_type: str,
    item: MemoryItem,
    now_dt: datetime,
    *,
    content: str | None = None,
    valid_until: str | None = None,
) -> dict[str, object]:
    return {
        "memory_type": memory_type,
        "content": content or item.content,
        "created_at": _dt_to_iso(now_dt),
        "updated_at": _dt_to_iso(now_dt),
        "ttl_hours": item.ttl_hours,
        "valid_until": valid_until or _resolve_valid_until(item, now_dt),
        "decay": item.decay or "hard_expire",
        "confidence": item.confidence,
        "status": "active",
    }


def _resolve_valid_until(item: MemoryItem, now_dt: datetime) -> str | None:
    if item.valid_until:
        parsed = _parse_dt(item.valid_until)
        if parsed:
            return _dt_to_iso(parsed)
    if item.ttl_hours and item.ttl_hours > 0:
        capped = min(item.ttl_hours, MAX_TTL_HOURS)
        return _dt_to_iso(now_dt + timedelta(hours=capped))
    return None


def _mark_expired(records: list[dict[str, object]], now_dt: datetime) -> None:
    for record in records:
        valid_until = _parse_dt(record.get("valid_until"))
        if valid_until and valid_until <= now_dt:
            record["status"] = "expired"


def _trim_records(records: list[dict[str, object]]) -> None:
    by_type: dict[str, list[dict[str, object]]] = {"semantic": [], "procedural": [], "episodic": []}
    for record in records:
        t = str(record.get("memory_type", ""))
        if t in by_type:
            by_type[t].append(record)

    limits = {"semantic": MAX_SEMANTIC_ITEMS, "procedural": MAX_PROCEDURAL_ITEMS, "episodic": MAX_EPISODIC_ITEMS}
    trimmed: list[dict[str, object]] = []
    for t, group in by_type.items():
        group.sort(key=lambda r: str(r.get("updated_at", "")))
        if len(group) > limits[t]:
            group = group[-limits[t] :]
        trimmed.extend(group)
    records.clear()
    records.extend(trimmed)


def _parse_sections(text: str) -> tuple[dict[str, list[str]], list[str], str]:
    keys = [SEMANTIC_SECTION, PROCEDURAL_SECTION, EPISODIC_SECTION]
    sections: dict[str, list[str]] = {key: [] for key in keys}
    legacy: list[str] = []
    policy_text = DEFAULT_MEMORY_POLICY
    if not text.strip():
        return sections, legacy, policy_text

    policy_body = _extract_section_body(text, POLICY_SECTION)
    if policy_body:
        policy_text = policy_body
    elif "What to keep:" in text and "What not to keep:" in text:
        policy_text = _extract_legacy_policy(text)

    positions: list[tuple[int, str]] = []
    for key in keys:
        marker = f"## {key}"
        idx = text.find(marker)
        if idx != -1:
            positions.append((idx, key))

    if not positions:
        if not policy_body and not ("What to keep:" in text and "What not to keep:" in text):
            legacy_item = _compact(" ".join(text.split()), max_len=1200)
            if legacy_item:
                legacy = [legacy_item]
        return sections, legacy, policy_text

    positions.sort()
    for i, (start, key) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        chunk = text[start:end]
        lines = [line[2:].strip() for line in chunk.splitlines() if line.startswith("- ")]
        sections[key] = [line for line in lines if line]

    legacy_pos = text.find(f"## {LEGACY_SECTION}")
    if legacy_pos != -1:
        legacy_chunk = text[legacy_pos:]
        legacy = [line[2:].strip() for line in legacy_chunk.splitlines() if line.startswith("- ")]

    return sections, legacy, policy_text


def _render_sections(
    sections: dict[str, list[str]],
    legacy_notes: list[str],
    policy_text: str,
) -> str:
    out: list[str] = [
        "# MEMORY.md - Long-Term Memory",
        "",
        "Curated long-term memory across sessions.",
        "",
        f"## {POLICY_SECTION}",
    ]
    out.extend((policy_text or DEFAULT_MEMORY_POLICY).strip().splitlines())
    out.extend(
        [
            "",
            f"## {SEMANTIC_SECTION}",
        ]
    )
    out.extend(_render_items(sections[SEMANTIC_SECTION]))
    out.extend(
        [
            "",
            f"## {PROCEDURAL_SECTION}",
        ]
    )
    out.extend(_render_items(sections[PROCEDURAL_SECTION]))
    out.extend(
        [
            "",
            f"## {EPISODIC_SECTION}",
        ]
    )
    out.extend(_render_items(sections[EPISODIC_SECTION]))
    if legacy_notes:
        out.extend(
            [
                "",
                f"## {LEGACY_SECTION}",
            ]
        )
        out.extend(_render_items(legacy_notes))
    out.append("")
    return "\n".join(out)


def _render_items(items: list[str]) -> list[str]:
    if not items:
        return ["- (none yet)"]
    return [f"- {item}" for item in items]


def _clean_extracted_items(raw: object, *, max_items: int) -> list[MemoryItem]:
    if not isinstance(raw, list):
        return []
    out: list[MemoryItem] = []
    for item in raw:
        parsed = _parse_extracted_item(item)
        if parsed is None:
            continue
        if _normalize(parsed.content) in {_normalize(existing.content) for existing in out}:
            continue
        out.append(parsed)
        if len(out) >= max_items:
            break
    return out


def _parse_extracted_item(item: object) -> MemoryItem | None:
    if isinstance(item, str):
        content = _compact(item.strip(), max_len=160)
        return MemoryItem(content=content) if content else None
    if not isinstance(item, dict):
        return None
    content = _compact(str(item.get("content", "")).strip(), max_len=160)
    if not content:
        return None
    if _is_invalid_memory_content(content):
        return None

    ttl_raw = item.get("ttl_hours")
    ttl_hours: int | None = None
    if isinstance(ttl_raw, int):
        ttl_hours = max(1, min(MAX_TTL_HOURS, ttl_raw))
    elif isinstance(ttl_raw, float):
        ttl_hours = max(1, min(MAX_TTL_HOURS, int(ttl_raw)))

    valid_until_raw = item.get("valid_until")
    valid_until = str(valid_until_raw).strip() if isinstance(valid_until_raw, str) else None
    if valid_until and _parse_dt(valid_until) is None:
        valid_until = None

    decay_raw = str(item.get("decay", "hard_expire")).strip().lower()
    decay = decay_raw if decay_raw in {"hard_expire", "soft_decay"} else "hard_expire"

    conf_raw = item.get("confidence")
    confidence: float | None = None
    if isinstance(conf_raw, (int, float)):
        confidence = max(0.0, min(1.0, float(conf_raw)))

    return MemoryItem(
        content=content,
        ttl_hours=ttl_hours,
        valid_until=valid_until,
        decay=decay,
        confidence=confidence,
    )


def _extract_section_body(text: str, section_title: str) -> str:
    pattern = rf"(?ms)^## {re.escape(section_title)}\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, text)
    if not match:
        return ""
    return match.group(1).strip()


def _extract_legacy_policy(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return DEFAULT_MEMORY_POLICY

    policy_lines: list[str] = []
    capture = False
    for line in lines:
        lower = line.lower()
        if lower.startswith("what to keep:"):
            capture = True
        if capture:
            if line.startswith("## "):
                break
            policy_lines.append(line)
    if policy_lines:
        return "\n".join(policy_lines).strip()
    return DEFAULT_MEMORY_POLICY


def _parse_json_object(text: str) -> dict[str, object] | None:
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        return None
    return None


def _prune_invalid_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for record in records:
        content = str(record.get("content", "")).strip()
        if not content:
            continue
        if _is_invalid_memory_content(content):
            continue
        out.append(record)
    return out


def _clean_legacy_notes(notes: list[str]) -> list[str]:
    cleaned: list[str] = []
    for note in notes:
        text = note.strip()
        if not text:
            continue
        if _is_invalid_memory_content(text):
            continue
        if _normalize(text) in {_normalize(existing) for existing in cleaned}:
            continue
        cleaned.append(text)
    return cleaned


def _is_invalid_memory_content(text: str) -> bool:
    norm = _normalize(text)
    if not norm or norm == "(none yet)":
        return True
    signals = (
        "# memory.md - long-term memory",
        "curated long-term memory across sessions",
        "what to keep:",
        "what not to keep:",
        "keep this concise and regularly prune outdated items",
    )
    hit = sum(1 for signal in signals if signal in norm)
    if hit >= 2:
        return True
    return False


def _message_text(message: object) -> str:
    if isinstance(message, AIMessage):
        content = message.content
    elif isinstance(message, BaseMessage):
        content = message.content
    else:
        content = getattr(message, "content", message)

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _compact(text: str, *, max_len: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3] + "..."


def _dt_to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _coerce_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)
