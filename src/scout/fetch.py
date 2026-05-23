"""Multi-source market fetcher.

This module is intentionally thin: real per-source logic lives under
``scout.sources``. The orchestrator simply concatenates results from every
configured adapter and writes them via :func:`store_markets`.
"""
from __future__ import annotations

import sqlite3

from scout.db import upsert_market
from scout.sources.kalshi import fetch_kalshi
from scout.sources.polymarket import fetch_polymarket


def fetch_all_sources() -> list[dict]:
    """Fetch from every configured source. Returns combined normalized markets."""
    out: list[dict] = []
    out.extend(fetch_polymarket())
    out.extend(fetch_kalshi())
    return out


def store_markets(
    conn: sqlite3.Connection, markets: list[dict], fetched_at: str
) -> int:
    """Upsert each market into the database. Returns count written."""
    for market in markets:
        upsert_market(conn, market, fetched_at=fetched_at)
    return len(markets)
