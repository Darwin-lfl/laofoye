from __future__ import annotations

import asyncio

import pytest

from gateway.cli import CliGateway


@pytest.mark.asyncio
async def test_cli_gateway_handles_keyboard_interrupt(monkeypatch):
    gateway = CliGateway(default_chat_id="local")

    async def fake_to_thread(_func, _prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    called = {"count": 0}

    async def handler(msg, reply, stream_handler=None):
        called["count"] += 1

    await gateway.start(handler)

    assert called["count"] == 0


@pytest.mark.asyncio
async def test_cli_gateway_handles_eof(monkeypatch):
    gateway = CliGateway(default_chat_id="local")

    async def fake_to_thread(_func, _prompt):
        raise EOFError

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    async def handler(msg, reply, stream_handler=None):
        raise AssertionError("handler should not be called")

    await gateway.start(handler)
