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
min_liquidity = 200.0
min_volume = 5000.0
"""
    )
    cfg = load_config(config_path)
    assert isinstance(cfg, Config)
    assert cfg.yield_threshold_apr == 0.05
    assert cfg.min_price == 0.90
    assert cfg.max_days_to_resolution == 730
    assert cfg.model == "claude-haiku-4-5"
    assert cfg.min_liquidity == 200.0
    assert cfg.min_volume == 5000.0


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


def test_load_config_uses_defaults_for_missing_liquidity_fields(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        """
yield_threshold_apr = 0.05
min_price = 0.85
max_days_to_resolution = 730
model = "claude-haiku-4-5"
"""
    )
    cfg = load_config(p)
    assert cfg.min_liquidity == 100.0
    assert cfg.min_volume == 1000.0


def test_load_config_uses_defaults_for_recommended_and_excluded_fields(tmp_path: Path) -> None:
    """Older configs without the new recommendation fields still load cleanly."""
    p = tmp_path / "config.toml"
    p.write_text(
        """
yield_threshold_apr = 0.05
min_price = 0.85
max_days_to_resolution = 730
model = "claude-haiku-4-5"
"""
    )
    cfg = load_config(p)
    assert cfg.recommended_min_edge_pct == 3.0
    assert cfg.recommended_max_risk_score == 2
    assert cfg.excluded_tags == ()


def test_load_config_reads_recommended_and_excluded_fields(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        """
yield_threshold_apr = 0.05
min_price = 0.85
max_days_to_resolution = 730
model = "claude-haiku-4-5:v2"
recommended_min_edge_pct = 5.0
recommended_max_risk_score = 1
excluded_tags = ["Religion", "Crypto Prices"]
"""
    )
    cfg = load_config(p)
    assert cfg.recommended_min_edge_pct == 5.0
    assert cfg.recommended_max_risk_score == 1
    assert cfg.excluded_tags == ("Religion", "Crypto Prices")
    assert cfg.model == "claude-haiku-4-5:v2"
