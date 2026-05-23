"""Tests for SQLite schema and helpers."""
from pathlib import Path

from scout.db import connect, init_schema, upsert_market, get_market


def test_init_schema_creates_tables(tmp_db: Path) -> None:
    conn = connect(tmp_db)
    init_schema(conn)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in cur.fetchall()]
    assert "markets" in tables
    assert "judgments" in tables
    assert "runs" in tables


def test_upsert_market_inserts_then_updates(tmp_db: Path, sample_market: dict) -> None:
    conn = connect(tmp_db)
    init_schema(conn)
    upsert_market(conn, sample_market, fetched_at="2026-05-23T00:00:00Z")
    upsert_market(conn, sample_market, fetched_at="2026-05-24T00:00:00Z")
    cur = conn.execute("SELECT COUNT(*) FROM markets")
    assert cur.fetchone()[0] == 1
    row = get_market(conn, sample_market["id"])
    assert row is not None
    assert row["question"] == sample_market["question"]
    assert row["fetched_at"] == "2026-05-24T00:00:00Z"
    assert row["yes_price"] == 0.06
    assert row["no_price"] == 0.94
    assert row["primary_tag"] == "Religion"
