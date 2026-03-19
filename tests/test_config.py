from __future__ import annotations

import json

from config import load_config


def test_load_config_with_defaults(tmp_path):
    config = load_config(home_dir=tmp_path)

    assert config.agent.model == "gpt-4o-mini"
    assert config.log_level == "info"
    assert config.scheduler.poll_interval_seconds == 30
    assert config.agent.api_key == ""
    assert config.log_file.endswith(".empress-dowager/logs/app.log")


def test_load_config_merges_file_and_env(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "agent": {"model": "gpt-4.1", "system_prompt": "from-file"},
                "log_level": "warn",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("EMPRESS_DOWAGER_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("EMPRESS_DOWAGER_LOG_LEVEL", "debug")

    config = load_config(home_dir=tmp_path, config_path=config_file)

    assert config.agent.model == "gpt-4.1-mini"
    assert config.agent.system_prompt == "from-file"
    assert config.log_level == "debug"


def test_load_config_reads_openai_from_dotenv(tmp_path):
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=sk-from-dotenv\nOPENAI_BASE_URL=https://example-openai.local/v1\n",
        encoding="utf-8",
    )

    config = load_config(home_dir=tmp_path)

    assert config.agent.api_key == "sk-from-dotenv"
    assert config.agent.base_url == "https://example-openai.local/v1"


def test_load_config_keeps_legacy_runclaw_env_compat(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNCLAW_MODEL", "legacy-model")
    monkeypatch.setenv("RUNCLAW_LOG_LEVEL", "warning")

    config = load_config(home_dir=tmp_path)

    assert config.agent.model == "legacy-model"
    assert config.log_level == "warning"


def test_load_config_reads_feishu_stream_batch_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("FEISHU_CARD_STREAM_BATCH_TOKENS", "7")

    config = load_config(home_dir=tmp_path)

    assert config.feishu.card_stream_batch_tokens == 7


def test_load_config_reads_log_file_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPRESS_DOWAGER_LOG_FILE", "runtime/app.log")
    config = load_config(home_dir=tmp_path)
    assert config.log_file == str((tmp_path / "runtime" / "app.log").resolve())
