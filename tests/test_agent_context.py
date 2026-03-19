from __future__ import annotations

import pytest

import agent as agent_module
from config import AgentConfig
from core_types import RunRequest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage


class DummyChatModel:
    def __init__(self, model: str, temperature: int, api_key: str, base_url: str | None = None):
        self.model = model
        self.temperature = temperature
        self.api_key = api_key
        self.base_url = base_url


class DummyApp:
    async def ainvoke(self, payload):
        return {"messages": [AIMessage(content="ok")]}


def _build_agent(monkeypatch, tmp_path, **config_overrides) -> agent_module.LangGraphAgent:
    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: DummyApp())
    config_data = dict(
        api_key="sk-test",
        history_keep_messages=4,
        history_compact_threshold=6,
        history_summary_max_chars=500,
    )
    config_data.update(config_overrides)
    return agent_module.LangGraphAgent(
        config=AgentConfig(**config_data),
        workspaces_dir=tmp_path / "workspaces",
        skills_dir=tmp_path / "skills",
        scheduler_store=None,
    )


def test_build_payload_compacts_long_history(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    workspace = agent_obj._prepare_workspace("local")
    conversation_id = "local"

    history: list[BaseMessage] = []
    for i in range(4):
        history.append(HumanMessage(content=f"user-{i}"))
        history.append(AIMessage(content=f"assistant-{i}"))
    agent_obj._history[conversation_id] = history

    payload = agent_obj._build_payload(
        conversation_id=conversation_id,
        workspace_dir=workspace,
        user_text="new turn",
    )

    summary_blocks = [
        msg for msg in payload if isinstance(msg, SystemMessage) and "Conversation Summary" in str(msg.content)
    ]
    assert len(summary_blocks) == 1
    assert "- User:" in str(summary_blocks[0].content)
    assert len(agent_obj._history[conversation_id]) == 4


@pytest.mark.asyncio
async def test_run_retries_after_context_length_error(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    conversation_id = "chat-1"
    agent_obj._prepare_workspace(conversation_id)

    history: list[BaseMessage] = []
    for i in range(5):
        history.append(HumanMessage(content=f"user-{i}"))
        history.append(AIMessage(content=f"assistant-{i}"))
    agent_obj._history[conversation_id] = history

    calls = 0
    captured_payloads: list[list[BaseMessage]] = []

    async def fake_invoke(payload: list[BaseMessage], workspace_dir):
        nonlocal calls
        calls += 1
        captured_payloads.append(payload)
        if calls == 1:
            raise RuntimeError("maximum context length exceeded")
        return [AIMessage(content="retry-ok")]

    monkeypatch.setattr(agent_obj, "_invoke_messages", fake_invoke)

    response = await agent_obj.run(
        RunRequest(
            text="hello",
            conversation_id=conversation_id,
            chat_id=conversation_id,
        )
    )

    assert calls == 2
    assert response.text == "retry-ok"
    assert any(
        isinstance(msg, SystemMessage) and "Conversation Summary" in str(msg.content)
        for msg in captured_payloads[1]
    )


def test_runtime_context_injected_but_stripped_from_history(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    workspace = agent_obj._prepare_workspace("chat-runtime")

    payload = agent_obj._build_payload(
        conversation_id="chat-runtime",
        workspace_dir=workspace,
        user_text="hello runtime",
        runtime_context={"current_time": "2026-03-19T10:00:00", "current_chat_id": "chat-runtime"},
    )

    user_message = payload[-1]
    assert isinstance(user_message, HumanMessage)
    assert str(user_message.content).startswith(agent_module.RUNTIME_CONTEXT_TAG)

    agent_obj._store_history(
        "chat-runtime",
        payload + [AIMessage(content="ok")],
    )
    stored = agent_obj._history["chat-runtime"]
    stored_user = next(msg for msg in stored if isinstance(msg, HumanMessage))
    assert stored_user.content == "hello runtime"


def test_payload_history_drops_orphan_tool_messages(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path, history_compact_threshold=100)
    workspace = agent_obj._prepare_workspace("chat-tools")

    orphan = ToolMessage(content="orphan", tool_call_id="call_orphan", name="terminal")
    linked_ai = AIMessage(
        content="",
        tool_calls=[{"id": "call_ok", "type": "tool_call", "name": "terminal", "args": {}}],
    )
    linked_tool = ToolMessage(content="ok", tool_call_id="call_ok", name="terminal")
    agent_obj._history["chat-tools"] = [
        orphan,
        HumanMessage(content="do something"),
        linked_ai,
        linked_tool,
    ]

    payload = agent_obj._build_payload(
        conversation_id="chat-tools",
        workspace_dir=workspace,
        user_text="new turn",
    )

    tool_ids = [
        msg.tool_call_id
        for msg in payload
        if isinstance(msg, ToolMessage)
    ]
    assert "call_orphan" not in tool_ids
    assert "call_ok" in tool_ids


@pytest.mark.asyncio
async def test_run_preflight_compacts_history_before_invoke(monkeypatch, tmp_path):
    agent_obj = _build_agent(
        monkeypatch,
        tmp_path,
        history_keep_messages=4,
        history_compact_threshold=100,
        context_window_tokens=200,
    )
    conversation_id = "chat-preflight"
    workspace = agent_obj._prepare_workspace(conversation_id)

    history: list[BaseMessage] = []
    for i in range(8):
        history.append(HumanMessage(content=f"user-{i}"))
        history.append(AIMessage(content=f"assistant-{i}"))
    agent_obj._history[conversation_id] = history

    token_probe = {"count": 0}

    def fake_estimate(_payload):
        token_probe["count"] += 1
        return 500 if token_probe["count"] == 1 else 80

    async def fake_invoke(payload: list[BaseMessage], workspace_dir):
        del payload, workspace_dir
        assert len(agent_obj._history[conversation_id]) == 4
        return [AIMessage(content="ok")]

    monkeypatch.setattr(agent_module, "_estimate_prompt_tokens", fake_estimate)
    monkeypatch.setattr(agent_obj, "_invoke_messages", fake_invoke)

    response = await agent_obj.run(
        RunRequest(
            text="hello",
            conversation_id=conversation_id,
            chat_id=conversation_id,
            runtime_context={"current_time": "2026-03-19T10:00:00", "current_chat_id": conversation_id},
        )
    )

    assert response.text == "ok"
