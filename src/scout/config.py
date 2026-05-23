"""Configuration loader for polymarket-scout."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    yield_threshold_apr: float
    min_price: float
    max_days_to_resolution: int
    model: str


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

    return Config(
        yield_threshold_apr=yield_threshold,
        min_price=min_price,
        max_days_to_resolution=max_days,
        model=str(data["model"]),
    )
