"""Tests for HTML and JSON rendering."""
import json
from pathlib import Path

import pytest

from scout.config import Config
from scout.db import connect, init_schema, upsert_market
from scout.judge import Judgment, store_judgment
from scout.render import collect_rows, duration_bucket, enrich_rows, render_report
from scout.score import Candidate


def _cfg() -> Config:
    return Config(
        yield_threshold_apr=0.05,
        min_price=0.90,
        max_days_to_resolution=730,
        model="claude-haiku-4-5",
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
