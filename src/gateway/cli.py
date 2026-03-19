from __future__ import annotations

import asyncio
import json
import uuid

from core_types import InboundMessage, MessageHandler, RunResponse
from utils import get_logger

log = get_logger("gateway.cli")

MAX_TOKEN_SIZE = 12000

class CliGateway:
    kind = "cli"

    def __init__(self, default_chat_id: str = "local") -> None:
        self._default_chat_id = default_chat_id
        self._running = False

    async def start(self, handler: MessageHandler) -> None:
        self._running = True
        log.info("CLI gateway started (default_chat_id=%s). Type /exit to quit.", self._default_chat_id)
        while self._running:
            try:
                raw = await asyncio.to_thread(input, "> ")
            except (KeyboardInterrupt, EOFError):
                log.info("CLI gateway stopping...")
                self._running = False
                break
            text = raw.strip()
            if not text:
                continue
            if text in {"/exit", "/quit"}:
                self._running = False
                log.info("CLI exit command received")
                break

            msg = InboundMessage(
                id=str(uuid.uuid4()),
                text=text,
                chat_id=self._default_chat_id,
                gateway_kind=self.kind,
            )
            log.info("CLI inbound message (id=%s, chars=%d)", msg.id, len(text))

            async def reply(response: RunResponse) -> None:
                log.info("CLI reply ready (chars=%d)", len(response.text))
                print(f"\n{response.text}\n")

            async def stream_handler(stream) -> None:
                printed_text = False
                for_first = True
                thinking_started = False
                answer_started = False
                async for event in stream:
                    if event.type == "tool_use":
                        tool_line = f"[tool] {event.name or 'unknown'}"
                        if event.tool_input:
                            raw = json.dumps(event.tool_input, ensure_ascii=False)
                            if len(raw) > MAX_TOKEN_SIZE:
                                raw = raw[:MAX_TOKEN_SIZE] + "...(truncated)"
                            tool_line += f" {raw}"
                        if for_first:
                            print()
                            for_first = False
                        print(tool_line)
                        continue

                    if event.type == "tool_result":
                        if for_first:
                            print()
                            for_first = False
                        result = (event.text or "").strip() or "(no output)"
                        if len(result) > MAX_TOKEN_SIZE:
                            result = result[:MAX_TOKEN_SIZE] + "...(truncated)"
                        print(f"[tool_result] {event.name or 'unknown'}: {result}")
                        continue

                    if event.type == "thinking_delta" and event.text:
                        if for_first:
                            print()
                            for_first = False
                        if not thinking_started:
                            print("[thinking] ", end="", flush=True)
                            thinking_started = True
                        print(event.text, end="", flush=True)
                        continue

                    if event.type == "text_delta" and event.text:
                        if for_first:
                            print()
                            for_first = False
                        if thinking_started and not answer_started:
                            print("\n[answer] ", end="", flush=True)
                            answer_started = True
                        elif not answer_started:
                            print("[answer] ", end="", flush=True)
                            answer_started = True
                        print(event.text, end="", flush=True)
                        printed_text = True
                        continue

                    if event.type == "done" and event.response:
                        if not printed_text:
                            if for_first:
                                print()
                            print(event.response.text, end="", flush=True)
                        print("\n")

            await handler(msg, reply, stream_handler)

    async def stop(self) -> None:
        self._running = False
        log.info("CLI gateway stop requested")

    async def send(self, chat_id: str, response: RunResponse) -> None:
        log.info("CLI outbound scheduled message (chat_id=%s, chars=%d)", chat_id, len(response.text))
        print(f"\n[schedule:{chat_id}] {response.text}\n")
