"""SQLite schema and helpers for polymarket-scout."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    id              TEXT PRIMARY KEY,
    platform        TEXT NOT NULL DEFAULT 'polymarket',
    slug            TEXT NOT NULL,
    question        TEXT NOT NULL,
    tags_json       TEXT,
    primary_tag     TEXT,
    end_date        TEXT,
    outcomes_json   TEXT,
    yes_price       REAL,
    no_price        REAL,
    volume          REAL,
    liquidity       REAL,
    description     TEXT,
    raw_json        TEXT,
    fetched_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS judgments (
    market_id           TEXT NOT NULL,
    side                TEXT NOT NULL,
    price               REAL NOT NULL,
    yield_apr           REAL NOT NULL,
    days_to_resolution  INTEGER NOT NULL,
    risk_score          INTEGER,
    risk_rationale      TEXT,
    summary             TEXT,
    subjective_p_win    REAL,
    model               TEXT NOT NULL,
    judged_at           TEXT NOT NULL,
    PRIMARY KEY (market_id, side, model),
    FOREIGN KEY (market_id) REFERENCES markets(id)
);

CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    n_fetched       INTEGER,
    n_candidates    INTEGER,
    n_judged        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_markets_end_date ON markets(end_date);
CREATE INDEX IF NOT EXISTS idx_judgments_yield ON judgments(yield_apr DESC);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _parse_price(outcome_prices: str | None, index: int) -> float | None:
    if not outcome_prices:
        return None
    try:
        parsed = json.loads(outcome_prices)
        return float(parsed[index])
    except (json.JSONDecodeError, IndexError, TypeError, ValueError):
        return None


def _primary_tag(tags: Any) -> str | None:
    if not tags:
        return None
    first = tags[0]
    if isinstance(first, dict):
        return first.get("label")
    if isinstance(first, str):
        return first
    return None


def upsert_market(
    conn: sqlite3.Connection, market: dict, fetched_at: str
) -> None:
    tags = market.get("tags") or []
    conn.execute(
        """
        INSERT INTO markets (
            id, platform, slug, question, tags_json, primary_tag, end_date,
            outcomes_json, yes_price, no_price, volume, liquidity,
            description, raw_json, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            platform=excluded.platform,
            slug=excluded.slug,
            question=excluded.question,
            tags_json=excluded.tags_json,
            primary_tag=excluded.primary_tag,
            end_date=excluded.end_date,
            outcomes_json=excluded.outcomes_json,
            yes_price=excluded.yes_price,
            no_price=excluded.no_price,
            volume=excluded.volume,
            liquidity=excluded.liquidity,
            description=excluded.description,
            raw_json=excluded.raw_json,
            fetched_at=excluded.fetched_at
        """,
        (
            market["id"],
            market.get("platform", "polymarket"),
            market.get("slug", ""),
            market.get("question", ""),
            json.dumps(tags),
            _primary_tag(tags),
            market.get("endDate"),
            market.get("outcomes"),
            _parse_price(market.get("outcomePrices"), 0),
            _parse_price(market.get("outcomePrices"), 1),
            market.get("volume"),
            market.get("liquidity"),
            market.get("description"),
            json.dumps(market),
            fetched_at,
        ),
    )
    conn.commit()


def get_market(conn: sqlite3.Connection, market_id: str) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM markets WHERE id = ?", (market_id,))
    return cur.fetchone()


def start_run(conn: sqlite3.Connection, started_at: str) -> int:
    cur = conn.execute(
        "INSERT INTO runs (started_at) VALUES (?)", (started_at,)
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    finished_at: str,
    n_fetched: int,
    n_candidates: int,
    n_judged: int,
) -> None:
    conn.execute(
        """
        UPDATE runs
           SET finished_at = ?, n_fetched = ?, n_candidates = ?, n_judged = ?
         WHERE id = ?
        """,
        (finished_at, n_fetched, n_candidates, n_judged, run_id),
    )
    conn.commit()
