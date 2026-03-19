from __future__ import annotations

from agent import _extract_text_deltas, _extract_thinking_deltas, _extract_token_usage
from langchain_core.messages import AIMessage


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


def test_extract_token_usage_from_usage_metadata():
    msg = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 13, "output_tokens": 8, "total_tokens": 21},
    )

    input_tokens, output_tokens = _extract_token_usage([msg])

    assert input_tokens == 13
    assert output_tokens == 8


def test_extract_token_usage_from_response_metadata_token_usage():
    msg = AIMessage(
        content="ok",
        response_metadata={"token_usage": {"prompt_tokens": 7, "completion_tokens": 5}},
    )

    input_tokens, output_tokens = _extract_token_usage([msg])

    assert input_tokens == 7
    assert output_tokens == 5


def test_extract_token_usage_aggregates_across_multiple_ai_messages():
    msg1 = AIMessage(
        content="first",
        usage_metadata={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13},
    )
    msg2 = AIMessage(
        content="second",
        response_metadata={"token_usage": {"prompt_tokens": 4, "completion_tokens": 9}},
    )

    input_tokens, output_tokens = _extract_token_usage([msg1, msg2])

    assert input_tokens == 14
    assert output_tokens == 12
