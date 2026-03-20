from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import agent as agent_module
from config import AgentConfig
from core_types import RunRequest
from langchain_core.messages import AIMessage


class DummyChatModel:
    def __init__(self, model: str, temperature: int, api_key: str, base_url: str | None = None):
        self.model = model
        self.temperature = temperature
        self.api_key = api_key
        self.base_url = base_url


class CaptureApp:
    def __init__(self) -> None:
        self.last_config = None

    async def ainvoke(self, payload, config=None):
        del payload
        self.last_config = config
        return {"messages": [AIMessage(content="ok")]}


@pytest.mark.asyncio
async def test_run_injects_langfuse_callback_and_metadata(monkeypatch, tmp_path):
    app = CaptureApp()
    captured: dict[str, object] = {}
    fake_handler = object()

    def fake_handler_builder(**kwargs):
        captured.update(kwargs)
        return fake_handler

    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: app)
    monkeypatch.setattr(agent_module, "_build_langfuse_handler", fake_handler_builder, raising=False)

    agent_obj = agent_module.LangGraphAgent(
        config=AgentConfig(
            api_key="sk-test",
            langfuse_enabled=True,
            langfuse_public_key="pk-test",
            langfuse_secret_key="sk-langfuse",
            langfuse_host="https://langfuse.example.com",
        ),
        workspaces_dir=tmp_path / "workspaces",
        skills_dir=tmp_path / "skills",
        scheduler_store=None,
    )

    response = await agent_obj.run(
        RunRequest(
            text="hello",
            conversation_id="conv-1",
            chat_id="chat-1",
            runtime_context={"current_time": "2026-03-20T10:00:00"},
        )
    )

    assert response.text == "ok"
    assert captured["public_key"] == "pk-test"
    assert captured["secret_key"] == "sk-langfuse"
    assert captured["host"] == "https://langfuse.example.com"
    assert captured["session_id"] == "conv-1"
    assert captured["user_id"] == "chat-1"
    assert captured["trace_name"] == "agent.turn"
    assert app.last_config["callbacks"] == [fake_handler]
    assert app.last_config["metadata"]["conversation_id"] == "conv-1"
    assert app.last_config["metadata"]["chat_id"] == "chat-1"
    assert app.last_config["metadata"]["model"] == agent_obj.model
    assert app.last_config["metadata"]["runtime_context"]["current_time"] == "2026-03-20T10:00:00"


@pytest.mark.asyncio
async def test_run_skips_langfuse_when_disabled(monkeypatch, tmp_path):
    app = CaptureApp()
    call_count = {"n": 0}

    def fake_handler_builder(**kwargs):
        del kwargs
        call_count["n"] += 1
        return object()

    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: app)
    monkeypatch.setattr(agent_module, "_build_langfuse_handler", fake_handler_builder, raising=False)

    agent_obj = agent_module.LangGraphAgent(
        config=AgentConfig(api_key="sk-test", langfuse_enabled=False),
        workspaces_dir=tmp_path / "workspaces",
        skills_dir=tmp_path / "skills",
        scheduler_store=None,
    )

    await agent_obj.run(
        RunRequest(
            text="hello",
            conversation_id="conv-2",
            chat_id="chat-2",
        )
    )

    assert call_count["n"] == 0
    assert app.last_config is None


def test_build_langfuse_handler_initializes_client(monkeypatch):
    captured: dict[str, object] = {}

    class FakeLangfuse:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

    class FakeCallbackHandler:
        def __init__(self, **kwargs):
            captured["handler_kwargs"] = kwargs

    monkeypatch.setitem(sys.modules, "langfuse", SimpleNamespace(Langfuse=FakeLangfuse))
    monkeypatch.setitem(
        sys.modules,
        "langfuse.langchain",
        SimpleNamespace(CallbackHandler=FakeCallbackHandler),
    )

    handler = agent_module._build_langfuse_handler(
        public_key="pk-test",
        secret_key="sk-test",
        host="http://localhost:3000",
        session_id="conv-1",
        user_id="chat-1",
        trace_name="agent.turn",
        metadata={"conversation_id": "conv-1"},
    )

    assert isinstance(handler, FakeCallbackHandler)
    assert captured["client_kwargs"] == {
        "public_key": "pk-test",
        "secret_key": "sk-test",
        "host": "http://localhost:3000",
    }
    assert captured["handler_kwargs"]["public_key"] == "pk-test"
