"""Tests for HTML and JSON rendering."""
import json
from pathlib import Path

import pytest

from scout.config import Config
from scout.db import connect, init_schema, upsert_market
from scout.judge import Judgment, store_judgment
from scout.render import (
    RISK_HAIRCUT,
    _adjust_p_win,
    collect_rows,
    duration_bucket,
    enrich_rows,
    render_report,
)
from scout.score import Candidate


def _cfg() -> Config:
    return Config(
        yield_threshold_apr=0.05,
        min_price=0.90,
        max_days_to_resolution=730,
        model="claude-haiku-4-5",
        min_liquidity=100.0,
        min_volume=1000.0,
        recommended_min_edge_pct=3.0,
        recommended_max_risk_score=2,
        excluded_tags=(),
    )


def _candidate(sample_market: dict) -> Candidate:
    return Candidate(
        market_id=sample_market["id"],
        side="NO",
        price=0.94,
        days_to_resolution=220,
        yield_apr=0.106,
    )


def _seed_judged(conn, sample_market):
    upsert_market(conn, sample_market, fetched_at="2026-05-23T00:00:00Z")
    cand = _candidate(sample_market)
    judgment = Judgment(
        risk_score=5,
        risk_rationale="Resolution depends on supernatural verification — no clean arbiter.",
        summary="Bet NO on Jesus resurrection by 2026, paying ~6.4% absolute (10.6% APR).",
        subjective_p_win=0.99,
    )
    store_judgment(
        conn, cand, judgment, model="claude-haiku-4-5", judged_at="2026-05-23T01:00:00Z"
    )
    return cand


def test_duration_bucket_boundaries() -> None:
    assert duration_bucket(1) == "≤90d"
    assert duration_bucket(90) == "≤90d"
    assert duration_bucket(91) == "91–365d"
    assert duration_bucket(365) == "91–365d"
    assert duration_bucket(366) == "366–730d"
    assert duration_bucket(730) == "366–730d"


def test_collect_rows_joins_markets_and_judgments(tmp_db: Path, sample_market: dict) -> None:
    conn = connect(tmp_db)
    init_schema(conn)
    cand = _seed_judged(conn, sample_market)
    rows = collect_rows(conn, [cand], model="claude-haiku-4-5")
    assert len(rows) == 1
    row = rows[0]
    assert row["question"] == sample_market["question"]
    assert row["side"] == "NO"
    assert row["risk_score"] == 5
    assert row["slug"] == "jesus-resurrection-2026"
    assert row["primary_tag"] == "Religion"


def test_collect_rows_includes_unjudged_candidates(tmp_db: Path, sample_market: dict) -> None:
    conn = connect(tmp_db)
    init_schema(conn)
    upsert_market(conn, sample_market, fetched_at="2026-05-23T00:00:00Z")
    cand = _candidate(sample_market)
    # Note: NOT storing a judgment
    rows = collect_rows(conn, [cand], model="claude-haiku-4-5")
    assert len(rows) == 1
    row = rows[0]
    assert row["question"] == sample_market["question"]
    assert row["side"] == "NO"
    assert row["price"] == pytest.approx(0.94)
    assert row["yield_apr"] == pytest.approx(0.106)
    assert row["days_to_resolution"] == 220
    assert row["risk_score"] is None
    assert row["risk_rationale"] is None
    assert row["summary"] is None


def test_enrich_rows_adds_payoff_and_bucket(tmp_db: Path, sample_market: dict) -> None:
    conn = connect(tmp_db)
    init_schema(conn)
    cand = _seed_judged(conn, sample_market)
    rows = enrich_rows(collect_rows(conn, [cand], model="claude-haiku-4-5"))
    row = rows[0]
    # absolute_payoff_pct = (1 - 0.94) * 100 = 6.0
    assert row["absolute_payoff_pct"] == pytest.approx(6.0, abs=1e-6)
    assert row["duration_bucket"] == "91–365d"


def test_enrich_rows_computes_edge_and_kelly() -> None:
    # risk_score=1 → 0pp haircut, so adjusted == raw.
    rows = [{
        "price": 0.85,
        "days_to_resolution": 100,
        "subjective_p_win": 0.95,
        "risk_score": 1,
    }]
    enriched = enrich_rows(rows)
    r = enriched[0]
    # edge: (0.95 - 0.85) * 100 = 10.0
    assert r["edge_pct"] == pytest.approx(10.0, abs=1e-6)
    # Kelly: b = 0.15/0.85 ≈ 0.1765
    #   f = (0.1765 * 0.95 - 0.05) / 0.1765 ≈ 0.6667
    assert r["kelly_fraction"] == pytest.approx(0.6667, abs=1e-3)


def test_enrich_rows_handles_missing_subjective_p_win() -> None:
    rows = [{"price": 0.94, "days_to_resolution": 200}]
    enriched = enrich_rows(rows)
    assert enriched[0]["edge_pct"] is None
    assert enriched[0]["kelly_fraction"] is None
    assert enriched[0]["suggested_size_pct"] is None
    assert enriched[0]["adjusted_p_win"] is None


def test_enrich_rows_suggested_size_capped_at_one_percent() -> None:
    # Large Kelly: 0.25 * 0.67 ≈ 0.167, hits the 1% cap.
    rows = [{
        "price": 0.85,
        "days_to_resolution": 100,
        "subjective_p_win": 0.95,
        "risk_score": 1,
    }]
    enriched = enrich_rows(rows)
    assert enriched[0]["suggested_size_pct"] == pytest.approx(1.0, abs=1e-6)


def test_enrich_rows_suggested_size_quarter_kelly_when_below_cap() -> None:
    # Tiny edge → small Kelly → 0.25 * Kelly stays under the 1% cap.
    # price=0.97, p_win=0.971 → b ≈ 0.0309, f ≈ 0.0326, 0.25 * f ≈ 0.00815 → 0.81%
    rows = [{
        "price": 0.97,
        "days_to_resolution": 100,
        "subjective_p_win": 0.971,
        "risk_score": 1,
    }]
    enriched = enrich_rows(rows)
    r = enriched[0]
    assert r["suggested_size_pct"] is not None
    assert r["suggested_size_pct"] < 1.0
    assert r["suggested_size_pct"] == pytest.approx(0.25 * r["kelly_fraction"] * 100, abs=1e-9)


def test_enrich_rows_suggested_size_zero_when_no_edge() -> None:
    rows = [{
        "price": 0.95,
        "days_to_resolution": 100,
        "subjective_p_win": 0.80,
        "risk_score": 1,
    }]
    enriched = enrich_rows(rows)
    assert enriched[0]["suggested_size_pct"] == pytest.approx(0.0, abs=1e-9)


def test_kelly_clamped_to_zero_when_no_edge() -> None:
    # Subjective P below market price → negative edge → Kelly clamps to 0
    rows = [{
        "price": 0.95,
        "days_to_resolution": 100,
        "subjective_p_win": 0.80,
        "risk_score": 1,
    }]
    enriched = enrich_rows(rows)
    assert enriched[0]["kelly_fraction"] == 0.0


# --- Risk-score haircut (auditable, code-side) ----------------------------


def test_adjust_p_win_returns_none_when_inputs_missing() -> None:
    assert _adjust_p_win(None, 1) is None
    assert _adjust_p_win(0.9, None) is None
    assert _adjust_p_win(None, None) is None


@pytest.mark.parametrize(
    "risk_score, expected_haircut",
    [(1, 0.00), (2, 0.00), (3, 0.05), (4, 0.10), (5, 0.20)],
)
def test_adjust_p_win_haircut_table(risk_score: int, expected_haircut: float) -> None:
    raw = 0.97
    adj = _adjust_p_win(raw, risk_score)
    assert adj == pytest.approx(raw - expected_haircut, abs=1e-9)
    # Cross-check the published RISK_HAIRCUT table matches what's applied.
    assert RISK_HAIRCUT[risk_score] == pytest.approx(expected_haircut, abs=1e-9)


def test_adjust_p_win_floors_at_zero() -> None:
    # raw - haircut would go negative; should clamp to 0.0.
    assert _adjust_p_win(0.10, 5) == pytest.approx(0.0, abs=1e-9)


def test_enrich_rows_uses_adjusted_p_win_for_edge_and_kelly() -> None:
    # risk_score=5 → 20pp haircut; raw 0.99 → adjusted 0.79.
    # price=0.85 → edge = (0.79 - 0.85) * 100 = -6.0pp.
    rows = [{
        "price": 0.85,
        "days_to_resolution": 100,
        "subjective_p_win": 0.99,
        "risk_score": 5,
    }]
    enriched = enrich_rows(rows)
    r = enriched[0]
    assert r["adjusted_p_win"] == pytest.approx(0.79, abs=1e-9)
    assert r["edge_pct"] == pytest.approx(-6.0, abs=1e-6)
    # Negative edge → Kelly clamped to 0.
    assert r["kelly_fraction"] == 0.0


def test_enrich_rows_seeded_risk5_uses_haircut(tmp_db: Path, sample_market: dict) -> None:
    # The _seed_judged helper stores risk_score=5, subjective_p_win=0.99
    # against a candidate with price=0.94. After the 20pp haircut the
    # adjusted P(win) is 0.79, so edge = (0.79 - 0.94) * 100 = -15.0pp.
    conn = connect(tmp_db)
    init_schema(conn)
    cand = _seed_judged(conn, sample_market)
    rows = enrich_rows(collect_rows(conn, [cand], model="claude-haiku-4-5"))
    r = rows[0]
    assert r["subjective_p_win"] == pytest.approx(0.99, abs=1e-9)
    assert r["adjusted_p_win"] == pytest.approx(0.79, abs=1e-9)
    assert r["edge_pct"] == pytest.approx(-15.0, abs=1e-6)
    assert r["kelly_fraction"] == 0.0


def test_render_report_writes_html_and_json(tmp_db: Path, tmp_path: Path, sample_market: dict) -> None:
    conn = connect(tmp_db)
    init_schema(conn)
    cand = _seed_judged(conn, sample_market)
    out_dir = tmp_path / "docs"
    out_dir.mkdir()
    render_report(
        conn,
        [cand],
        cfg=_cfg(),
        out_dir=out_dir,
        generated_at="2026-05-23T02:00:00Z",
    )
    html = (out_dir / "index.html").read_text()
    # template chrome
    assert "Polymarket Scout" in html
    assert "The <em>Scout</em>" in html
    # injected timestamp
    assert "2026-05-23T02:00:00Z" in html
    # data made it through
    assert "Jesus" in html
    assert "Religion" in html
    # JS data constant exists
    assert "const DATA =" in html

    data = json.loads((out_dir / "data.json").read_text())
    assert data["generated_at"] == "2026-05-23T02:00:00Z"
    assert len(data["rows"]) == 1
    row = data["rows"][0]
    assert row["risk_score"] == 5
    assert row["side"] == "NO"
    assert row["duration_bucket"] == "91–365d"
    assert row["absolute_payoff_pct"] == pytest.approx(6.0, abs=1e-6)
