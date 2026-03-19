from __future__ import annotations

import pytest

import agent as agent_module
from config import AgentConfig
from core_types import RunRequest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage


class DummyChatModel:
    def __init__(self, model: str, temperature: int, api_key: str, base_url: str | None = None):
        self.model = model
        self.temperature = temperature
        self.api_key = api_key
        self.base_url = base_url


class DummyApp:
    async def ainvoke(self, payload):
        return {"messages": [AIMessage(content="ok")]}


def _build_agent(monkeypatch, tmp_path) -> agent_module.LangGraphAgent:
    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: DummyApp())
    return agent_module.LangGraphAgent(
        config=AgentConfig(
            api_key="sk-test",
            history_keep_messages=4,
            history_compact_threshold=6,
            history_summary_max_chars=500,
        ),
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
