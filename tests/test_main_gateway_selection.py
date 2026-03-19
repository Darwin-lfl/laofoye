from __future__ import annotations

from config import AppConfig, FeishuGatewayConfig


def test_feishu_config_defaults():
    cfg = AppConfig()
    assert isinstance(cfg.feishu, FeishuGatewayConfig)
    assert cfg.feishu.enabled is False
    assert cfg.feishu.webhook_host == "127.0.0.1"
    assert cfg.feishu.webhook_port == 9001
