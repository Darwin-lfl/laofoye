from __future__ import annotations

from textwrap import dedent

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
    async def ainvoke(self, payload, config=None):
        del config
        return {"messages": [AIMessage(content="ok")]}


def test_prepare_workspace_does_not_create_claude_skills_link(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: DummyApp())

    workspaces_dir = tmp_path / "workspaces"
    skills_dir = tmp_path / "skills"

    agent_obj = agent_module.LangGraphAgent(
        config=AgentConfig(api_key="sk-test"),
        workspaces_dir=workspaces_dir,
        skills_dir=skills_dir,
        scheduler_store=None,
    )

    resolved = agent_obj._prepare_workspace("local")

    assert resolved == workspaces_dir / "local"
    assert not (resolved / ".claude").exists()


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
    prompt = agent_obj._build_system_prompt(workspace)

    assert "agent-rules" in prompt
    assert "soul-style" in prompt
    assert "identity-info" in prompt
    assert "user-profile" in prompt


def test_build_system_prompt_wraps_sections_into_stable_modules(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: DummyApp())

    skills_dir = tmp_path / "skills"
    (skills_dir / "my-skill").mkdir(parents=True, exist_ok=True)
    (skills_dir / "my-skill" / "SKILL.md").write_text(
        "---\n"
        "name: my-skill\n"
        "description: concise bullet helper\n"
        "---\n",
        encoding="utf-8",
    )

    agent_obj = agent_module.LangGraphAgent(
        config=AgentConfig(api_key="sk-test"),
        workspaces_dir=tmp_path / "workspaces",
        skills_dir=skills_dir,
        scheduler_store=None,
    )
    workspace = agent_obj._prepare_workspace("local")
    (workspace / "AGENTS.md").write_text("## Session Checklist\n- do x", encoding="utf-8")
    (workspace / "SOUL.md").write_text("## Persona\n- demo", encoding="utf-8")
    (workspace / "IDENTITY.md").write_text("## Name\n- test", encoding="utf-8")
    (workspace / "USER.md").write_text("## User\n- profile", encoding="utf-8")

    prompt = agent_obj._build_system_prompt(workspace)

    assert prompt.startswith("# System Instructions\n\n")
    assert '<module id="core.system" kind="instruction" source="base_prompt" priority="10">' in prompt
    assert '<module id="profile.agents" kind="profile" source="AGENTS.md" priority="20">' in prompt
    assert '<module id="profile.soul" kind="profile" source="SOUL.md" priority="30">' in prompt
    assert '<module id="profile.identity" kind="profile" source="IDENTITY.md" priority="40">' in prompt
    assert '<module id="profile.user" kind="profile" source="USER.md" priority="50">' in prompt
    assert '<module id="skills.catalog" kind="catalog" source="skills_dir" priority="90">' in prompt
    assert "## Workspace Profile" not in prompt

    idx_core = prompt.index('id="core.system"')
    idx_agents = prompt.index('id="profile.agents"')
    idx_soul = prompt.index('id="profile.soul"')
    idx_identity = prompt.index('id="profile.identity"')
    idx_user = prompt.index('id="profile.user"')
    idx_skills = prompt.index('id="skills.catalog"')
    assert idx_core < idx_agents < idx_soul < idx_identity < idx_user < idx_skills


def test_build_system_prompt_snapshot_is_stable(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: DummyApp())

    skills_dir = tmp_path / "skills"
    (skills_dir / "z-skill").mkdir(parents=True, exist_ok=True)
    (skills_dir / "z-skill" / "SKILL.md").write_text(
        "---\n"
        "name: z-skill\n"
        "description: skill z description\n"
        "---\n",
        encoding="utf-8",
    )
    (skills_dir / "a-skill").mkdir(parents=True, exist_ok=True)
    (skills_dir / "a-skill" / "SKILL.md").write_text(
        "---\n"
        "name: a-skill\n"
        "description: skill a description\n"
        "---\n",
        encoding="utf-8",
    )

    agent_obj = agent_module.LangGraphAgent(
        config=AgentConfig(
            api_key="sk-test",
            system_prompt="You are test assistant.\n\n## Constraints\n- Keep concise.",
        ),
        workspaces_dir=tmp_path / "workspaces",
        skills_dir=skills_dir,
        scheduler_store=None,
    )
    workspace = agent_obj._prepare_workspace("local")
    (workspace / "AGENTS.md").write_text(
        dedent(
            """
            ## Session Checklist
            1. Read A

            ## Working Rules
            - Keep explicit.
            """
        ).strip(),
        encoding="utf-8",
    )
    (workspace / "SOUL.md").write_text("## Persona\n- direct", encoding="utf-8")
    (workspace / "IDENTITY.md").write_text("## Name\n- 老佛爷", encoding="utf-8")
    (workspace / "USER.md").write_text("## Preferred language\n- 中文", encoding="utf-8")

    prompt = agent_obj._build_system_prompt(workspace)

    expected = dedent(
        f"""
        # System Instructions

        <module id="core.system" kind="instruction" source="base_prompt" priority="10">
        ## System Persona
        You are test assistant.

        ### Constraints
        - Keep concise.
        </module>

        <module id="profile.agents" kind="profile" source="AGENTS.md" priority="20">
        ## Operating Playbook
        ### Session Checklist
        1. Read A

        ### Working Rules
        - Keep explicit.
        </module>

        <module id="profile.soul" kind="profile" source="SOUL.md" priority="30">
        ## Soul Profile
        ### Persona
        - direct
        </module>

        <module id="profile.identity" kind="profile" source="IDENTITY.md" priority="40">
        ## Identity Card
        ### Name
        - 老佛爷
        </module>

        <module id="profile.user" kind="profile" source="USER.md" priority="50">
        ## User Profile
        ### Preferred language
        - 中文
        </module>

        <module id="skills.catalog" kind="catalog" source="skills_dir" priority="90">
        ## Skills Catalog
        Use skills by name and load full details only when needed via `skill_read`.
        <available_skills>
          <skill>
            <name>a-skill</name>
            <description>skill a description</description>
            <location>{skills_dir / "a-skill" / "SKILL.md"}</location>
          </skill>
          <skill>
            <name>z-skill</name>
            <description>skill z description</description>
            <location>{skills_dir / "z-skill" / "SKILL.md"}</location>
          </skill>
        </available_skills>
        </module>
        """
    ).strip()

    assert prompt == expected


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


def test_build_system_prompt_ignores_workspace_local_skill_links(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: DummyApp())

    workspaces_dir = tmp_path / "workspaces"
    skills_dir = tmp_path / "skills"
    (skills_dir / "demo").mkdir(parents=True, exist_ok=True)
    (skills_dir / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: demo skill\n---\n",
        encoding="utf-8",
    )

    ws_claude_skills = workspaces_dir / "local" / ".claude" / "skills" / "bogus"
    ws_claude_skills.mkdir(parents=True, exist_ok=True)
    (ws_claude_skills / "SKILL.md").write_text(
        "---\nname: bogus\ndescription: should be ignored\n---\n",
        encoding="utf-8",
    )

    agent_obj = agent_module.LangGraphAgent(
        config=AgentConfig(api_key="sk-test"),
        workspaces_dir=workspaces_dir,
        skills_dir=skills_dir,
        scheduler_store=None,
    )

    workspace = agent_obj._prepare_workspace("local")
    prompt = agent_obj._build_system_prompt(workspace)

    assert "<name>demo</name>" in prompt
    assert "<name>bogus</name>" not in prompt


def test_extract_skill_metadata_parses_yaml_folded_description(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: DummyApp())

    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "daily-hunt"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\n"
        "name: daily-hunt\n"
        "description: >\n"
        "  Daily tech digest with Product Hunt and GitHub Trending.\n"
        "  Includes colon content: keep this sentence.\n"
        "---\n"
        "\n"
        "# Daily Hunt\n"
        "Body text.\n",
        encoding="utf-8",
    )

    agent_obj = agent_module.LangGraphAgent(
        config=AgentConfig(api_key="sk-test"),
        workspaces_dir=tmp_path / "workspaces",
        skills_dir=skills_dir,
        scheduler_store=None,
    )

    name, description = agent_obj._extract_skill_metadata("fallback", skill_file)
    assert name == "daily-hunt"
    assert "Daily tech digest with Product Hunt and GitHub Trending." in description
    assert "Includes colon content: keep this sentence." in description
