"""Tests for the Polymarket Gamma API fetcher."""
import json
from pathlib import Path

import httpx
import pytest

from scout.db import connect, get_market, init_schema
from scout.fetch import store_markets
from scout.sources.polymarket import fetch_polymarket

FIXTURE = Path(__file__).parent / "fixtures" / "gamma_response.json"


def test_fetch_polymarket_paginates_until_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = json.loads(FIXTURE.read_text())
    pages = [fixture, []]
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = call_count["n"]
        call_count["n"] += 1
        # Deep-copy via JSON round-trip so the adapter's in-place id rewrite
        # doesn't bleed across pages on retries.
        return httpx.Response(200, json=json.loads(json.dumps(pages[idx])))

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    result = fetch_polymarket(client=client, page_size=500)
    assert len(result) == 2
    assert result[0]["id"] == "polymarket:0x111"
    assert result[0]["platform"] == "polymarket"
    assert call_count["n"] == 2


def test_store_markets_writes_all(tmp_db: Path) -> None:
    fixture = json.loads(FIXTURE.read_text())
    # Simulate what the adapter does before handing off to store_markets.
    for m in fixture:
        m["id"] = f"polymarket:{m['id']}"
        m["platform"] = "polymarket"
    conn = connect(tmp_db)
    init_schema(conn)
    n = store_markets(conn, fixture, fetched_at="2026-05-23T00:00:00Z")
    assert n == 2
    row = get_market(conn, "polymarket:0x111")
    assert row is not None
    assert row["primary_tag"] == "Politics"
    assert row["no_price"] == 0.96
    assert row["platform"] == "polymarket"
