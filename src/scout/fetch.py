"""Polymarket Gamma API client."""
from __future__ import annotations

import sqlite3

import httpx

from scout.db import upsert_market

GAMMA_URL = "https://gamma-api.polymarket.com/markets"


def fetch_markets(
    client: httpx.Client | None = None,
    page_size: int = 500,
) -> list[dict]:
    """Fetch all active, open markets from Polymarket Gamma API.

    Paginates via offset until the API returns an empty page.
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
            response.raise_for_status()
            page = response.json()
            if not page:
                break
            all_markets.extend(page)
            offset += page_size
        return all_markets
    finally:
        if own_client:
            client.close()


def store_markets(
    conn: sqlite3.Connection, markets: list[dict], fetched_at: str
) -> int:
    """Upsert each market into the database. Returns count written."""
    for market in markets:
        upsert_market(conn, market, fetched_at=fetched_at)
    return len(markets)
