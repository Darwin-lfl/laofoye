from __future__ import annotations

import os

import agent as agent_module
from config import AgentConfig
from langchain_core.messages import AIMessage


class DummyChatModel:
    def __init__(self, model: str, temperature: int, api_key: str, base_url: str | None = None):
        self.model = model
        self.temperature = temperature
        self.api_key = api_key
        self.base_url = base_url


class DummyApp:
    async def ainvoke(self, payload):
        return {"messages": [AIMessage(content="ok")]}


def test_prepare_workspace_handles_broken_skills_symlink(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: DummyApp())

    workspaces_dir = tmp_path / "workspaces"
    skills_dir = tmp_path / "skills"

    ws = workspaces_dir / "local" / ".claude"
    ws.mkdir(parents=True, exist_ok=True)
    broken_target = tmp_path / "missing-skills-target"
    skills_link = ws / "skills"
    skills_link.symlink_to(broken_target, target_is_directory=True)

    agent_obj = agent_module.LangGraphAgent(
        config=AgentConfig(api_key="sk-test"),
        workspaces_dir=workspaces_dir,
        skills_dir=skills_dir,
        scheduler_store=None,
    )

    resolved = agent_obj._prepare_workspace("local")

    assert resolved == workspaces_dir / "local"
    assert skills_link.is_symlink()


def test_build_system_prompt_includes_workspace_identity_files(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: DummyApp())

    agent_obj = agent_module.LangGraphAgent(
        config=AgentConfig(api_key="sk-test"),
        workspaces_dir=tmp_path / "workspaces",
        skills_dir=tmp_path / "skills",
        scheduler_store=None,
    )

    workspace = agent_obj._prepare_workspace("local")
    (workspace / "AGENTS.md").write_text("agent-rules", encoding="utf-8")
    (workspace / "SOUL.md").write_text("soul-style", encoding="utf-8")
    (workspace / "IDENTITY.md").write_text("identity-info", encoding="utf-8")
    (workspace / "USER.md").write_text("user-profile", encoding="utf-8")
    (workspace / "MEMORY.md").write_text("long-memory", encoding="utf-8")

    prompt = agent_obj._build_system_prompt(workspace)

    assert "agent-rules" in prompt
    assert "soul-style" in prompt
    assert "identity-info" in prompt
    assert "user-profile" in prompt
    assert "long-memory" in prompt


def test_build_system_prompt_includes_dynamic_skills(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: DummyApp())

    skills_dir = tmp_path / "skills"
    (skills_dir / "my-skill").mkdir(parents=True, exist_ok=True)
    (skills_dir / "my-skill" / "SKILL.md").write_text(
        "---\n"
        "name: my-skill\n"
        "description: concise bullet helper\n"
        "---\n"
        "\n"
        "# my-skill\n"
        "DO_NOT_INLINE_FULL_SKILL_BODY\n",
        encoding="utf-8",
    )

    agent_obj = agent_module.LangGraphAgent(
        config=AgentConfig(api_key="sk-test"),
        workspaces_dir=tmp_path / "workspaces",
        skills_dir=skills_dir,
        scheduler_store=None,
    )

    workspace = agent_obj._prepare_workspace("local")
    prompt = agent_obj._build_system_prompt(workspace)

    assert "## Skills Catalog" in prompt
    assert "<available_skills>" in prompt
    assert "<name>my-skill</name>" in prompt
    assert "<description>concise bullet helper</description>" in prompt
    assert "DO_NOT_INLINE_FULL_SKILL_BODY" not in prompt


def test_skill_read_tool_loads_full_skill_on_demand(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: DummyApp())

    skills_dir = tmp_path / "skills"
    (skills_dir / "research").mkdir(parents=True, exist_ok=True)
    (skills_dir / "research" / "SKILL.md").write_text(
        "# research\nFull skill content here.\n",
        encoding="utf-8",
    )

    agent_obj = agent_module.LangGraphAgent(
        config=AgentConfig(api_key="sk-test"),
        workspaces_dir=tmp_path / "workspaces",
        skills_dir=skills_dir,
        scheduler_store=None,
    )

    skill_tool = next(tool for tool in agent_obj._tools if tool.name == "skill_read")
    result = skill_tool.invoke({"skill_name": "research"})

    assert "Full skill content here." in result


def test_prepare_workspace_repairs_relative_self_symlink(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: DummyApp())

    workspaces_dir = tmp_path / "workspaces"
    skills_dir = tmp_path / "skills"
    (skills_dir / "demo").mkdir(parents=True, exist_ok=True)
    (skills_dir / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: demo skill\n---\n",
        encoding="utf-8",
    )

    ws_claude = workspaces_dir / "local" / ".claude"
    ws_claude.mkdir(parents=True, exist_ok=True)
    bad_link = ws_claude / "skills"
    bad_link.symlink_to("skills", target_is_directory=True)

    agent_obj = agent_module.LangGraphAgent(
        config=AgentConfig(api_key="sk-test"),
        workspaces_dir=workspaces_dir,
        skills_dir=skills_dir,
        scheduler_store=None,
    )

    workspace = agent_obj._prepare_workspace("local")
    prompt = agent_obj._build_system_prompt(workspace)

    assert bad_link.is_symlink()
    target = bad_link.readlink()
    if not target.is_absolute():
        target = bad_link.parent / target
    assert os.path.abspath(str(target)) == os.path.abspath(str(skills_dir))
    assert "<name>demo</name>" in prompt
