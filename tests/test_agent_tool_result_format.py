from __future__ import annotations

from agent import _format_tool_output
from langchain_core.messages import ToolMessage


def test_format_tool_output_with_dict_and_none():
    assert _format_tool_output(None) == "(no output)"
    text = _format_tool_output({"ok": True, "count": 2})
    assert '"ok": true' in text
    assert '"count": 2' in text


def test_format_tool_output_truncates_long_text():
    raw = "x" * 6000
    out = _format_tool_output(raw)
    assert out.endswith("...[truncated]")
    assert len(out) < len(raw)


def test_format_tool_output_extracts_tool_message_content():
    msg = ToolMessage(content="plain tool output", tool_call_id="python_repl:1", name="python_repl")
    out = _format_tool_output(msg)
    assert out == "plain tool output"
