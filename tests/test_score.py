"""Tests for yield math and candidate filtering."""
from datetime import date

import pytest

from scout.config import Config
from scout.score import Candidate, score_market


@pytest.fixture
def cfg() -> Config:
    return Config(
        yield_threshold_apr=0.05,
        min_price=0.90,
        max_days_to_resolution=730,
        model="claude-haiku-4-5",
    )


def _market(yes: float, no: float, end_date: str) -> dict:
    return {
        "id": "m1",
        "slug": "test",
        "question": "Test?",
        "end_date": end_date,
        "yes_price": yes,
        "no_price": no,
    }


def test_score_market_no_side_qualifies(cfg: Config) -> None:
    # NO at $0.94, 220 days out → APR = (0.06/0.94) * (365/220) ≈ 10.6%
    today = date(2026, 5, 23)
    market = _market(yes=0.06, no=0.94, end_date="2026-12-29T23:59:59Z")
    cand = score_market(market, today, cfg)
    assert cand is not None
    assert cand.side == "NO"
    assert cand.price == 0.94
    assert cand.days_to_resolution == 220
    assert cand.yield_apr == pytest.approx(0.1059, abs=1e-3)


def test_score_market_yes_side_qualifies(cfg: Config) -> None:
    today = date(2026, 5, 23)
    market = _market(yes=0.95, no=0.05, end_date="2027-05-23T00:00:00Z")
    cand = score_market(market, today, cfg)
    assert cand is not None
    assert cand.side == "YES"
    assert cand.price == 0.95


def test_score_market_below_price_floor_rejected(cfg: Config) -> None:
    today = date(2026, 5, 23)
    market = _market(yes=0.50, no=0.50, end_date="2026-12-29T23:59:59Z")
    assert score_market(market, today, cfg) is None


def test_score_market_below_yield_floor_rejected(cfg: Config) -> None:
    # NO at $0.99, 365 days → APR ≈ 1% — below 5% floor
    today = date(2026, 5, 23)
    market = _market(yes=0.01, no=0.99, end_date="2027-05-23T00:00:00Z")
    assert score_market(market, today, cfg) is None


def test_score_market_too_far_out_rejected(cfg: Config) -> None:
    today = date(2026, 5, 23)
    # 800 days > 730 cap
    market = _market(yes=0.05, no=0.95, end_date="2028-07-31T23:59:59Z")
    assert score_market(market, today, cfg) is None


def test_score_market_already_resolved_rejected(cfg: Config) -> None:
    today = date(2026, 5, 23)
    market = _market(yes=0.05, no=0.95, end_date="2026-05-22T00:00:00Z")
    assert score_market(market, today, cfg) is None


def test_score_market_missing_end_date_rejected(cfg: Config) -> None:
    today = date(2026, 5, 23)
    market = _market(yes=0.05, no=0.95, end_date=None)
    assert score_market(market, today, cfg) is None
