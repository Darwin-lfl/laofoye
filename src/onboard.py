from __future__ import annotations

import json
from pathlib import Path

from config import AppConfig, project_root


def run_onboard(home_dir: Path | None = None) -> Path:
    root = home_dir or project_root()
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / "config.json"

    model = input("Model (default gpt-4o-mini): ").strip() or "gpt-4o-mini"
    log_level = input("Log level (debug/info/warn/error, default info): ").strip() or "info"

    config = AppConfig.model_validate(
        {
            "agent": {"model": model},
            "log_level": log_level,
            "workspaces_dir": str(root / "workspaces"),
            "skills_dir": str(root / "skills"),
        }
    )
    config_path.write_text(json.dumps(config.model_dump(), indent=2), encoding="utf-8")
    return config_path
