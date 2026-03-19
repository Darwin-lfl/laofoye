from __future__ import annotations

from memory.daily import append_daily_entry
from memory.global_memory import read_recent_summaries


def test_append_daily_entry_creates_file(tmp_path):
    append_daily_entry(
        workspace_dir=tmp_path,
        user_text="hello",
        response_text="world",
        tools=["web_search"],
    )

    memory_dir = tmp_path / "memory"
    files = list(memory_dir.glob("*.md"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "**Q:** hello" in content
    assert "**A:** world" in content
    assert "web_search" in content


def test_read_recent_summaries(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True)
    today = "2099-01-01"
    (memory_dir / f"{today}.md").write_text(
        "## Summary\nimportant summary\n\n---\n\n### 09:00\n**Q:** q\n**A:** a\n",
        encoding="utf-8",
    )

    text = read_recent_summaries(tmp_path, days=1, now_date=today)
    assert today in text
    assert "important summary" in text
