from __future__ import annotations

import json

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


def _build_agent(monkeypatch, tmp_path, config: AgentConfig | None = None):
    monkeypatch.setattr(agent_module, "ChatOpenAI", DummyChatModel)
    monkeypatch.setattr(agent_module, "create_agent", lambda **kwargs: DummyApp())
    return agent_module.LangGraphAgent(
        config=config or AgentConfig(api_key="sk-test"),
        workspaces_dir=tmp_path / "workspaces",
        skills_dir=tmp_path / "skills",
        scheduler_store=None,
    )


def test_web_search_tool_uses_duckduckgo_payload(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    workspace = agent_obj._prepare_workspace("local")

    payload = {
        "AbstractURL": "https://example.com/overview",
        "AbstractText": "TypeScript best practices overview.",
        "Heading": "TypeScript",
        "RelatedTopics": [
            {
                "FirstURL": "https://example.com/topic-1",
                "Text": "Generics - details about generics",
            },
            {
                "Topics": [
                    {
                        "FirstURL": "https://example.com/topic-2",
                        "Text": "TSConfig - compiler options",
                    }
                ]
            },
        ],
    }
    monkeypatch.setattr(agent_module, "_urlopen_text", lambda *_args, **_kwargs: json.dumps(payload))

    token = agent_obj._workspace_var.set(workspace)
    try:
        tool = next(t for t in agent_obj._tools if t.name == "web_search")
        out = tool.invoke({"query": "TypeScript best practices", "count": 3})
    finally:
        agent_obj._workspace_var.reset(token)

    assert "Results for: TypeScript best practices" in out
    assert "https://example.com/overview" in out
    assert "Generics" in out
    assert "TSConfig" in out


def test_web_fetch_tool_prefers_reader_endpoint(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    workspace = agent_obj._prepare_workspace("local")

    def fake_urlopen_raw(url: str, **_kwargs):
        assert url.startswith("https://r.jina.ai/https://")
        return "Reader cleaned content", 200, "https://example.com", "text/plain"

    monkeypatch.setattr(agent_module, "_urlopen_raw", fake_urlopen_raw)

    token = agent_obj._workspace_var.set(workspace)
    try:
        tool = next(t for t in agent_obj._tools if t.name == "web_fetch")
        out = tool.invoke({"url": "https://example.com"})
    finally:
        agent_obj._workspace_var.reset(token)

    parsed = json.loads(out)
    assert parsed["extractor"] == "jina"
    assert parsed["untrusted"] is True
    assert "Reader cleaned content" in parsed["text"]


def test_web_fetch_tool_falls_back_to_direct_html(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    workspace = agent_obj._prepare_workspace("local")

    def fake_urlopen_raw(url: str, **_kwargs):
        if url.startswith("https://r.jina.ai/"):
            raise RuntimeError("reader unavailable")
        return (
            "<html><head><title>T</title></head><body><h1>Hello</h1><p>World</p></body></html>",
            200,
            "https://example.com",
            "text/html; charset=utf-8",
        )

    monkeypatch.setattr(agent_module, "_urlopen_raw", fake_urlopen_raw)

    token = agent_obj._workspace_var.set(workspace)
    try:
        tool = next(t for t in agent_obj._tools if t.name == "web_fetch")
        out = tool.invoke({"url": "example.com"})
    finally:
        agent_obj._workspace_var.reset(token)

    parsed = json.loads(out)
    assert parsed["extractor"] == "readability"
    assert parsed["untrusted"] is True
    assert "<h1>" not in parsed["text"]
    assert "Hello" in parsed["text"]
    assert "World" in parsed["text"]


def test_web_fetch_tool_encodes_non_ascii_url_for_fallback(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    workspace = agent_obj._prepare_workspace("local")
    captured: dict[str, str] = {}

    monkeypatch.setattr(agent_module, "_fetch_jina_reader", lambda *_args, **_kwargs: None)

    def fake_urlopen_raw(url: str, **_kwargs):
        captured["url"] = url
        return ('{"temp_c":12}', 200, url, "application/json; charset=utf-8")

    monkeypatch.setattr(agent_module, "_urlopen_raw", fake_urlopen_raw)

    token = agent_obj._workspace_var.set(workspace)
    try:
        tool = next(t for t in agent_obj._tools if t.name == "web_fetch")
        out = tool.invoke({"url": "https://wttr.in/南京?format=j1", "extractMode": "text"})
    finally:
        agent_obj._workspace_var.reset(token)

    parsed = json.loads(out)
    assert parsed["extractor"] == "json"
    assert captured["url"] == "https://wttr.in/%E5%8D%97%E4%BA%AC?format=j1"


def test_web_fetch_tool_falls_back_when_jina_returns_null_like_payload(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    workspace = agent_obj._prepare_workspace("local")
    captured: dict[str, str] = {}

    def fake_urlopen_raw(url: str, **_kwargs):
        if url.startswith("https://r.jina.ai/"):
            # Broken reader payload that previously leaked as extractor=jina/text=null.
            return ("null<!--broken-->", 200, url, "application/json; charset=utf-8")
        captured["url"] = url
        return ('{"temp_c":12}', 200, url, "application/json; charset=utf-8")

    monkeypatch.setattr(agent_module, "_urlopen_raw", fake_urlopen_raw)

    token = agent_obj._workspace_var.set(workspace)
    try:
        tool = next(t for t in agent_obj._tools if t.name == "web_fetch")
        out = tool.invoke({"url": "https://wttr.in/南京?format=j1", "extractMode": "text"})
    finally:
        agent_obj._workspace_var.reset(token)

    parsed = json.loads(out)
    assert parsed["extractor"] == "json"
    assert captured["url"] == "https://wttr.in/%E5%8D%97%E4%BA%AC?format=j1"


def test_web_fetch_tool_uses_open_meteo_when_wttr_capacity_exceeded(monkeypatch, tmp_path):
    agent_obj = _build_agent(monkeypatch, tmp_path)
    workspace = agent_obj._prepare_workspace("local")

    def fake_urlopen_raw(url: str, **_kwargs):
        if url.startswith("https://r.jina.ai/https://wttr.in/"):
            return (
                "Sorry, we processed more than 1M requests today and we ran out of our datasource capacity.",
                200,
                url,
                "text/plain; charset=utf-8",
            )
        if url.startswith("https://geocoding-api.open-meteo.com/v1/search"):
            return (
                '{"results":[{"name":"Nanjing","latitude":32.06,"longitude":118.78}]}',
                200,
                url,
                "application/json; charset=utf-8",
            )
        if url.startswith("https://api.open-meteo.com/v1/forecast"):
            return (
                '{"current":{"temperature_2m":19.2,"relative_humidity_2m":44,"apparent_temperature":18.7,"wind_speed_10m":11.1,"weather_code":1},'
                '"daily":{"weather_code":[1],"temperature_2m_max":[21.0],"temperature_2m_min":[12.0]}}',
                200,
                url,
                "application/json; charset=utf-8",
            )
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(agent_module, "_urlopen_raw", fake_urlopen_raw)

    token = agent_obj._workspace_var.set(workspace)
    try:
        tool = next(t for t in agent_obj._tools if t.name == "web_fetch")
        out = tool.invoke({"url": "https://wttr.in/南京"})
    finally:
        agent_obj._workspace_var.reset(token)

    parsed = json.loads(out)
    assert parsed["extractor"] == "open-meteo-fallback"
    assert "Nanjing天气" in parsed["text"]
    assert "当前温度：19.2" in parsed["text"]


def test_web_search_tool_reads_provider_from_agent_config(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_search_web(query, n, provider, *, api_key="", base_url=""):
        captured["query"] = query
        captured["n"] = n
        captured["provider"] = provider
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        return "ok"

    monkeypatch.setattr(agent_module, "_search_web", fake_search_web)
    config = AgentConfig(
        api_key="sk-test",
        web_search_provider="searxng",
        web_search_api_key="search-key",
        web_search_base_url="https://searxng.example.com",
    )
    agent_obj = _build_agent(monkeypatch, tmp_path, config=config)
    workspace = agent_obj._prepare_workspace("local")

    token = agent_obj._workspace_var.set(workspace)
    try:
        tool = next(t for t in agent_obj._tools if t.name == "web_search")
        out = tool.invoke({"query": "agent frameworks", "count": 4})
    finally:
        agent_obj._workspace_var.reset(token)

    assert out == "ok"
    assert captured["query"] == "agent frameworks"
    assert captured["n"] == 4
    assert captured["provider"] == "searxng"
    assert captured["api_key"] == "search-key"
    assert captured["base_url"] == "https://searxng.example.com"


def test_web_fetch_tool_reads_jina_key_from_agent_config(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_fetch_jina(url: str, max_chars: int, jina_api_key: str = "") -> str | None:
        captured["url"] = url
        captured["max_chars"] = max_chars
        captured["jina_api_key"] = jina_api_key
        return json.dumps({"extractor": "jina", "text": "ok"}, ensure_ascii=False)

    monkeypatch.setattr(agent_module, "_fetch_jina_reader", fake_fetch_jina)
    config = AgentConfig(api_key="sk-test", web_fetch_jina_api_key="jina-secret")
    agent_obj = _build_agent(monkeypatch, tmp_path, config=config)
    workspace = agent_obj._prepare_workspace("local")

    token = agent_obj._workspace_var.set(workspace)
    try:
        tool = next(t for t in agent_obj._tools if t.name == "web_fetch")
        out = tool.invoke({"url": "https://example.com", "maxChars": 3210})
    finally:
        agent_obj._workspace_var.reset(token)

    assert "jina" in out
    assert captured["url"] == "https://example.com"
    assert captured["max_chars"] == 3210
    assert captured["jina_api_key"] == "jina-secret"
