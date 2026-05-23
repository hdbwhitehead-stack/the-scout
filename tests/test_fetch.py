"""Tests for the Polymarket Gamma API fetcher."""
import json
from pathlib import Path

import httpx
import pytest

from scout.db import connect, get_market, init_schema
from scout.fetch import fetch_markets, store_markets

FIXTURE = Path(__file__).parent / "fixtures" / "gamma_response.json"


def test_fetch_markets_paginates_until_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = json.loads(FIXTURE.read_text())
    pages = [fixture, []]
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = call_count["n"]
        call_count["n"] += 1
        return httpx.Response(200, json=pages[idx])

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    result = fetch_markets(client=client, page_size=500)
    assert len(result) == 2
    assert result[0]["id"] == "0x111"
    assert call_count["n"] == 2


def test_store_markets_writes_all(tmp_db: Path) -> None:
    fixture = json.loads(FIXTURE.read_text())
    conn = connect(tmp_db)
    init_schema(conn)
    n = store_markets(conn, fixture, fetched_at="2026-05-23T00:00:00Z")
    assert n == 2
    row = get_market(conn, "0x111")
    assert row is not None
    assert row["primary_tag"] == "Politics"
    assert row["no_price"] == 0.96
