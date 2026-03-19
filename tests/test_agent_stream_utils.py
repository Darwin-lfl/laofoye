from __future__ import annotations

from agent import _extract_text_deltas, _extract_thinking_deltas


class Chunk:
    def __init__(self, content, additional_kwargs=None):
        self.content = content
        self.additional_kwargs = additional_kwargs or {}


def test_extract_stream_deltas_separates_thinking_and_text():
    chunk = Chunk(
        content=[
            {"type": "reasoning", "text": "think step 1"},
            {"type": "text", "text": "final answer"},
        ]
    )

    assert _extract_thinking_deltas(chunk) == ["think step 1"]
    assert _extract_text_deltas(chunk) == ["final answer"]


def test_extract_thinking_from_additional_kwargs():
    chunk = Chunk(content=[], additional_kwargs={"reasoning": [{"text": "hidden thought"}]})

    assert _extract_thinking_deltas(chunk) == ["hidden thought"]
