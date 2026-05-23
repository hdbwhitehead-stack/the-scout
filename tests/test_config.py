"""Tests for the config loader."""
from pathlib import Path

import pytest

from scout.config import Config, load_config


def test_load_config_reads_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
yield_threshold_apr = 0.05
min_price = 0.90
max_days_to_resolution = 730
model = "claude-haiku-4-5"
"""
    )
    cfg = load_config(config_path)
    assert isinstance(cfg, Config)
    assert cfg.yield_threshold_apr == 0.05
    assert cfg.min_price == 0.90
    assert cfg.max_days_to_resolution == 730
    assert cfg.model == "claude-haiku-4-5"


def test_load_config_rejects_negative_threshold(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
yield_threshold_apr = -0.01
min_price = 0.90
max_days_to_resolution = 730
model = "claude-haiku-4-5"
"""
    )
    with pytest.raises(ValueError, match="yield_threshold_apr"):
        load_config(config_path)
