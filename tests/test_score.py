"""Tests for yield math and candidate filtering."""
from datetime import date

import pytest

from scout.config import Config
from scout.score import Candidate, score_market


@pytest.fixture
def cfg() -> Config:
    return Config(
        yield_threshold_apr=0.05,
        min_price=0.85,
        max_days_to_resolution=730,
        model="claude-haiku-4-5",
        min_liquidity=100.0,
        min_volume=1000.0,
        recommended_min_edge_pct=3.0,
        recommended_max_risk_score=2,
        excluded_tags=("Religion",),
    )


def _market(yes: float, no: float, end_date: str) -> dict:
    return {
        "id": "m1",
        "slug": "test",
        "question": "Test?",
        "end_date": end_date,
        "yes_price": yes,
        "no_price": no,
        "liquidity": 10000.0,
        "volume": 100000.0,
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


def test_score_market_dead_market_rejected(cfg: Config) -> None:
    """Both liquidity and volume below floor → skipped."""
    today = date(2026, 5, 23)
    market = _market(yes=0.05, no=0.95, end_date="2026-12-29T23:59:59Z")
    market["liquidity"] = 10.0  # below 100 default
    market["volume"] = 50.0      # below 1000 default
    assert score_market(market, today, cfg) is None


def test_score_market_thin_book_but_active_history_kept(cfg: Config) -> None:
    """Low liquidity OK if volume shows historical interest."""
    today = date(2026, 5, 23)
    market = _market(yes=0.05, no=0.95, end_date="2026-12-29T23:59:59Z")
    market["liquidity"] = 10.0    # below floor
    market["volume"] = 50000.0     # well above floor
    cand = score_market(market, today, cfg)
    assert cand is not None


def test_score_market_zero_volume_but_fresh_book_kept(cfg: Config) -> None:
    """Brand-new market with $0 historical volume but tradeable book is kept."""
    today = date(2026, 5, 23)
    market = _market(yes=0.05, no=0.95, end_date="2026-12-29T23:59:59Z")
    market["liquidity"] = 500.0   # above floor
    market["volume"] = 0.0
    cand = score_market(market, today, cfg)
    assert cand is not None


def test_score_market_excluded_tag_rejected(cfg: Config) -> None:
    """Markets whose primary_tag is in excluded_tags are dropped after all other gates."""
    today = date(2026, 5, 23)
    market = _market(yes=0.05, no=0.95, end_date="2026-12-29T23:59:59Z")
    market["primary_tag"] = "Religion"
    assert score_market(market, today, cfg) is None


def test_score_market_excluded_tag_matches_case_insensitive(cfg: Config) -> None:
    today = date(2026, 5, 23)
    market = _market(yes=0.05, no=0.95, end_date="2026-12-29T23:59:59Z")
    market["primary_tag"] = "religion"  # lower case still matches "Religion"
    assert score_market(market, today, cfg) is None


def test_score_market_non_excluded_tag_kept(cfg: Config) -> None:
    today = date(2026, 5, 23)
    market = _market(yes=0.05, no=0.95, end_date="2026-12-29T23:59:59Z")
    market["primary_tag"] = "Politics"
    cand = score_market(market, today, cfg)
    assert cand is not None
