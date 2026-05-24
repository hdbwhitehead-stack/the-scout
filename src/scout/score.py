"""Yield math and candidate filtering."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from scout.config import Config

Side = Literal["YES", "NO"]


@dataclass(frozen=True)
class Candidate:
    market_id: str
    side: Side
    price: float
    days_to_resolution: int
    yield_apr: float


def _parse_end_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def score_market(market: dict, today: date, cfg: Config) -> Candidate | None:
    end = _parse_end_date(market.get("end_date"))
    if end is None:
        return None

    days = (end - today).days
    if days <= 0 or days > cfg.max_days_to_resolution:
        return None

    yes = market.get("yes_price")
    no = market.get("no_price")
    if yes is None or no is None:
        return None

    if yes >= no:
        side: Side = "YES"
        price = yes
    else:
        side = "NO"
        price = no

    if price < cfg.min_price:
        return None

    liq = market.get("liquidity") or 0.0
    vol = market.get("volume") or 0.0
    if liq < cfg.min_liquidity and vol < cfg.min_volume:
        return None

    yield_apr = ((1 - price) / price) * (365 / days)
    if yield_apr < cfg.yield_threshold_apr:
        return None

    primary_tag = market.get("primary_tag")
    if primary_tag and cfg.excluded_tags:
        excluded_lower = {t.lower() for t in cfg.excluded_tags}
        if str(primary_tag).lower() in excluded_lower:
            return None

    return Candidate(
        market_id=market["id"],
        side=side,
        price=price,
        days_to_resolution=days,
        yield_apr=yield_apr,
    )
