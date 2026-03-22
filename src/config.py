from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def project_root() -> Path:
    # Source layout is `src/*.py`, so parent of this file's directory is repo root.
    return Path(__file__).resolve().parent.parent


class AgentConfig(BaseModel):
    model: str = "gpt-4o-mini"
    system_prompt: str = (
        "You are 老佛爷, a practical assistant. "
        "Read AGENTS.md in workspace first, keep answers concise, and match user language."
    )
    allowed_tools: list[str] = Field(default_factory=list)
    history_keep_messages: int = 24
    history_compact_threshold: int = 36
    history_summary_max_chars: int = 20000
    context_window_tokens: int = 20000
    api_key: str = ""
    base_url: str | None = None
    web_search_provider: str = "tavily"
    web_search_api_key: str = ""
    web_search_base_url: str = ""
    web_fetch_jina_api_key: str = ""
    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""
    openviking_enabled: bool = False
    openviking_path: str = str(project_root() / ".openviking")
    openviking_search_limit: int = 5
    openviking_commit_every_turn: bool = True
    openviking_payload_history_keep_messages: int = 8
    openviking_payload_token_budget: int = 6000


class SchedulerConfig(BaseModel):
    poll_interval_seconds: int = 30


class CliGatewayConfig(BaseModel):
    default_chat_id: str = "local"


class FeishuGatewayConfig(BaseModel):
    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    bot_open_id: str = ""
    verification_token: str = ""
    encrypt_key: str = ""
    domain: str = "https://open.feishu.cn"
    webhook_host: str = "127.0.0.1"
    webhook_port: int = 9001
    card_stream_update_interval_ms: int = 3000
    card_stream_batch_tokens: int = 5
    reply_ack_emoji_type: str = "OK"
    group_auto_reply: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    agent: AgentConfig = Field(default_factory=AgentConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    gateway: CliGatewayConfig = Field(default_factory=CliGatewayConfig)
    feishu: FeishuGatewayConfig = Field(default_factory=FeishuGatewayConfig)
    workspaces_dir: str = str(Path.home() / ".empress-dowager" / "workspaces")
    skills_dir: str = str(Path.home() / ".empress-dowager" / "skills")
    log_level: str = "info"
    log_file: str = str(Path.home() / ".empress-dowager" / "logs" / "app.log")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_dotenv(dotenv_path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not dotenv_path.exists():
        return data

    for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        data[key] = value
        # Respect existing process env if already present.
        os.environ.setdefault(key, value)
    return data


def _first_env(*keys: str) -> str | None:
    for key in keys:
        value = os.getenv(key)
        if value is not None and value != "":
            return value
    return None


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_config(
    *,
    home_dir: Path | None = None,
    config_path: Path | None = None,
) -> AppConfig:
    root = home_dir or project_root()
    path = config_path or root / "config.json"
    dotenv_values = _load_dotenv(root / ".env")

    base = AppConfig().model_dump()
    file_data: dict[str, Any] = {}
    if path.exists():
        file_data = json.loads(path.read_text(encoding="utf-8"))

    merged = _deep_merge(base, file_data)

    agent = dict(merged.get("agent", {}))
    agent["model"] = _first_env("EMPRESS_DOWAGER_MODEL", "RUNCLAW_MODEL") or agent.get("model", "gpt-4o-mini")
    system_prompt = _first_env("EMPRESS_DOWAGER_SYSTEM_PROMPT", "RUNCLAW_SYSTEM_PROMPT")
    if system_prompt:
        agent["system_prompt"] = system_prompt
    # OPENAI_API_KEY must be injected from project .env.
    agent["api_key"] = dotenv_values.get("OPENAI_API_KEY", "")
    agent["base_url"] = (
        os.getenv("OPENAI_BASE_URL")
        or os.getenv("OPENAI_API_BASE")
        or dotenv_values.get("OPENAI_BASE_URL")
        or dotenv_values.get("OPENAI_API_BASE")
        or agent.get("base_url")
    )
    agent["web_search_provider"] = (
        _first_env(
            "EMPRESS_DOWAGER_WEB_SEARCH_PROVIDER",
            "RUNCLAW_WEB_SEARCH_PROVIDER",
            "WEB_SEARCH_PROVIDER",
        )
        or str(agent.get("web_search_provider", "tavily"))
    )
    agent["web_search_api_key"] = (
        _first_env(
            "EMPRESS_DOWAGER_WEB_SEARCH_API_KEY",
            "RUNCLAW_WEB_SEARCH_API_KEY",
            "WEB_SEARCH_API_KEY",
            "BRAVE_API_KEY",
            "TAVILY_API_KEY",
            "JINA_API_KEY",
        )
        or str(agent.get("web_search_api_key", ""))
    )
    agent["web_search_base_url"] = (
        _first_env(
            "EMPRESS_DOWAGER_WEB_SEARCH_BASE_URL",
            "RUNCLAW_WEB_SEARCH_BASE_URL",
            "WEB_SEARCH_BASE_URL",
            "SEARXNG_BASE_URL",
        )
        or str(agent.get("web_search_base_url", ""))
    )
    agent["web_fetch_jina_api_key"] = (
        _first_env(
            "EMPRESS_DOWAGER_WEB_FETCH_JINA_API_KEY",
            "RUNCLAW_WEB_FETCH_JINA_API_KEY",
            "WEB_FETCH_JINA_API_KEY",
            "JINA_API_KEY",
        )
        or str(agent.get("web_fetch_jina_api_key", ""))
    )
    langfuse_enabled = _first_env(
        "EMPRESS_DOWAGER_LANGFUSE_ENABLED",
        "RUNCLAW_LANGFUSE_ENABLED",
        "LANGFUSE_ENABLED",
    )
    agent["langfuse_enabled"] = (
        _to_bool(langfuse_enabled)
        if langfuse_enabled is not None
        else _to_bool(agent.get("langfuse_enabled", False))
    )
    agent["langfuse_public_key"] = (
        _first_env(
            "EMPRESS_DOWAGER_LANGFUSE_PUBLIC_KEY",
            "RUNCLAW_LANGFUSE_PUBLIC_KEY",
            "LANGFUSE_PUBLIC_KEY",
        )
        or str(agent.get("langfuse_public_key", ""))
    )
    agent["langfuse_secret_key"] = (
        _first_env(
            "EMPRESS_DOWAGER_LANGFUSE_SECRET_KEY",
            "RUNCLAW_LANGFUSE_SECRET_KEY",
            "LANGFUSE_SECRET_KEY",
        )
        or str(agent.get("langfuse_secret_key", ""))
    )
    agent["langfuse_host"] = (
        _first_env(
            "EMPRESS_DOWAGER_LANGFUSE_HOST",
            "RUNCLAW_LANGFUSE_HOST",
            "LANGFUSE_HOST",
        )
        or str(agent.get("langfuse_host", ""))
    )
    openviking_enabled = _first_env(
        "EMPRESS_DOWAGER_OPENVIKING_ENABLED",
        "RUNCLAW_OPENVIKING_ENABLED",
        "OPENVIKING_ENABLED",
    )
    agent["openviking_enabled"] = (
        _to_bool(openviking_enabled)
        if openviking_enabled is not None
        else _to_bool(agent.get("openviking_enabled", False))
    )
    agent["openviking_path"] = (
        _first_env(
            "EMPRESS_DOWAGER_OPENVIKING_PATH",
            "RUNCLAW_OPENVIKING_PATH",
            "OPENVIKING_PATH",
        )
        or str(agent.get("openviking_path", root / ".openviking"))
    )

    openviking_search_limit = _first_env(
        "EMPRESS_DOWAGER_OPENVIKING_SEARCH_LIMIT",
        "RUNCLAW_OPENVIKING_SEARCH_LIMIT",
        "OPENVIKING_SEARCH_LIMIT",
    )
    try:
        agent["openviking_search_limit"] = max(
            1,
            int(
                openviking_search_limit
                if openviking_search_limit is not None
                else agent.get("openviking_search_limit", 5)
            ),
        )
    except (TypeError, ValueError):
        agent["openviking_search_limit"] = 5

    openviking_commit_every_turn = _first_env(
        "EMPRESS_DOWAGER_OPENVIKING_COMMIT_EVERY_TURN",
        "RUNCLAW_OPENVIKING_COMMIT_EVERY_TURN",
        "OPENVIKING_COMMIT_EVERY_TURN",
    )
    agent["openviking_commit_every_turn"] = (
        _to_bool(openviking_commit_every_turn)
        if openviking_commit_every_turn is not None
        else _to_bool(agent.get("openviking_commit_every_turn", True))
    )
    openviking_payload_history_keep_messages = _first_env(
        "EMPRESS_DOWAGER_OPENVIKING_PAYLOAD_HISTORY_KEEP_MESSAGES",
        "RUNCLAW_OPENVIKING_PAYLOAD_HISTORY_KEEP_MESSAGES",
        "OPENVIKING_PAYLOAD_HISTORY_KEEP_MESSAGES",
    )
    try:
        agent["openviking_payload_history_keep_messages"] = max(
            0,
            int(
                openviking_payload_history_keep_messages
                if openviking_payload_history_keep_messages is not None
                else agent.get("openviking_payload_history_keep_messages", 8)
            ),
        )
    except (TypeError, ValueError):
        agent["openviking_payload_history_keep_messages"] = 8

    openviking_payload_token_budget = _first_env(
        "EMPRESS_DOWAGER_OPENVIKING_PAYLOAD_TOKEN_BUDGET",
        "RUNCLAW_OPENVIKING_PAYLOAD_TOKEN_BUDGET",
        "OPENVIKING_PAYLOAD_TOKEN_BUDGET",
    )
    try:
        agent["openviking_payload_token_budget"] = max(
            1,
            int(
                openviking_payload_token_budget
                if openviking_payload_token_budget is not None
                else agent.get("openviking_payload_token_budget", 6000)
            ),
        )
    except (TypeError, ValueError):
        agent["openviking_payload_token_budget"] = 6000
    merged["agent"] = agent

    feishu = dict(merged.get("feishu", {}))
    feishu["enabled"] = str(os.getenv("FEISHU_ENABLED", str(feishu.get("enabled", False)))).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    feishu["app_id"] = os.getenv("FEISHU_APP_ID", str(feishu.get("app_id", "")))
    feishu["app_secret"] = os.getenv("FEISHU_APP_SECRET", str(feishu.get("app_secret", "")))
    feishu["domain"] = os.getenv("FEISHU_DOMAIN", str(feishu.get("domain", "https://open.feishu.cn")))
    feishu["card_stream_update_interval_ms"] = int(
        os.getenv(
            "FEISHU_CARD_STREAM_UPDATE_INTERVAL_MS",
            str(feishu.get("card_stream_update_interval_ms", 3000)),
        )
    )
    feishu["card_stream_batch_tokens"] = int(
        os.getenv(
            "FEISHU_CARD_STREAM_BATCH_TOKENS",
            str(feishu.get("card_stream_batch_tokens", 5)),
        )
    )
    feishu["reply_ack_emoji_type"] = os.getenv(
        "FEISHU_REPLY_ACK_EMOJI_TYPE",
        str(feishu.get("reply_ack_emoji_type", "OK")),
    )
    merged["feishu"] = feishu

    merged["log_level"] = _first_env("EMPRESS_DOWAGER_LOG_LEVEL", "RUNCLAW_LOG_LEVEL") or str(
        merged.get("log_level", "info")
    )
    merged["log_file"] = _first_env("EMPRESS_DOWAGER_LOG_FILE", "RUNCLAW_LOG_FILE") or str(
        merged.get("log_file", Path.home() / ".empress-dowager" / "logs" / "app.log")
    )

    workspaces_raw = _first_env("EMPRESS_DOWAGER_WORKSPACES_DIR", "RUNCLAW_WORKSPACES_DIR") or str(
        merged.get("workspaces_dir", root / "workspaces")
    )
    skills_raw = _first_env("EMPRESS_DOWAGER_SKILLS_DIR", "RUNCLAW_SKILLS_DIR") or str(
        merged.get("skills_dir", root / "skills")
    )

    workspaces_path = Path(workspaces_raw).expanduser()
    skills_path = Path(skills_raw).expanduser()
    if not workspaces_path.is_absolute():
        workspaces_path = (root / workspaces_path).resolve()
    if not skills_path.is_absolute():
        skills_path = (root / skills_path).resolve()

    merged["workspaces_dir"] = str(workspaces_path)
    merged["skills_dir"] = str(skills_path)

    log_file_path = Path(str(merged["log_file"])).expanduser()
    if not log_file_path.is_absolute():
        log_file_path = (root / log_file_path).resolve()
    merged["log_file"] = str(log_file_path)

    return AppConfig.model_validate(merged)
