from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


def read_global_memory(home_dir: Path) -> str:
    path = home_dir / "memory" / "MEMORY.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_global_memory(home_dir: Path, content: str) -> None:
    path = home_dir / "memory" / "MEMORY.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def extract_summary(content: str) -> str:
    marker = "## Summary\n"
    if marker not in content:
        return ""
    tail = content.split(marker, 1)[1]
    if "\n---" in tail:
        return tail.split("\n---", 1)[0].strip()
    return ""


def read_recent_summaries(workspace_dir: Path, days: int, now_date: str | None = None) -> str:
    mem_dir = workspace_dir / "memory"
    if not mem_dir.exists():
        return ""

    if now_date:
        current = datetime.fromisoformat(now_date).date()
    else:
        current = datetime.now().date()

    chunks: list[str] = []
    for offset in range(days):
        date = current - timedelta(days=offset)
        file = mem_dir / f"{date.isoformat()}.md"
        if not file.exists():
            continue
        summary = extract_summary(file.read_text(encoding="utf-8"))
        if summary:
            chunks.append(f"### {date.isoformat()}\n{summary}")
    return "\n\n".join(chunks)
