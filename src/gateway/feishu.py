from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from collections.abc import AsyncGenerator, Callable
from contextvars import Context
from dataclasses import replace
from typing import Any, Protocol

from config import FeishuGatewayConfig
from core_types import AgentStreamEvent, InboundMessage, MessageHandler, RunResponse
from utils import get_logger

log = get_logger("gateway.feishu")
STREAM_TEXT_ELEMENT_ID = "answer_stream"
CARD_HEADER_TITLE = "老佛爷"
CARD_IMAGE_KEY = "img_v3_02vu_775831b4-98ab-4158-b00c-4b132cf4bb2g"
CARD_IMAGE_ALT = "我是老佛爷，需要来一段PUA吗"


class FeishuApi(Protocol):
    def react_emoji_to(self, *, message_id: str, emoji_type_name: str) -> None: ...

    def create_message(self, *, chat_id: str, msg_type: str, content: str) -> str: ...

    def reply_message(
            self,
            *,
            message_id: str,
            msg_type: str,
            content: str,
            reply_in_thread: bool = True,
    ) -> str: ...

    def id_convert_card_id(self, *, message_id: str) -> str: ...

    def stream_card_text(
            self,
            *,
            card_id: str,
            element_id: str,
            content: str,
            sequence: int,
    ) -> None: ...

    def update_card_settings(self, *, card_id: str, settings: str, sequence: int) -> None: ...


class WsClient(Protocol):
    def start(self) -> None: ...


WsClientFactory = Callable[[Callable[[Any], None]], WsClient]


class _SdkFeishuApi(FeishuApi):
    def __init__(self, config: FeishuGatewayConfig) -> None:
        try:
            import lark_oapi as lark
            import lark_oapi.api.cardkit.v1 as cardkit_v1
            import lark_oapi.api.im.v1 as im_v1
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "Feishu gateway requires lark-oapi. "
                "Install with: UV_CACHE_DIR=/tmp/uv-cache uv sync --extra dev"
            ) from exc

        self._im_v1 = im_v1
        self._cardkit_v1 = cardkit_v1
        self._client = (
            lark.Client.builder()
            .app_id(config.app_id)
            .app_secret(config.app_secret)
            .domain(config.domain)
            .build()
        )

    def create_message(self, *, chat_id: str, msg_type: str, content: str) -> str:
        req = (
            self._im_v1.CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                self._im_v1.CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type(msg_type)
                .content(content)
                .uuid(str(uuid.uuid4()))
                .build()
            )
            .build()
        )
        resp = self._client.im.v1.message.create(req)
        if not resp.success():
            raise RuntimeError(f"create message failed: code={resp.code}, msg={resp.msg}")
        if resp.data is None or not resp.data.message_id:
            raise RuntimeError("create message succeeded but missing message_id")
        return str(resp.data.message_id)

    def react_emoji_to(self, *, message_id: str, emoji_type_name: str) -> None:
        req = (
            self._im_v1.CreateMessageReactionRequest.builder()
            .message_id(message_id)
            .request_body(
                self._im_v1.CreateMessageReactionRequestBody.builder()
                .reaction_type(self._im_v1.Emoji.builder().emoji_type(emoji_type_name).build())
                .build()
            )
            .build()
        )
        resp = self._client.im.v1.message_reaction.create(req)
        if not resp.success():
            raise RuntimeError(
                "react emoji failed: "
                f"message_id={message_id}, emoji_type={emoji_type_name}, "
                f"code={resp.code}, msg={resp.msg}, log_id={resp.get_log_id()}"
            )

    def reply_message(
            self,
            *,
            message_id: str,
            msg_type: str,
            content: str,
            reply_in_thread: bool = True,
    ) -> str:
        req = (
            self._im_v1.ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                self._im_v1.ReplyMessageRequestBody.builder()
                .msg_type(msg_type)
                .content(content)
                .reply_in_thread(reply_in_thread)
                .uuid(str(uuid.uuid4()))
                .build()
            )
            .build()
        )
        resp = self._client.im.v1.message.reply(req)
        if not resp.success():
            raise RuntimeError(f"reply message failed: code={resp.code}, msg={resp.msg}")
        if resp.data is None or not resp.data.message_id:
            raise RuntimeError("reply message succeeded but missing message_id")
        return str(resp.data.message_id)

    def id_convert_card_id(self, *, message_id: str) -> str:
        req = (
            self._cardkit_v1.IdConvertCardRequest.builder()
            .request_body(
                self._cardkit_v1.IdConvertCardRequestBody.builder()
                .message_id(message_id)
                .build()
            )
            .build()
        )
        resp = self._client.cardkit.v1.card.id_convert(req)
        if not resp.success():
            raise RuntimeError(f"id convert failed: code={resp.code}, msg={resp.msg}")
        if resp.data is None or not resp.data.card_id:
            raise RuntimeError("id convert succeeded but missing card_id")
        return str(resp.data.card_id)

    def stream_card_text(
            self,
            *,
            card_id: str,
            element_id: str,
            content: str,
            sequence: int,
    ) -> None:
        req = (
            self._cardkit_v1.ContentCardElementRequest.builder()
            .card_id(card_id)
            .element_id(element_id)
            .request_body(
                self._cardkit_v1.ContentCardElementRequestBody.builder()
                .uuid(str(uuid.uuid4()))
                .content(content)
                .sequence(sequence)
                .build()
            )
            .build()
        )
        resp = self._client.cardkit.v1.card_element.content(req)
        if not resp.success():
            raise RuntimeError(f"stream card content failed: code={resp.code}, msg={resp.msg}")

    def update_card_settings(self, *, card_id: str, settings: str, sequence: int) -> None:
        req = (
            self._cardkit_v1.SettingsCardRequest.builder()
            .card_id(card_id)
            .request_body(
                self._cardkit_v1.SettingsCardRequestBody.builder()
                .uuid(str(uuid.uuid4()))
                .settings(settings)
                .sequence(sequence)
                .build()
            )
            .build()
        )
        resp = self._client.cardkit.v1.card.settings(req)
        if not resp.success():
            raise RuntimeError(f"update card settings failed: code={resp.code}, msg={resp.msg}")


class FeishuGateway:
    kind = "feishu"

    def __init__(
            self,
            *,
            config: FeishuGatewayConfig,
            api: FeishuApi | None = None,
            ws_client_factory: WsClientFactory | None = None,
    ) -> None:
        self._config = config
        self._handler: MessageHandler | None = None
        self._stopped = False
        self._seen_message_ids: dict[str, float] = {}
        self._dedup_ttl_seconds = 600

        self._api = api or _SdkFeishuApi(config)
        self._ws_client_factory = ws_client_factory or self._default_ws_client_factory
        self._ws_client: WsClient | None = None
        self._ws_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self, handler: MessageHandler, *, block: bool = True) -> None:
        self._handler = handler
        self._stopped = False
        self._loop = asyncio.get_running_loop()
        log.info(
            "Feishu gateway starting (long connection mode, domain=%s, stream_batch_tokens=%s, stream_interval_ms=%s)",
            self._config.domain,
            self._config.card_stream_batch_tokens,
            self._config.card_stream_update_interval_ms,
        )
        self._start_long_conn()

        if block:
            while not self._stopped:
                await asyncio.sleep(60)

    async def stop(self) -> None:
        self._stopped = True
        self._handler = None
        log.info("Feishu gateway stopped")

    async def send(self, chat_id: str, response: RunResponse) -> None:
        log.info("Feishu proactive send (chat_id=%s, chars=%d)", chat_id, len(response.text))
        await self._send_card_response(chat_id=chat_id, response=response)

    async def ingest_event(self, payload: dict[str, Any]) -> None:
        if self._handler is None:
            return

        event = payload.get("event") or {}
        message = event.get("message") or {}
        sender = event.get("sender") or {}

        message_id = str(message.get("message_id") or "")
        chat_id = str(message.get("chat_id") or "")
        chat_type = str(message.get("chat_type") or "")
        message_type = str(message.get("message_type") or "")

        if not message_id or not chat_id:
            log.debug("Skip Feishu event due to missing message_id or chat_id")
            return
        if not self._mark_seen(message_id):
            log.debug("Skip duplicate Feishu message (message_id=%s)", message_id)
            return

        text = _extract_text(str(message.get("content") or ""), message_type)
        mentions = message.get("mentions") or []
        mentioned_bot = any(
            (item.get("id") or {}).get("open_id") == self._config.bot_open_id
            for item in mentions
        )
        auto_reply = chat_id in self._config.group_auto_reply
        if chat_type == "group" and not (mentioned_bot or auto_reply):
            log.debug("Skip group message without mention/auto-reply (message_id=%s, chat_id=%s)", message_id, chat_id)
            return

        author_id = str(((sender.get("sender_id") or {}).get("open_id")) or "")
        if chat_type == "group" and not auto_reply and author_id:
            text = f"{author_id}: {text}"
        log.info(
            "Feishu inbound message accepted (message_id=%s, chat_id=%s, chat_type=%s, message_type=%s, chars=%d)",
            message_id,
            chat_id,
            chat_type,
            message_type,
            len(text),
        )

        inbound = InboundMessage(
            id=message_id,
            text=text,
            chat_id=chat_id,
            thread_root_id=message.get("thread_id"),
            author_id=author_id,
            gateway_kind=self.kind,
        )

        async def reply(resp: RunResponse) -> None:
            await self._send_card_response(
                chat_id=chat_id,
                response=resp,
                reply_to_message_id=message_id,
            )

        async def stream_handler(stream: AsyncGenerator[AgentStreamEvent, None]) -> None:
            await self._stream_to_card(
                chat_id=chat_id,
                source_message_id=message_id,
                stream=stream,
            )

        await self._handler(inbound, reply, stream_handler)

    def _start_long_conn(self) -> None:
        if self._ws_client is None:
            self._ws_client = self._ws_client_factory(self._on_ws_message)
        if self._ws_thread and self._ws_thread.is_alive():
            return
        self._ws_thread = threading.Thread(
            target=self._run_ws_client,
            name="feishu-long-conn",
            daemon=True,
        )
        self._ws_thread.start()
        log.info("Feishu long connection thread started")

    def _run_ws_client(self) -> None:
        if self._ws_client is None:
            return
        ws_loop: asyncio.AbstractEventLoop | None = None
        try:
            # lark_oapi.ws.client stores a module-global `loop`. If imported while
            # our main asyncio loop is running, it may bind to that loop and later
            # trigger cross-thread/context issues. Rebind it to a dedicated loop in
            # the long-connection thread before start().
            try:
                import lark_oapi.ws.client as ws_client_module

                ws_loop = asyncio.new_event_loop()
                ws_client_module.loop = ws_loop
                asyncio.set_event_loop(ws_loop)
            except Exception:  # noqa: BLE001
                ws_loop = None
            self._ws_client.start()
            log.info("Feishu websocket client started")
        except Exception:  # noqa: BLE001
            log.exception("Feishu long connection exited with error")
        finally:
            if ws_loop is not None and not ws_loop.is_closed():
                ws_loop.close()

    def _on_ws_message(self, event: Any) -> None:
        if self._loop is None or self._handler is None:
            return
        if self._stopped or self._loop.is_closed():
            return
        payload = _event_to_payload(event)
        if not payload:
            return
        try:
            self._loop.call_soon_threadsafe(self._schedule_ingest_payload, payload, context=Context())
        except TypeError:
            # Compatibility fallback if context kw is unavailable in runtime.
            self._loop.call_soon_threadsafe(self._schedule_ingest_payload, payload)
        except RuntimeError:
            # Loop closed/race during shutdown.
            log.debug("Skip Feishu event: main loop is unavailable")

    def _schedule_ingest_payload(self, payload: dict[str, Any]) -> None:
        if self._stopped or self._handler is None:
            return
        task = asyncio.create_task(self.ingest_event(payload))
        task.add_done_callback(_log_task_error)

    async def _stream_to_card(
            self,
            *,
            chat_id: str,
            source_message_id: str | None,
            stream: AsyncGenerator[AgentStreamEvent, None],
    ) -> None:
        answer_chunks: list[str] = []
        stream_error: Exception | None = None
        card_id: str | None = None
        final_response: RunResponse | None = None
        last_update = time.monotonic()
        last_sent_text = ""
        sequence = 1
        pending_tokens = 0
        batch_tokens = max(1, int(self._config.card_stream_batch_tokens))
        interval = max(0.1, self._config.card_stream_update_interval_ms / 1000)
        ack_sent = False
        log.info(
            "Begin Feishu stream card (chat_id=%s, source_message_id=%s, batch_tokens=%d, interval=%.2fs)",
            chat_id,
            source_message_id or "",
            batch_tokens,
            interval,
        )

        try:
            card = _build_streaming_card()
            card_content = json.dumps(card, ensure_ascii=False)
            if source_message_id:
                await self._react_ack_to_message(source_message_id)
                ack_sent = True
                created_message_id = await asyncio.to_thread(
                    self._api.reply_message,
                    message_id=source_message_id,
                    msg_type="interactive",
                    content=card_content,
                    reply_in_thread=True,
                )
            else:
                created_message_id = await asyncio.to_thread(
                    self._api.create_message,
                    chat_id=chat_id,
                    msg_type="interactive",
                    content=card_content,
                )
            card_id = await asyncio.to_thread(self._api.id_convert_card_id, message_id=created_message_id)
            log.debug("Initialized stream card (card_id=%s)", card_id)
        except Exception:  # noqa: BLE001
            log.exception("Failed to initialize stream card, fallback to final card")
            card_id = None

        try:
            async for event in stream:
                if event.type == "text_delta" and event.text:
                    answer_chunks.append(event.text)
                    pending_tokens += _estimate_tokens(event.text)
                if event.type == "done":
                    if event.response is not None:
                        final_response = event.response
                    if event.response and event.response.text and not "".join(answer_chunks).strip():
                        answer_chunks.append(event.response.text)
                    # Final content (with metadata footer) is sent in finalize block.
                    continue

                if event.type != "text_delta":
                    continue

                now = time.monotonic()
                should_flush = (
                        pending_tokens >= batch_tokens
                        or (pending_tokens > 0 and now - last_update >= interval)
                )
                if not should_flush:
                    continue

                current_text = "".join(answer_chunks)
                if not current_text:
                    continue

                if card_id is not None and current_text != last_sent_text:
                    try:
                        await asyncio.to_thread(
                            self._api.stream_card_text,
                            card_id=card_id,
                            element_id=STREAM_TEXT_ELEMENT_ID,
                            content=current_text,
                            sequence=sequence,
                        )
                        log.debug("Stream card content flushed (card_id=%s, sequence=%d, chars=%d)", card_id, sequence,
                                  len(current_text))
                        sequence += 1
                        last_sent_text = current_text
                        pending_tokens = 0
                    except Exception:  # noqa: BLE001
                        log.exception("Failed to stream update card content")
                last_update = now
        except Exception as exc:  # noqa: BLE001
            stream_error = exc
            log.exception("Stream generator raised before done event, finalizing card state first")

        final_text = "".join(answer_chunks).strip() or "(no output)"
        if final_response is None:
            final_response = RunResponse(text=final_text)
        elif final_response.text != final_text:
            final_response = replace(final_response, text=final_text)
        final_content = _build_card_main_content(final_response)
        delivered = False
        if card_id is not None:
            try:
                if last_sent_text != final_content:
                    await asyncio.to_thread(
                        self._api.stream_card_text,
                        card_id=card_id,
                        element_id=STREAM_TEXT_ELEMENT_ID,
                        content=final_content,
                        sequence=sequence,
                    )
                    sequence += 1
                settings = json.dumps(
                    {
                        "config": {
                            "streaming_mode": False,
                            "summary": {"content": _clip(final_text.replace("\n", " "), 200)},
                        }
                    },
                    ensure_ascii=False,
                )
                await asyncio.to_thread(
                    self._api.update_card_settings,
                    card_id=card_id,
                    settings=settings,
                    sequence=sequence,
                )
                delivered = True
                log.info("Feishu stream card finalized (card_id=%s, final_chars=%d)", card_id, len(final_text))
            except Exception:  # noqa: BLE001
                log.exception("Failed to finalize stream card")
        if not delivered:
            log.info("Falling back to static card delivery (chat_id=%s)", chat_id)
            await self._send_card_response(
                chat_id=chat_id,
                response=final_response,
                reply_to_message_id=source_message_id,
                skip_ack=ack_sent,
            )
        if stream_error is not None:
            raise stream_error

    async def _send_card_response(
            self,
            *,
            chat_id: str,
            response: RunResponse,
            reply_to_message_id: str | None = None,
            skip_ack: bool = False,
    ) -> None:
        card = _build_static_card(response)
        content = json.dumps(card, ensure_ascii=False)
        if reply_to_message_id:
            if not skip_ack:
                await self._react_ack_to_message(reply_to_message_id)
            log.info(
                "Sending Feishu reply card (reply_to=%s, chars=%d, skip_ack=%s)",
                reply_to_message_id,
                len(response.text),
                skip_ack,
            )
            await asyncio.to_thread(
                self._api.reply_message,
                message_id=reply_to_message_id,
                msg_type="interactive",
                content=content,
                reply_in_thread=True,
            )
            return
        log.info("Sending Feishu new card (chat_id=%s, chars=%d)", chat_id, len(response.text))
        await asyncio.to_thread(
            self._api.create_message,
            chat_id=chat_id,
            msg_type="interactive",
            content=content,
        )

    async def _react_ack_to_message(self, message_id: str) -> None:
        emoji_type = self._config.reply_ack_emoji_type.strip()
        if not emoji_type:
            return
        try:
            await asyncio.to_thread(
                self._api.react_emoji_to,
                message_id=message_id,
                emoji_type_name=emoji_type,
            )
            log.debug("Ack emoji sent (message_id=%s, emoji=%s)", message_id, emoji_type)
        except Exception:  # noqa: BLE001
            log.exception(
                "Failed to react ack emoji before reply, continue sending reply",
            )

    def _default_ws_client_factory(self, callback: Callable[[Any], None]) -> WsClient:
        try:
            import lark_oapi as lark
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "Feishu long connection requires lark-oapi. "
                "Install with: UV_CACHE_DIR=/tmp/uv-cache uv sync --extra dev"
            ) from exc

        event_handler = (
            lark.EventDispatcherHandler.builder(
                self._config.verification_token or "",
                self._config.encrypt_key or "",
            )
            .register_p2_im_message_receive_v1(callback)
            .build()
        )
        return lark.ws.Client(
            self._config.app_id,
            self._config.app_secret,
            event_handler=event_handler,
            domain=self._config.domain,
        )

    def _mark_seen(self, message_id: str) -> bool:
        now = time.time()
        if len(self._seen_message_ids) > 500:
            cutoff = now - self._dedup_ttl_seconds
            for mid, ts in list(self._seen_message_ids.items()):
                if ts < cutoff:
                    self._seen_message_ids.pop(mid, None)

        if message_id in self._seen_message_ids:
            return False
        self._seen_message_ids[message_id] = now
        return True


def _event_to_payload(event: Any) -> dict[str, Any]:
    data = getattr(event, "event", None)
    if data is None:
        return {}

    message = getattr(data, "message", None)
    sender = getattr(data, "sender", None)
    if message is None:
        return {}

    mentions_payload: list[dict[str, Any]] = []
    mentions = getattr(message, "mentions", None) or []
    for mention in mentions:
        mention_id = getattr(mention, "id", None)
        mentions_payload.append(
            {
                "id": {
                    "open_id": getattr(mention_id, "open_id", None),
                    "user_id": getattr(mention_id, "user_id", None),
                    "union_id": getattr(mention_id, "union_id", None),
                },
                "name": getattr(mention, "name", None),
                "key": getattr(mention, "key", None),
            }
        )

    sender_id = getattr(sender, "sender_id", None)
    return {
        "event": {
            "sender": {
                "sender_id": {
                    "open_id": getattr(sender_id, "open_id", None),
                    "user_id": getattr(sender_id, "user_id", None),
                    "union_id": getattr(sender_id, "union_id", None),
                }
            },
            "message": {
                "message_id": getattr(message, "message_id", None),
                "chat_id": getattr(message, "chat_id", None),
                "chat_type": getattr(message, "chat_type", None),
                "message_type": getattr(message, "message_type", None),
                "content": getattr(message, "content", None),
                "thread_id": getattr(message, "thread_id", None),
                "mentions": mentions_payload,
            },
        }
    }


def _extract_text(content: str, message_type: str) -> str:
    if message_type != "text":
        return content or f"<{message_type}>"
    try:
        data = json.loads(content)
        return str(data.get("text") or "")
    except json.JSONDecodeError:
        return content


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _estimate_tokens(text: str) -> int:
    # Lightweight token approximation for batching stream updates.
    # Counts word-like segments and individual symbols/CJK chars.
    parts = re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", text)
    return max(1, len(parts))


def _build_streaming_card() -> dict[str, Any]:
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "streaming_mode": True,
            "streaming_config": {
                "print_frequency_ms": {
                    "default": 70,
                    "android": 70,
                    "ios": 70,
                    "pc": 70
                },
                "print_step": {
                    "default": 1,
                    "android": 1,
                    "ios": 1,
                    "pc": 1
                },
                "print_strategy": "fast"
            }
        },
        "header": _build_card_header(),
        "body": {
            "direction": "vertical",
            "elements": _build_card_elements(
                content="_生成中..._",
                element_id=STREAM_TEXT_ELEMENT_ID,
            ),
        },
    }


def _build_static_card(response: RunResponse) -> dict[str, Any]:
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": _build_card_header(),
        "body": {
            "direction": "vertical",
            "elements": _build_card_elements(content=_build_card_main_content(response)),
        },
    }


def _build_card_header() -> dict[str, Any]:
    return {
        "title": {"tag": "plain_text", "content": CARD_HEADER_TITLE},
        "subtitle": {"tag": "plain_text", "content": ""},
        "template": "blue",
        "padding": "12px 8px 12px 8px",
    }


def _build_card_elements(*, content: str, element_id: str | None = None) -> list[dict[str, Any]]:
    markdown: dict[str, Any] = {
        "tag": "markdown",
        "content": content,
        "text_size": "normal",
        "margin": "0px 0px 0px 0px",
    }
    if element_id:
        markdown["element_id"] = element_id

    return [
        {
            "tag": "img",
            "img_key": CARD_IMAGE_KEY,
            "preview": False,
            "scale_type": "fit_horizontal",
            "alt": {"tag": "plain_text", "content": CARD_IMAGE_ALT},
            "corner_radius": "8px",
            "margin": "0px 0px 0px 0px",
        },
        markdown,
    ]


def _build_card_main_content(response: RunResponse) -> str:
    body = (response.text or "").strip() or "(no output)"
    footer = _build_card_footer(response)
    return f"{body}\n\n{footer}"


def _build_card_footer(response: RunResponse) -> str:
    elapsed_text = _format_elapsed_ms(response.elapsed_ms)
    tokens_text = _format_tokens(response.input_tokens, response.output_tokens)
    return f"---\n> 耗时：`{elapsed_text}` | Token：`{tokens_text}`"


def _format_elapsed_ms(elapsed_ms: int | None) -> str:
    if elapsed_ms is None or elapsed_ms < 0:
        return "N/A"
    if elapsed_ms < 1000:
        return f"{elapsed_ms} ms"
    return f"{elapsed_ms / 1000:.2f} s"


def _format_tokens(input_tokens: int | None, output_tokens: int | None) -> str:
    if input_tokens is None and output_tokens is None:
        return "N/A"
    in_text = str(input_tokens) if input_tokens is not None else "-"
    out_text = str(output_tokens) if output_tokens is not None else "-"
    total = (
        input_tokens + output_tokens
        if input_tokens is not None and output_tokens is not None
        else None
    )
    total_text = str(total) if total is not None else "-"
    return f"in {in_text} / out {out_text} / total {total_text}"


def _log_task_error(task: "asyncio.Task[None]") -> None:
    try:
        task.result()
    except Exception:  # noqa: BLE001
        log.exception("Failed to handle Feishu long-conn event")
