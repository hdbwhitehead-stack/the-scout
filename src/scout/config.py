"""Configuration loader for polymarket-scout."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    yield_threshold_apr: float
    min_price: float
    max_days_to_resolution: int
    model: str
    min_liquidity: float
    min_volume: float
    recommended_min_edge_pct: float = 3.0
    recommended_max_risk_score: int = 2
    excluded_tags: tuple[str, ...] = field(default_factory=tuple)


def load_config(path: Path) -> Config:
    with path.open("rb") as f:
        data = tomllib.load(f)

    yield_threshold = float(data["yield_threshold_apr"])
    if yield_threshold < 0:
        raise ValueError("yield_threshold_apr must be >= 0")

    min_price = float(data["min_price"])
    if not 0 < min_price < 1:
        raise ValueError("min_price must be between 0 and 1 (exclusive)")

    max_days = int(data["max_days_to_resolution"])
    if max_days <= 0:
        raise ValueError("max_days_to_resolution must be > 0")

    min_liquidity = float(data.get("min_liquidity", 100.0))
    if min_liquidity < 0:
        raise ValueError("min_liquidity must be >= 0")

    min_volume = float(data.get("min_volume", 1000.0))
    if min_volume < 0:
        raise ValueError("min_volume must be >= 0")

    recommended_min_edge_pct = float(data.get("recommended_min_edge_pct", 3.0))
    recommended_max_risk_score = int(data.get("recommended_max_risk_score", 2))

    excluded_tags_raw = data.get("excluded_tags", []) or []
    excluded_tags = tuple(str(t) for t in excluded_tags_raw)

    return Config(
        yield_threshold_apr=yield_threshold,
        min_price=min_price,
        max_days_to_resolution=max_days,
        model=str(data["model"]),
        min_liquidity=min_liquidity,
        min_volume=min_volume,
        recommended_min_edge_pct=recommended_min_edge_pct,
        recommended_max_risk_score=recommended_max_risk_score,
        excluded_tags=excluded_tags,
    )
