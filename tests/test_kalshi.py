"""Tests for the Kalshi API adapter."""
import json
from pathlib import Path

import httpx

from scout.sources.kalshi import _normalize, fetch_kalshi

FIXTURE = Path(__file__).parent / "fixtures" / "kalshi_response.json"


def test_normalize_maps_kalshi_fields() -> None:
    fixture = json.loads(FIXTURE.read_text())
    km = fixture["markets"][0]
    norm = _normalize(km)

    assert norm["id"] == "kalshi:KXFED-24DEC-RAISE"
    assert norm["slug"] == "KXFED-24DEC-RAISE"
    assert norm["platform"] == "kalshi"
    assert norm["question"] == km["title"]
    assert norm["tags"] == [{"label": "Economics"}]
    assert norm["outcomes"] == '["Yes", "No"]'

    prices = json.loads(norm["outcomePrices"])
    # yes_ask=6 cents -> 0.06, no_ask=96 cents -> 0.96
    assert float(prices[0]) == 0.06
    assert float(prices[1]) == 0.96

    # volume/open_interest are cents → dollars
    assert norm["volume"] == 12345.0
    assert norm["liquidity"] == 450000.0

    # rules_secondary is empty → description = rules_primary only
    assert norm["description"] == km["rules_primary"]

    # endDate prefers the earlier of close_time / expected_expiration_time
    assert norm["endDate"] == "2024-12-18T19:00:00Z"


def test_normalize_handles_missing_prices_and_secondary_rules() -> None:
    km = {
        "ticker": "X-1",
        "title": "Test",
        "category": "Politics",
        "rules_primary": "primary",
        "rules_secondary": "secondary detail",
        "close_time": "2025-01-01T00:00:00Z",
    }
    norm = _normalize(km)
    assert norm["outcomePrices"] is None
    assert norm["description"] == "primary\nsecondary detail"
    assert norm["volume"] == 0
    assert norm["liquidity"] == 0
    assert norm["endDate"] == "2025-01-01T00:00:00Z"


def test_fetch_kalshi_paginates_until_cursor_empty() -> None:
    page1 = {
        "markets": [
            {
                "ticker": "A-1",
                "title": "first",
                "yes_ask": 50,
                "no_ask": 50,
                "category": "Sports",
                "volume": 100,
                "open_interest": 200,
            }
        ],
        "cursor": "abc",
    }
    page2 = {
        "markets": [
            {
                "ticker": "B-1",
                "title": "second",
                "yes_ask": 30,
                "no_ask": 70,
                "category": "Politics",
                "volume": 0,
                "open_interest": 0,
            }
        ],
        "cursor": "",
    }
    pages = [page1, page2]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = calls["n"]
        calls["n"] += 1
        return httpx.Response(200, json=pages[idx])

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    result = fetch_kalshi(client=client, page_size=200)
    assert calls["n"] == 2
    assert [r["id"] for r in result] == ["kalshi:A-1", "kalshi:B-1"]
    assert all(r["platform"] == "kalshi" for r in result)
