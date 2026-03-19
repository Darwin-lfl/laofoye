from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from langchain_core.messages import AIMessage

from memory.long_term import (
    LLMLongTermMemoryExtractor,
    LongTermMemoryWorker,
    MemoryExtraction,
    MemoryItem,
    apply_long_term_memory,
    read_memory_policy,
    sync_long_term_memory,
)


class DummyLLM:
    def __init__(self, payload: dict):
        self._payload = payload
        self.last_messages = None

    def invoke(self, messages):
        self.last_messages = messages
        return AIMessage(content=json.dumps(self._payload, ensure_ascii=False))


class FixedExtractor:
    def __init__(self, extraction: MemoryExtraction):
        self._extraction = extraction
        self.last_policy_text = None

    def extract(self, *, user_text: str, response_text: str, tools=None, policy_text=None):
        del user_text, response_text, tools
        self.last_policy_text = policy_text
        return self._extraction


def test_llm_extractor_parses_json_payload():
    llm = DummyLLM(
        {
            "semantic_memory": ["用户喜欢简洁回复"],
            "procedural_memory": ["必须使用 create_agent"],
            "episodic_memory": ["本轮修复了python_repl异常输出"],
        }
    )
    extractor = LLMLongTermMemoryExtractor(
        model="gpt-4o-mini",
        api_key="sk-test",
        llm=llm,
    )

    out = extractor.extract(
        user_text="u",
        response_text="a",
        tools=["terminal"],
        policy_text="What to keep:\n- Stable preferences",
    )
    assert [item.content for item in out.semantic] == ["用户喜欢简洁回复"]
    assert [item.content for item in out.procedural] == ["必须使用 create_agent"]
    assert [item.content for item in out.episodic] == ["本轮修复了python_repl异常输出"]
    system_prompt = str(llm.last_messages[0].content)
    assert "Memory Policy:" in system_prompt
    assert "Stable preferences" in system_prompt


def test_apply_long_term_memory_creates_three_sections(tmp_path):
    apply_long_term_memory(
        tmp_path,
        MemoryExtraction(
            semantic=[MemoryItem(content="我更喜欢简洁输出")],
            procedural=[MemoryItem(content="你必须使用 LangChain 1.x create_agent")],
            episodic=[MemoryItem(content="修复了上下文超限自动重试")],
        ),
    )

    content = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "## Memory Policy" in content
    assert "## Semantic Memory" in content
    assert "## Procedural Memory" in content
    assert "## Episodic Memory" in content
    assert "我更喜欢简洁输出" in content
    assert "你必须使用 LangChain 1.x create_agent" in content
    assert "修复了上下文超限自动重试" in content


def test_apply_long_term_memory_deduplicates(tmp_path):
    extraction = MemoryExtraction(
        semantic=[MemoryItem(content="我喜欢中文回复")],
        procedural=[MemoryItem(content="你必须使用 create_agent")],
        episodic=[MemoryItem(content="完成一次代码修复")],
    )
    apply_long_term_memory(tmp_path, extraction)
    apply_long_term_memory(tmp_path, extraction)

    content = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    semantic_block = content.split("## Semantic Memory", 1)[1].split("## Procedural Memory", 1)[0]
    procedural_block = content.split("## Procedural Memory", 1)[1].split("## Episodic Memory", 1)[0]
    assert semantic_block.count("- 我喜欢中文回复") == 1
    assert procedural_block.count("- 你必须使用 create_agent") == 1


def test_long_term_memory_worker_runs_in_background_thread(tmp_path):
    extractor = FixedExtractor(
        MemoryExtraction(
            semantic=[MemoryItem(content="semantic")],
            procedural=[MemoryItem(content="procedural")],
            episodic=[MemoryItem(content="episodic")],
        )
    )
    worker = LongTermMemoryWorker(extractor=extractor)
    (tmp_path / "MEMORY.md").write_text(
        "# MEMORY.md - Long-Term Memory\n\n"
        "## Memory Policy\n"
        "What to keep:\n- Durable decisions\n\n"
        "## Semantic Memory\n- (none yet)\n\n"
        "## Procedural Memory\n- (none yet)\n\n"
        "## Episodic Memory\n- (none yet)\n",
        encoding="utf-8",
    )
    worker.start()
    worker.submit(
        workspace_dir=tmp_path,
        user_text="u",
        response_text="a",
        tools=["tool-a"],
    )
    worker.stop(timeout_seconds=2.0)

    content = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "semantic" in content
    assert "procedural" in content
    assert "episodic" in content
    assert "Durable decisions" in str(extractor.last_policy_text)


def test_apply_long_term_memory_preserves_legacy_content(tmp_path):
    (tmp_path / "MEMORY.md").write_text(
        "# MEMORY.md - Long-Term Memory\n\nOld custom notes that should not be dropped.\n",
        encoding="utf-8",
    )

    apply_long_term_memory(
        tmp_path,
        MemoryExtraction(
            semantic=[],
            procedural=[],
            episodic=[MemoryItem(content="event")],
        ),
    )

    content = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "## Legacy Notes" in content
    assert "Old custom notes that should not be dropped." in content


def test_read_memory_policy_defaults_and_legacy_parse(tmp_path):
    assert "What to keep:" in read_memory_policy(tmp_path)
    (tmp_path / "MEMORY.md").write_text(
        "# MEMORY.md - Long-Term Memory\n\n"
        "What to keep:\n- Stable preferences\n\n"
        "What not to keep:\n- One-off noise\n",
        encoding="utf-8",
    )
    policy = read_memory_policy(tmp_path)
    assert "Stable preferences" in policy
    assert "One-off noise" in policy


def test_sync_long_term_memory_expires_temporal_items(tmp_path):
    t0 = datetime(2026, 3, 18, 9, 0, tzinfo=UTC)
    apply_long_term_memory(
        tmp_path,
        MemoryExtraction(
            semantic=[],
            procedural=[],
            episodic=[MemoryItem(content="南京今天小雨有雾", ttl_hours=12)],
        ),
        now=t0,
    )
    before = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "南京今天小雨有雾" in before
    assert "valid_until:" in before

    sync_long_term_memory(tmp_path, now=t0 + timedelta(hours=13))
    after = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "南京今天小雨有雾" not in after


def test_sync_long_term_memory_prunes_policy_noise_records(tmp_path):
    (tmp_path / ".long_term_memory.json").write_text(
        json.dumps(
            [
                {
                    "memory_type": "episodic",
                    "content": "# MEMORY.md - Long-Term Memory Curated long-term memory across sessions. What to keep: - Stable preferences",
                    "created_at": "2026-03-18T11:41:53+00:00",
                    "updated_at": "2026-03-18T11:41:53+00:00",
                    "ttl_hours": None,
                    "valid_until": None,
                    "decay": "hard_expire",
                    "confidence": None,
                    "status": "active",
                },
                {
                    "memory_type": "episodic",
                    "content": "真实记忆条目",
                    "created_at": "2026-03-18T11:41:53+00:00",
                    "updated_at": "2026-03-18T11:41:53+00:00",
                    "ttl_hours": None,
                    "valid_until": None,
                    "decay": "hard_expire",
                    "confidence": None,
                    "status": "active",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    sync_long_term_memory(tmp_path, now=datetime(2026, 3, 18, 12, 0, tzinfo=UTC))
    content = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "真实记忆条目" in content
    assert "# MEMORY.md - Long-Term Memory Curated long-term memory across sessions" not in content
