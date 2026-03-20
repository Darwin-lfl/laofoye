from __future__ import annotations

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


def _build_agent(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: DummyApp())
    return agent_module.LangGraphAgent(
        config=AgentConfig(api_key="sk-test"),
        workspaces_dir=tmp_path / "workspaces",
        skills_dir=tmp_path / "skills",
        scheduler_store=None,
    )


def test_toolset_contains_terminal_python_and_file_ops(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    names = {tool.name for tool in agent_obj._tools}

    assert "terminal" in names
    assert "python_repl" in names
    assert "read_file" in names
    assert "write_file" in names
    assert "list_files" in names
    assert "glob_files" in names
    assert "web_search" in names
    assert "web_fetch" in names


def test_terminal_runs_in_workspace(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    workspace = agent_obj._prepare_workspace("local")
    token = agent_obj._workspace_var.set(workspace)
    try:
        terminal_tool = next(tool for tool in agent_obj._tools if tool.name == "terminal")
        result = terminal_tool.invoke({"command": "pwd"})
    finally:
        agent_obj._workspace_var.reset(token)

    assert str(workspace) in result


def test_python_repl_persists_state_per_workspace(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    workspace = agent_obj._prepare_workspace("local")
    token = agent_obj._workspace_var.set(workspace)
    try:
        py_tool = next(tool for tool in agent_obj._tools if tool.name == "python_repl")
        py_tool.invoke({"code": "x = 7"})
        result = py_tool.invoke({"code": "x * 3"})
    finally:
        agent_obj._workspace_var.reset(token)

    assert "21" in result


def test_python_repl_supports_statement_then_expression(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    workspace = agent_obj._prepare_workspace("local")
    token = agent_obj._workspace_var.set(workspace)
    try:
        py_tool = next(tool for tool in agent_obj._tools if tool.name == "python_repl")
        first = py_tool.invoke({"code": "import math"})
        second = py_tool.invoke({"code": "math.sqrt(16)"})
    finally:
        agent_obj._workspace_var.reset(token)

    assert first == "OK"
    assert "4.0" in second


def test_python_repl_exec_error_does_not_include_chained_eval_syntaxerror(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    workspace = agent_obj._prepare_workspace("local")
    token = agent_obj._workspace_var.set(workspace)
    try:
        py_tool = next(tool for tool in agent_obj._tools if tool.name == "python_repl")
        err = py_tool.invoke({"code": "d = {}\nd['missing']"})
    finally:
        agent_obj._workspace_var.reset(token)

    assert "KeyError" in err
    assert "During handling of the above exception" not in err


def test_file_tools_enforce_workspace_boundary(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    workspace = agent_obj._prepare_workspace("local")
    token = agent_obj._workspace_var.set(workspace)
    try:
        write_tool = next(tool for tool in agent_obj._tools if tool.name == "write_file")
        read_tool = next(tool for tool in agent_obj._tools if tool.name == "read_file")

        ok = write_tool.invoke({"path": "notes/a.txt", "content": "hello"})
        content = read_tool.invoke({"path": "notes/a.txt"})
        blocked = write_tool.invoke({"path": "../escape.txt", "content": "nope"})
    finally:
        agent_obj._workspace_var.reset(token)

    assert "Wrote" in ok
    assert "hello" in content
    assert "outside workspace" in blocked.lower()


def test_read_file_allows_absolute_path_in_skills_dir(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    workspace = agent_obj._prepare_workspace("local")
    skill_file = tmp_path / "skills" / "demo" / "EXTEND.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text("skill extension", encoding="utf-8")

    token = agent_obj._workspace_var.set(workspace)
    try:
        read_tool = next(tool for tool in agent_obj._tools if tool.name == "read_file")
        content = read_tool.invoke({"path": str(skill_file)})
    finally:
        agent_obj._workspace_var.reset(token)

    assert "skill extension" in content
