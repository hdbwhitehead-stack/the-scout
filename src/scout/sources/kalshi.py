"""Kalshi prediction-market API client."""
from __future__ import annotations

import json

import httpx

KALSHI_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"


def _normalize(km: dict) -> dict:
    """Map a Kalshi market dict into our unified market shape."""
    yes_ask = km.get("yes_ask")
    no_ask = km.get("no_ask")
    prices = None
    if yes_ask is not None and no_ask is not None:
        prices = json.dumps([f"{yes_ask / 100:.4f}", f"{no_ask / 100:.4f}"])

    desc_parts = [
        km.get("rules_primary") or "",
        km.get("rules_secondary") or "",
    ]
    description = "\n".join(p for p in desc_parts if p).strip() or None

    close = km.get("close_time")
    expected = km.get("expected_expiration_time")
    if close and expected:
        end_date = min(close, expected)
    else:
        end_date = close or expected

    return {
        "id": f"kalshi:{km['ticker']}",
        "slug": km["ticker"],
        "question": km.get("title", ""),
        "tags": [{"label": km["category"]}] if km.get("category") else [],
        "endDate": end_date,
        "outcomes": '["Yes", "No"]',
        "outcomePrices": prices,
        "volume": (km.get("volume") or 0) / 100,
        "liquidity": (km.get("open_interest") or 0) / 100,
        "description": description,
        "platform": "kalshi",
    }


def fetch_kalshi(
    client: httpx.Client | None = None,
    page_size: int = 200,
) -> list[dict]:
    """Fetch all open markets from Kalshi.

    Paginates via the API's ``cursor`` field until empty/null. Returns a list
    of normalized market dicts ready for ``upsert_market``.
    """
    own = client is None
    if client is None:
        client = httpx.Client(timeout=30.0)
    try:
        out: list[dict] = []
        cursor = ""
        while True:
            params: dict = {"status": "open", "limit": page_size}
            if cursor:
                params["cursor"] = cursor
            r = client.get(KALSHI_URL, params=params)
            r.raise_for_status()
            data = r.json()
            markets = data.get("markets", [])
            out.extend(_normalize(m) for m in markets)
            cursor = data.get("cursor") or ""
            if not cursor:
                break
        return out
    finally:
        if own:
            client.close()
