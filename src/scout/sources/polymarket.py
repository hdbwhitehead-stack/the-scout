"""Polymarket Gamma API client."""
from __future__ import annotations

import httpx

GAMMA_URL = "https://gamma-api.polymarket.com/markets"


def fetch_polymarket(
    client: httpx.Client | None = None,
    page_size: int = 500,
) -> list[dict]:
    """Fetch all active, open markets from Polymarket Gamma API.

    Paginates via offset until the API returns an empty page. Each returned
    market dict is normalized so its ``id`` is platform-prefixed
    (``polymarket:<gamma id>``) and ``platform`` is set to ``"polymarket"``.
    """
    own_client = client is None
    if client is None:
        client = httpx.Client(timeout=30.0)

    try:
        all_markets: list[dict] = []
        offset = 0
        while True:
            response = client.get(
                GAMMA_URL,
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": page_size,
                    "offset": offset,
                },
            )
            if response.status_code == 422:
                break
            response.raise_for_status()
            page = response.json()
            if not page:
                break
            for market in page:
                market["id"] = f"polymarket:{market['id']}"
                market["platform"] = "polymarket"
                all_markets.append(market)
            offset += page_size
        return all_markets
    finally:
        if own_client:
            client.close()
