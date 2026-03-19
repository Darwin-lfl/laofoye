from __future__ import annotations

from datetime import datetime
from pathlib import Path

from memory.global_memory import read_global_memory, write_global_memory

CONSOLIDATED_MARKER = "<!-- consolidated -->"


def _today_file(workspace_dir: Path, now: datetime | None = None) -> Path:
    dt = now or datetime.now()
    memory_dir = workspace_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir / f"{dt.date().isoformat()}.md"


def append_daily_entry(
    workspace_dir: Path,
    user_text: str,
    response_text: str,
    tools: list[str] | None = None,
) -> None:
    file = _today_file(workspace_dir)
    ts = datetime.now().strftime("%H:%M")
    suffix = f" ({', '.join(tools)})" if tools else ""
    entry = f"### {ts}{suffix}\n**Q:** {user_text}\n**A:** {response_text}\n\n"
    with file.open("a", encoding="utf-8") as fp:
        fp.write(entry)


def consolidate(workspace_dir: Path, date: str | None = None) -> bool:
    target = (workspace_dir / "memory" / f"{date}.md") if date else _today_file(workspace_dir)
    if not target.exists():
        return True

    content = target.read_text(encoding="utf-8").strip()
    if not content:
        return True

    if CONSOLIDATED_MARKER in content:
        return True

    entries = [line for line in content.splitlines() if line.startswith("### ")]
    summary = f"{len(entries)} entries consolidated." if entries else "No entries."
    rebuilt = f"## Summary\n{summary}\n\n---\n\n{content}\n\n{CONSOLIDATED_MARKER}\n"
    target.write_text(rebuilt, encoding="utf-8")

    home_dir = workspace_dir.parent.parent
    memory = read_global_memory(home_dir)
    if "entries consolidated" not in memory:
        write_global_memory(home_dir, (memory + "\n- Daily consolidation running.").strip())
    return True
