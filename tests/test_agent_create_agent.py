from __future__ import annotations

from dataclasses import dataclass

import agent as agent_module
from config import AgentConfig
from langchain_core.messages import AIMessage


class DummyChatModel:
    def __init__(
        self,
        model: str,
        temperature: int,
        api_key: str,
        base_url: str | None = None,
    ):
        self.model = model
        self.temperature = temperature
        self.api_key = api_key
        self.base_url = base_url


@dataclass
class Capture:
    called: bool = False
    model: object | None = None
    tools_count: int = 0


class DummyApp:
    async def ainvoke(self, payload, config=None):
        del config
        return {"messages": [AIMessage(content="ok")]}


def test_langgraph_agent_uses_create_agent(monkeypatch, tmp_path):
    cap = Capture()

    def fake_create_agent(*, model, tools, system_prompt):
        cap.called = True
        cap.model = model
        cap.tools_count = len(tools)
        return DummyApp()

    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", fake_create_agent)

    agent_obj = agent_module.LangGraphAgent(
        config=AgentConfig(api_key="sk-test", base_url="https://api.example.com/v1"),
        workspaces_dir=tmp_path / "workspaces",
        skills_dir=tmp_path / "skills",
        scheduler_store=None,
    )

    assert cap.called is True
    assert cap.model is agent_obj._model
    assert cap.tools_count > 0
    assert agent_obj._model.api_key == "sk-test"
    assert agent_obj._model.base_url == "https://api.example.com/v1"
