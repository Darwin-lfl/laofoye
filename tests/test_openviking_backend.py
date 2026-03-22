from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from config import AgentConfig


class FakeTextPart:
    def __init__(self, *, text: str):
        self.text = text


class FakeSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: list[tuple[str, list[FakeTextPart]]] = []
        self.used_contexts: list[list[str]] = []
        self.commit_count = 0
        self.load_count = 0

    def load(self):
        self.load_count += 1
        return {"session_id": self.session_id}

    def add_message(self, role: str, parts: list[FakeTextPart]) -> None:
        self.messages.append((role, parts))

    def used(self, *, contexts=None, skill=None):
        del skill
        if contexts:
            self.used_contexts.append(list(contexts))

    def commit(self):
        self.commit_count += 1
        return {"status": "ok"}


class FakeOpenVikingClient:
    def __init__(self, *, path):
        self.path = path
        self.initialized = False
        self.closed = False
        self.removed: list[tuple[str, bool]] = []
        self.sessions: dict[str, FakeSession] = {}
        self.find_calls: list[tuple[str, str, int]] = []

    def initialize(self) -> None:
        self.initialized = True

    def close(self) -> None:
        self.closed = True

    def session(self, session_id=None):
        sid = session_id or "auto-generated"
        self.sessions.setdefault(sid, FakeSession(sid))
        return self.sessions[sid]

    def search(self, query: str, *, session, limit: int = 10):
        del query, session, limit
        hit = SimpleNamespace(
            uri="viking://user/memories/prefs/writing-style",
            abstract="User prefers concise Chinese responses.",
            score=0.93,
            context_type="memory",
        )
        return SimpleNamespace(memories=[hit], resources=[], skills=[])

    def find(self, query: str, target_uri: str = "", limit: int = 10):
        self.find_calls.append((query, target_uri, limit))
        hit = SimpleNamespace(
            uri="viking://user/memories/prefs/tooling",
            abstract="User likes direct technical guidance.",
            score=0.88,
            context_type="memory",
        )
        return SimpleNamespace(memories=[hit], resources=[], skills=[])

    def rm(self, uri: str, recursive: bool = False):
        self.removed.append((uri, recursive))


@pytest.fixture
def fake_openviking_modules(monkeypatch):
    import sys

    monkeypatch.setitem(
        sys.modules,
        "openviking",
        SimpleNamespace(OpenViking=FakeOpenVikingClient),
    )
    monkeypatch.setitem(
        sys.modules,
        "openviking.message",
        SimpleNamespace(TextPart=FakeTextPart),
    )


def test_build_memory_backend_returns_noop_when_disabled(tmp_path):
    from memory.backend import NoopMemoryBackend
    from memory.openviking_backend import build_memory_backend

    backend = build_memory_backend(
        config=AgentConfig(api_key="sk-test", openviking_enabled=False),
        workspaces_dir=tmp_path,
    )
    assert isinstance(backend, NoopMemoryBackend)


def test_build_memory_backend_resolves_relative_openviking_config_file(
    fake_openviking_modules,
    tmp_path,
    monkeypatch,
):
    import memory.openviking_backend as ov_backend

    monkeypatch.setattr(ov_backend, "project_root", lambda: tmp_path)
    (tmp_path / "ov.conf").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("OPENVIKING_CONFIG_FILE", "./ov.conf")

    backend = ov_backend.build_memory_backend(
        config=AgentConfig(api_key="sk-test", openviking_enabled=True),
        workspaces_dir=tmp_path / "workspaces",
    )

    assert os.environ["OPENVIKING_CONFIG_FILE"] == str((tmp_path / "ov.conf").resolve())
    backend.close()


def test_openviking_backend_search_and_record_turn(fake_openviking_modules, tmp_path):
    from memory.openviking_backend import OpenVikingMemoryBackend

    backend = OpenVikingMemoryBackend(
        path=tmp_path / "ov-data",
        search_limit=5,
        commit_every_turn=True,
    )
    context = backend.build_context(
        conversation_id="local",
        query="请记住我的偏好",
        limit=2,
    )

    assert "## Retrieved Context (OpenViking)" in context
    assert "viking://user/memories/prefs/writing-style" in context
    assert "concise Chinese responses" in context

    backend.record_turn(
        conversation_id="local",
        user_text="请记住我的偏好",
        response_text="我记住了",
        tools=["web_search"],
    )

    session = backend._client.sessions["local"]
    assert len(session.messages) == 2
    assert session.messages[0][0] == "user"
    assert session.messages[1][0] == "assistant"
    assert session.used_contexts == [["viking://user/memories/prefs/writing-style"]]
    assert session.commit_count == 1
    assert session.load_count >= 2


def test_openviking_backend_supports_manual_memory_and_clear(
    fake_openviking_modules,
    tmp_path,
):
    from memory.openviking_backend import OpenVikingMemoryBackend

    backend = OpenVikingMemoryBackend(
        path=tmp_path / "ov-data",
        search_limit=5,
        commit_every_turn=True,
    )
    backend.save_memory(conversation_id="local", content="用户偏好: 中文、简洁")
    session = backend._client.sessions["local"]
    assert session.messages[-1][0] == "assistant"
    assert "Memory Snapshot" in session.messages[-1][1][0].text
    assert session.commit_count == 1
    assert session.load_count >= 1

    backend.clear_conversation("local")
    assert ("viking://session/local/", True) in backend._client.removed

    backend.close()
    assert backend._client.closed is True


def test_openviking_backend_search_falls_back_to_find_on_search_error(
    fake_openviking_modules,
    tmp_path,
):
    from memory.openviking_backend import OpenVikingMemoryBackend

    backend = OpenVikingMemoryBackend(
        path=tmp_path / "ov-data",
        search_limit=5,
        commit_every_turn=True,
    )

    def broken_search(*_args, **_kwargs):
        raise RuntimeError("search pipeline unavailable")

    backend._client.search = broken_search

    hits = backend.search(
        conversation_id="local",
        query="请回忆我的偏好",
        limit=3,
    )

    assert hits
    assert hits[0].uri == "viking://user/memories/prefs/tooling"
    assert backend._client.sessions["local"].load_count >= 1


def test_openviking_backend_search_falls_back_to_find_on_empty_search_results(
    fake_openviking_modules,
    tmp_path,
):
    from memory.openviking_backend import OpenVikingMemoryBackend

    backend = OpenVikingMemoryBackend(
        path=tmp_path / "ov-data",
        search_limit=5,
        commit_every_turn=True,
    )

    def empty_search(*_args, **_kwargs):
        return SimpleNamespace(memories=[], resources=[], skills=[])

    backend._client.search = empty_search

    hits = backend.search(
        conversation_id="local",
        query="请回忆我的偏好",
        limit=3,
    )

    assert hits
    assert hits[0].uri == "viking://user/memories/prefs/tooling"
    assert backend._client.sessions["local"].load_count >= 1
    assert backend._client.find_calls[0][1] == "viking://session/default/local"


def test_openviking_backend_search_returns_session_context_when_no_hits(
    fake_openviking_modules,
    tmp_path,
):
    from memory.openviking_backend import OpenVikingMemoryBackend

    backend = OpenVikingMemoryBackend(
        path=tmp_path / "ov-data",
        search_limit=5,
        commit_every_turn=True,
    )

    backend._client.search = (
        lambda *_args, **_kwargs: SimpleNamespace(
            memories=[],
            resources=[],
            skills=[],
            query_plan=SimpleNamespace(
                queries=[],
                session_context="Session summary: user asked 南京今天天气如何 and assistant answered.",
            ),
            query_results=[],
            total=0,
        )
    )
    backend._client.find = lambda *_args, **_kwargs: SimpleNamespace(
        memories=[],
        resources=[],
        skills=[],
    )

    hits = backend.search(
        conversation_id="local",
        query="南京今天天气",
        limit=3,
    )

    assert len(hits) == 1
    assert hits[0].context_type == "session_context"
    assert hits[0].uri == "viking://session/default/local"
    assert "Session summary" in hits[0].abstract


def test_openviking_backend_search_falls_back_to_archive_messages(
    fake_openviking_modules,
    tmp_path,
):
    from memory.openviking_backend import OpenVikingMemoryBackend

    backend = OpenVikingMemoryBackend(
        path=tmp_path / "ov-data",
        search_limit=5,
        commit_every_turn=True,
    )

    archive_dir = (
        tmp_path
        / "ov-data"
        / "viking"
        / "default"
        / "session"
        / "default"
        / "local"
        / "history"
        / "archive_001"
    )
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "messages.jsonl").write_text(
        "\n".join(
            [
                '{"role":"user","parts":[{"type":"text","text":"南京今天天气"}]}',
                '{"role":"assistant","parts":[{"type":"text","text":"南京今日气温9到17度，晴转多云"}]}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    backend._client.search = (
        lambda *_args, **_kwargs: SimpleNamespace(
            memories=[],
            resources=[],
            skills=[],
            query_plan=SimpleNamespace(queries=[], session_context=""),
            query_results=[],
            total=0,
        )
    )
    backend._client.find = lambda *_args, **_kwargs: SimpleNamespace(
        memories=[],
        resources=[],
        skills=[],
    )

    hits = backend.search(
        conversation_id="local",
        query="南京今天的天气",
        limit=3,
    )

    assert hits
    assert hits[0].context_type == "archive"
    assert "archive_001/messages.jsonl" in hits[0].uri
    assert "南京今日气温" in hits[0].abstract
