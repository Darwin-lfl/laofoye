from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from agent import LangGraphAgent
from config import load_config
from dispatcher import Dispatcher
from gateway import CliGateway, FeishuGateway
from memory import build_memory_backend
from onboard import run_onboard
from scheduler import Scheduler, TaskStore
from utils import configure_logging, get_logger

log = get_logger("main")


async def _start() -> None:
    config = load_config()
    configure_logging(level=config.log_level, file_path=config.log_file)
    log.info("Starting 老佛爷 (log_level=%s, log_file=%s)", config.log_level, config.log_file)

    store_path = Path(config.workspaces_dir).parent / "schedules.json"
    store = TaskStore(store_path)
    log.info("Task store initialized: %s", store_path)

    memory_backend = build_memory_backend(
        config=config.agent,
        workspaces_dir=Path(config.workspaces_dir),
    )
    log.info("Memory backend initialized: %s", type(memory_backend).__name__)

    agent = LangGraphAgent(
        config=config.agent,
        workspaces_dir=Path(config.workspaces_dir),
        skills_dir=Path(config.skills_dir),
        scheduler_store=store,
        memory_backend=memory_backend,
    )
    log.info(
        "Agent initialized (model=%s, workspaces_dir=%s, skills_dir=%s)",
        config.agent.model,
        config.workspaces_dir,
        config.skills_dir,
    )

    if config.feishu.enabled:
        if not config.feishu.app_id or not config.feishu.app_secret:
            raise RuntimeError("Feishu enabled but FEISHU_APP_ID/FEISHU_APP_SECRET not configured")
        gateway = FeishuGateway(config=config.feishu)
        log.info("Gateway selected: feishu (domain=%s)", config.feishu.domain)
    else:
        gateway = CliGateway(default_chat_id=config.gateway.default_chat_id)
        log.info("Gateway selected: cli (default_chat_id=%s)", config.gateway.default_chat_id)

    dispatcher = Dispatcher(
        agent,
        scheduler_store=store,
        memory_backend=memory_backend,
    )
    dispatcher.add_gateway(gateway)
    log.info("Dispatcher initialized and gateway registered (%s)", gateway.kind)

    scheduler = Scheduler(
        agent=agent,
        gateways=[gateway],
        dispatcher=dispatcher,
        store=store,
        poll_interval_seconds=config.scheduler.poll_interval_seconds,
    )

    scheduler.start()
    log.info("Scheduler started (poll_interval=%ss)", config.scheduler.poll_interval_seconds)
    try:
        log.info("Dispatcher entering event loop")
        await dispatcher.start()
    finally:
        log.info("Shutdown sequence started")
        await scheduler.stop()
        await dispatcher.stop()
        log.info("Shutdown sequence finished")


def main() -> None:
    parser = argparse.ArgumentParser(description="老佛爷")
    parser.add_argument("command", nargs="?", default="start", choices=["start", "onboard"])
    args = parser.parse_args()

    if args.command == "onboard":
        path = run_onboard()
        print(f"Config written to: {path}")
        return

    try:
        asyncio.run(_start())
    except KeyboardInterrupt:
        log.info("Shutting down...")


if __name__ == "__main__":
    main()
