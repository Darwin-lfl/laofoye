from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from config import FeishuGatewayConfig
from core_types import AgentStreamEvent, RunResponse
from gateway.feishu import FeishuGateway


@dataclass
class Capture:
    called: int = 0
    last_text: str = ""


class FakeApi:
    def __init__(self) -> None:
        self.reactions: list[dict[str, Any]] = []
        self.created: list[dict[str, Any]] = []
        self.replied: list[dict[str, Any]] = []
        self.converted: list[dict[str, Any]] = []
        self.streamed: list[dict[str, Any]] = []
        self.settings: list[dict[str, Any]] = []
        self.calls: list[str] = []

    def react_emoji_to(self, *, message_id: str, emoji_type_name: str) -> None:
        self.calls.append("react")
        self.reactions.append(
            {
                "message_id": message_id,
                "emoji_type_name": emoji_type_name,
            }
        )

    def create_message(self, *, chat_id: str, msg_type: str, content: str) -> str:
        self.calls.append("create")
        self.created.append(
            {
                "chat_id": chat_id,
                "msg_type": msg_type,
                "content": content,
            }
        )
        return f"om_{len(self.created)}"

    def reply_message(
        self,
        *,
        message_id: str,
        msg_type: str,
        content: str,
        reply_in_thread: bool = True,
    ) -> str:
        self.calls.append("reply")
        self.replied.append(
            {
                "message_id": message_id,
                "msg_type": msg_type,
                "content": content,
                "reply_in_thread": reply_in_thread,
            }
        )
        return f"om_reply_{len(self.replied)}"

    def id_convert_card_id(self, *, message_id: str) -> str:
        self.converted.append({"message_id": message_id})
        return f"card_{message_id}"

    def stream_card_text(
        self,
        *,
        card_id: str,
        element_id: str,
        content: str,
        sequence: int,
    ) -> None:
        self.streamed.append(
            {
                "card_id": card_id,
                "element_id": element_id,
                "content": content,
                "sequence": sequence,
            }
        )

    def update_card_settings(self, *, card_id: str, settings: str, sequence: int) -> None:
        self.settings.append(
            {
                "card_id": card_id,
                "settings": settings,
                "sequence": sequence,
            }
        )


class FakeWsClient:
    def __init__(self, callback):
        self._callback = callback
        self.started = False

    def start(self) -> None:
        self.started = True


def _ws_factory(_callback):
    return FakeWsClient(_callback)


def _sdk_event(*, message_id: str, chat_id: str, text: str, bot_open_id: str, author_open_id: str = "ou_user"):
    mention = SimpleNamespace(
        id=SimpleNamespace(open_id=bot_open_id, user_id=None, union_id=None),
        name="bot",
        key="@bot",
    )
    sender = SimpleNamespace(sender_id=SimpleNamespace(open_id=author_open_id, user_id=None, union_id=None))
    message = SimpleNamespace(
        message_id=message_id,
        chat_id=chat_id,
        chat_type="group",
        message_type="text",
        content=json.dumps({"text": text}, ensure_ascii=False),
        thread_id=None,
        mentions=[mention],
    )
    return SimpleNamespace(event=SimpleNamespace(sender=sender, message=message))


@pytest.mark.asyncio
async def test_ingest_group_message_requires_mention_or_auto_reply():
    config = FeishuGatewayConfig(app_id="id", app_secret="secret", bot_open_id="ou_bot")
    api = FakeApi()
    gateway = FeishuGateway(config=config, api=api, ws_client_factory=_ws_factory)

    capture = Capture()

    async def handler(msg, reply, stream_handler=None):
        capture.called += 1
        capture.last_text = msg.text
        await reply(RunResponse(text="ok"))

    await gateway.start(handler, block=False)

    no_mention_event = {
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user"}},
            "message": {
                "message_id": "m1",
                "chat_id": "c1",
                "chat_type": "group",
                "message_type": "text",
                "content": '{"text":"hello"}',
                "mentions": [],
            },
        }
    }

    await gateway.ingest_event(no_mention_event)
    assert capture.called == 0

    mention_event = {
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user"}},
            "message": {
                "message_id": "m2",
                "chat_id": "c1",
                "chat_type": "group",
                "message_type": "text",
                "content": '{"text":"@bot hi"}',
                "mentions": [{"id": {"open_id": "ou_bot"}, "name": "bot", "key": "@bot"}],
            },
        }
    }

    await gateway.ingest_event(mention_event)
    assert capture.called == 1
    assert "hi" in capture.last_text
    assert api.replied
    assert api.reactions
    assert api.reactions[0]["message_id"] == "m2"
    assert api.reactions[0]["emoji_type_name"] == "OK"
    assert api.calls.index("react") < api.calls.index("reply")
    assert api.replied[0]["message_id"] == "m2"
    assert api.replied[0]["msg_type"] == "interactive"
    assert api.replied[0]["reply_in_thread"] is True


@pytest.mark.asyncio
async def test_send_creates_text_message_via_sdk_api():
    api = FakeApi()
    gateway = FeishuGateway(
        config=FeishuGatewayConfig(app_id="id", app_secret="secret"),
        api=api,
        ws_client_factory=_ws_factory,
    )

    await gateway.send("chat-1", RunResponse(text="hello"))

    assert len(api.created) == 1
    assert api.created[0]["chat_id"] == "chat-1"
    assert api.created[0]["msg_type"] == "interactive"
    payload = json.loads(api.created[0]["content"])
    assert payload["schema"] == "2.0"
    assert payload["config"]["update_multi"] is True
    assert payload["header"]["title"]["content"] == "老佛爷"
    assert payload["header"]["template"] == "blue"
    assert payload["header"]["padding"] == "12px 8px 12px 8px"
    assert payload["body"]["direction"] == "vertical"
    assert payload["body"]["elements"][0]["tag"] == "img"
    assert payload["body"]["elements"][0]["img_key"] == "img_v3_02vu_775831b4-98ab-4158-b00c-4b132cf4bb2g"
    assert payload["body"]["elements"][1]["tag"] == "markdown"
    assert "hello" in payload["body"]["elements"][1]["content"]
    assert len(payload["body"]["elements"]) == 2
    assert all(item["tag"] != "button" for item in payload["body"]["elements"])


@pytest.mark.asyncio
async def test_ingest_event_dedup_message_id():
    gateway = FeishuGateway(
        config=FeishuGatewayConfig(app_id="id", app_secret="secret", bot_open_id="ou_bot"),
        api=FakeApi(),
        ws_client_factory=_ws_factory,
    )

    capture = Capture()

    async def handler(msg, reply, stream_handler=None):
        capture.called += 1
        await reply(RunResponse(text="ok"))

    await gateway.start(handler, block=False)

    event = {
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user"}},
            "message": {
                "message_id": "m-dedup",
                "chat_id": "c1",
                "chat_type": "group",
                "message_type": "text",
                "content": '{"text":"hello"}',
                "mentions": [{"id": {"open_id": "ou_bot"}, "name": "bot", "key": "@bot"}],
            },
        }
    }

    await gateway.ingest_event(event)
    await gateway.ingest_event(event)

    assert capture.called == 1


@pytest.mark.asyncio
async def test_stream_handler_updates_interactive_card():
    api = FakeApi()
    gateway = FeishuGateway(
        config=FeishuGatewayConfig(
            app_id="id",
            app_secret="secret",
            bot_open_id="ou_bot",
            card_stream_update_interval_ms=0,
        ),
        api=api,
        ws_client_factory=_ws_factory,
    )

    async def handler(msg, reply, stream_handler=None):
        del reply
        assert stream_handler is not None

        async def stream():
            yield AgentStreamEvent(type="tool_use", name="terminal", tool_input={"command": "pwd"})
            yield AgentStreamEvent(type="text_delta", text="南京")
            yield AgentStreamEvent(type="text_delta", text="小雨")
            yield AgentStreamEvent(type="tool_result", name="terminal", text="exit_code=0")
            yield AgentStreamEvent(type="done", response=RunResponse(text="南京小雨"))

        await stream_handler(stream())

    await gateway.start(handler, block=False)
    event = {
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user"}},
            "message": {
                "message_id": "m-stream",
                "chat_id": "c-stream",
                "chat_type": "group",
                "message_type": "text",
                "content": '{"text":"@bot weather"}',
                "mentions": [{"id": {"open_id": "ou_bot"}, "name": "bot", "key": "@bot"}],
            },
        }
    }
    await gateway.ingest_event(event)

    # First create is interactive card for stream.
    assert api.reactions
    assert api.reactions[0]["message_id"] == "m-stream"
    assert api.reactions[0]["emoji_type_name"] == "OK"
    assert api.calls.index("react") < api.calls.index("reply")
    assert api.replied
    assert api.replied[0]["message_id"] == "m-stream"
    assert api.replied[0]["msg_type"] == "interactive"
    stream_payload = json.loads(api.replied[0]["content"])
    assert stream_payload["schema"] == "2.0"
    assert stream_payload["config"]["update_multi"] is True
    assert stream_payload["header"]["title"]["content"] == "老佛爷"
    assert stream_payload["body"]["direction"] == "vertical"
    assert stream_payload["body"]["elements"][0]["tag"] == "img"
    assert stream_payload["body"]["elements"][1]["tag"] == "markdown"
    assert stream_payload["body"]["elements"][1]["element_id"] == "answer_stream"
    assert len(stream_payload["body"]["elements"]) == 2
    assert all(item["tag"] != "button" for item in stream_payload["body"]["elements"])
    assert api.converted
    assert api.converted[0]["message_id"] == "om_reply_1"
    assert api.streamed
    assert "南京小雨" in api.streamed[-1]["content"]
    assert all("tool_result" not in item["content"] for item in api.streamed)
    assert api.settings
    final_settings = json.loads(api.settings[-1]["settings"])
    assert final_settings["config"]["streaming_mode"] is False


@pytest.mark.asyncio
async def test_stream_handler_batches_text_updates_by_token_threshold():
    api = FakeApi()
    gateway = FeishuGateway(
        config=FeishuGatewayConfig(
            app_id="id",
            app_secret="secret",
            bot_open_id="ou_bot",
            card_stream_batch_tokens=5,
            card_stream_update_interval_ms=999999,
        ),
        api=api,
        ws_client_factory=_ws_factory,
    )

    async def handler(msg, reply, stream_handler=None):
        del msg, reply
        assert stream_handler is not None

        async def stream():
            for _ in range(12):
                yield AgentStreamEvent(type="text_delta", text="a ")
            yield AgentStreamEvent(type="done", response=RunResponse(text=""))

        await stream_handler(stream())

    await gateway.start(handler, block=False)
    event = {
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user"}},
            "message": {
                "message_id": "m-batch",
                "chat_id": "c-batch",
                "chat_type": "group",
                "message_type": "text",
                "content": '{"text":"@bot batch"}',
                "mentions": [{"id": {"open_id": "ou_bot"}, "name": "bot", "key": "@bot"}],
            },
        }
    }
    await gateway.ingest_event(event)

    # 12 estimated tokens with threshold=5 -> 3 flushes (5, 10, done).
    assert len(api.streamed) == 3
    assert api.streamed[0]["sequence"] == 1
    assert api.streamed[1]["sequence"] == 2
    assert api.streamed[2]["sequence"] == 3


@pytest.mark.asyncio
async def test_stream_handler_closes_streaming_mode_when_stream_raises():
    api = FakeApi()
    gateway = FeishuGateway(
        config=FeishuGatewayConfig(
            app_id="id",
            app_secret="secret",
            bot_open_id="ou_bot",
            card_stream_update_interval_ms=0,
        ),
        api=api,
        ws_client_factory=_ws_factory,
    )

    async def handler(msg, reply, stream_handler=None):
        del msg, reply
        assert stream_handler is not None

        async def stream():
            yield AgentStreamEvent(type="text_delta", text="进行中")
            raise RuntimeError("stream exploded")

        await stream_handler(stream())

    await gateway.start(handler, block=False)
    event = {
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user"}},
            "message": {
                "message_id": "m-stream-error",
                "chat_id": "c-stream-error",
                "chat_type": "group",
                "message_type": "text",
                "content": '{"text":"@bot fail"}',
                "mentions": [{"id": {"open_id": "ou_bot"}, "name": "bot", "key": "@bot"}],
            },
        }
    }

    with pytest.raises(RuntimeError, match="stream exploded"):
        await gateway.ingest_event(event)

    assert api.settings
    final_settings = json.loads(api.settings[-1]["settings"])
    assert final_settings["config"]["streaming_mode"] is False


@pytest.mark.asyncio
async def test_ws_callback_schedules_event_on_main_loop():
    api = FakeApi()
    gateway = FeishuGateway(
        config=FeishuGatewayConfig(app_id="id", app_secret="secret", bot_open_id="ou_bot"),
        api=api,
        ws_client_factory=_ws_factory,
    )
    capture = Capture()

    async def handler(msg, reply, stream_handler=None):
        del stream_handler
        capture.called += 1
        capture.last_text = msg.text
        await reply(RunResponse(text="ok"))

    await gateway.start(handler, block=False)
    gateway._on_ws_message(
        _sdk_event(
            message_id="m-from-ws",
            chat_id="c-ws",
            text="@bot hi from ws",
            bot_open_id="ou_bot",
        )
    )
    await asyncio.sleep(0.05)

    assert capture.called == 1
    assert "hi from ws" in capture.last_text
    assert api.replied
    assert api.replied[0]["message_id"] == "m-from-ws"
