from __future__ import annotations

from config import AppConfig, FeishuGatewayConfig


def test_feishu_config_defaults():
    cfg = AppConfig()
    assert isinstance(cfg.feishu, FeishuGatewayConfig)
    assert cfg.feishu.enabled is False
