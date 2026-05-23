# Polymarket Scout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI tool that scrapes Polymarket markets, identifies high-probability/low-payoff opportunities exceeding a yield threshold, has Claude Haiku judge each one for resolution risk, and outputs a sortable static HTML report deployable to GitHub Pages.

**Architecture:** Four-stage cached pipeline (`fetch` → `score` → `judge` → `render`), each stage writes to a single SQLite database. Pure Python, no web framework, no build step. Caching avoids re-paying LLM costs when only the HTML changes.

**Tech Stack:** Python 3.12+, `uv` for env management, `httpx`, SQLite (stdlib), `anthropic` SDK with Claude Haiku 4.5, `jinja2`, `typer`, `pytest`.

**Working directory for all commands:** `/Users/harry/Documents/Claude/polymarket-scout/`

---

## File Structure

```
polymarket-scout/
├── pyproject.toml                    # uv project config + deps
├── config.toml                       # user-tunable thresholds
├── .gitignore                        # scout.db, .venv, __pycache__
├── README.md                         # quick-start
├── scout.db                          # SQLite (gitignored)
├── src/scout/
│   ├── __init__.py
│   ├── config.py                     # load + validate config.toml
│   ├── db.py                         # SQLite schema + connection helpers
│   ├── fetch.py                      # Gamma API client → markets table
│   ├── score.py                      # yield math, candidate filter
│   ├── judge.py                      # Haiku judge agent
│   ├── render.py                     # Jinja2 → docs/index.html + data.json
│   └── cli.py                        # typer entrypoint
├── templates/
│   └── index.html.j2                 # sortable table template
├── docs/                             # GitHub Pages root (generated, committed)
│   ├── index.html
│   ├── data.json
│   └── superpowers/{specs,plans}/    # already exists
└── tests/
    ├── __init__.py
    ├── conftest.py                   # shared fixtures (tmp db, sample market)
    ├── fixtures/
    │   └── gamma_response.json       # recorded API response
    ├── test_config.py
    ├── test_db.py
    ├── test_score.py
    ├── test_fetch.py
    ├── test_judge.py
    └── test_render.py
```

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/scout/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Verify `uv` is installed**

Run: `uv --version`
Expected: prints a version number. If not installed, run `curl -LsSf https://astral.sh/uv/install.sh | sh` first.

- [ ] **Step 2: Initialize git repo**

```bash
cd /Users/harry/Documents/Claude/polymarket-scout
git init
```

Expected: `Initialized empty Git repository in .../polymarket-scout/.git/`

- [ ] **Step 3: Create `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
scout.db
scout.db-journal
.env
.DS_Store
```

- [ ] **Step 4: Create `pyproject.toml`**

```toml
[project]
name = "polymarket-scout"
version = "0.1.0"
description = "Find high-probability/low-payoff Polymarket opportunities"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "anthropic>=0.40",
    "typer>=0.12",
    "jinja2>=3.1",
    "rich>=13.7",
]

[project.scripts]
scout = "scout.cli:app"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/scout"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 5: Create `src/scout/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 6: Create `tests/__init__.py`**

Empty file.

- [ ] **Step 7: Create `tests/conftest.py`**

```python
"""Shared pytest fixtures."""
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Return a path to a fresh, empty SQLite database file."""
    return tmp_path / "scout.db"


@pytest.fixture
def sample_market() -> dict:
    """A representative Gamma API market payload."""
    return {
        "id": "0x123",
        "slug": "jesus-resurrection-2026",
        "question": "Will Jesus Christ be resurrected by Dec 31, 2026?",
        "tags": [{"label": "Religion"}, {"label": "Long Shot"}],
        "endDate": "2026-12-31T23:59:59Z",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.06", "0.94"]',
        "volume": 12345.67,
        "liquidity": 2500.0,
        "description": "Resolves YES if the Vatican or another major Christian authority confirms a resurrection event before Dec 31, 2026.",
    }
```

- [ ] **Step 8: Install dependencies**

Run: `uv sync`
Expected: creates `.venv/`, installs all deps, exits 0.

- [ ] **Step 9: Verify pytest discovers nothing yet but runs cleanly**

Run: `uv run pytest`
Expected: exits 0 with "no tests ran" or "collected 0 items".

- [ ] **Step 10: Commit**

```bash
git add .gitignore pyproject.toml src/scout/__init__.py tests/__init__.py tests/conftest.py uv.lock
git commit -m "chore: scaffold polymarket-scout project"
```

---

### Task 2: Configuration loader

**Files:**
- Create: `config.toml`
- Create: `src/scout/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
"""Tests for the config loader."""
from pathlib import Path

import pytest

from scout.config import Config, load_config


def test_load_config_reads_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
yield_threshold_apr = 0.05
min_price = 0.90
max_days_to_resolution = 730
model = "claude-haiku-4-5"
"""
    )
    cfg = load_config(config_path)
    assert isinstance(cfg, Config)
    assert cfg.yield_threshold_apr == 0.05
    assert cfg.min_price == 0.90
    assert cfg.max_days_to_resolution == 730
    assert cfg.model == "claude-haiku-4-5"


def test_load_config_rejects_negative_threshold(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
yield_threshold_apr = -0.01
min_price = 0.90
max_days_to_resolution = 730
model = "claude-haiku-4-5"
"""
    )
    with pytest.raises(ValueError, match="yield_threshold_apr"):
        load_config(config_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scout.config'`

- [ ] **Step 3: Write `src/scout/config.py`**

```python
"""Configuration loader for polymarket-scout."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    yield_threshold_apr: float
    min_price: float
    max_days_to_resolution: int
    model: str


def load_config(path: Path) -> Config:
    with path.open("rb") as f:
        data = tomllib.load(f)

    yield_threshold = float(data["yield_threshold_apr"])
    if yield_threshold < 0:
        raise ValueError("yield_threshold_apr must be >= 0")

    min_price = float(data["min_price"])
    if not 0 < min_price < 1:
        raise ValueError("min_price must be between 0 and 1 (exclusive)")

    max_days = int(data["max_days_to_resolution"])
    if max_days <= 0:
        raise ValueError("max_days_to_resolution must be > 0")

    return Config(
        yield_threshold_apr=yield_threshold,
        min_price=min_price,
        max_days_to_resolution=max_days,
        model=str(data["model"]),
    )
```

- [ ] **Step 4: Create the real `config.toml` at the project root**

```toml
yield_threshold_apr = 0.05
min_price = 0.90
max_days_to_resolution = 730
model = "claude-haiku-4-5"
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_config.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add config.toml src/scout/config.py tests/test_config.py
git commit -m "feat: add config loader with validation"
```

---

### Task 3: Database schema and helpers

**Files:**
- Create: `src/scout/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_db.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/scout/db.py`**

```python
"""SQLite schema and helpers for polymarket-scout."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    id              TEXT PRIMARY KEY,
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
            id, slug, question, tags_json, primary_tag, end_date,
            outcomes_json, yes_price, no_price, volume, liquidity,
            description, raw_json, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_db.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/scout/db.py tests/test_db.py
git commit -m "feat: add SQLite schema and market upsert"
```

---

### Task 4: Scoring (yield math + candidate filter)

**Files:**
- Create: `src/scout/score.py`
- Create: `tests/test_score.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_score.py`:
```python
"""Tests for yield math and candidate filtering."""
from datetime import date

import pytest

from scout.config import Config
from scout.score import Candidate, score_market


@pytest.fixture
def cfg() -> Config:
    return Config(
        yield_threshold_apr=0.05,
        min_price=0.90,
        max_days_to_resolution=730,
        model="claude-haiku-4-5",
    )


def _market(yes: float, no: float, end_date: str) -> dict:
    return {
        "id": "m1",
        "slug": "test",
        "question": "Test?",
        "end_date": end_date,
        "yes_price": yes,
        "no_price": no,
    }


def test_score_market_no_side_qualifies(cfg: Config) -> None:
    # NO at $0.94, 220 days out → APR = (0.06/0.94) * (365/220) ≈ 10.6%
    today = date(2026, 5, 23)
    market = _market(yes=0.06, no=0.94, end_date="2026-12-29T23:59:59Z")
    cand = score_market(market, today, cfg)
    assert cand is not None
    assert cand.side == "NO"
    assert cand.price == 0.94
    assert cand.days_to_resolution == 220
    assert cand.yield_apr == pytest.approx(0.1059, abs=1e-3)


def test_score_market_yes_side_qualifies(cfg: Config) -> None:
    today = date(2026, 5, 23)
    market = _market(yes=0.95, no=0.05, end_date="2027-05-23T00:00:00Z")
    cand = score_market(market, today, cfg)
    assert cand is not None
    assert cand.side == "YES"
    assert cand.price == 0.95


def test_score_market_below_price_floor_rejected(cfg: Config) -> None:
    today = date(2026, 5, 23)
    market = _market(yes=0.50, no=0.50, end_date="2026-12-29T23:59:59Z")
    assert score_market(market, today, cfg) is None


def test_score_market_below_yield_floor_rejected(cfg: Config) -> None:
    # NO at $0.99, 365 days → APR ≈ 1% — below 5% floor
    today = date(2026, 5, 23)
    market = _market(yes=0.01, no=0.99, end_date="2027-05-23T00:00:00Z")
    assert score_market(market, today, cfg) is None


def test_score_market_too_far_out_rejected(cfg: Config) -> None:
    today = date(2026, 5, 23)
    # 800 days > 730 cap
    market = _market(yes=0.05, no=0.95, end_date="2028-07-31T23:59:59Z")
    assert score_market(market, today, cfg) is None


def test_score_market_already_resolved_rejected(cfg: Config) -> None:
    today = date(2026, 5, 23)
    market = _market(yes=0.05, no=0.95, end_date="2026-05-22T00:00:00Z")
    assert score_market(market, today, cfg) is None


def test_score_market_missing_end_date_rejected(cfg: Config) -> None:
    today = date(2026, 5, 23)
    market = _market(yes=0.05, no=0.95, end_date=None)
    assert score_market(market, today, cfg) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_score.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/scout/score.py`**

```python
"""Yield math and candidate filtering."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from scout.config import Config

Side = Literal["YES", "NO"]


@dataclass(frozen=True)
class Candidate:
    market_id: str
    side: Side
    price: float
    days_to_resolution: int
    yield_apr: float


def _parse_end_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def score_market(market: dict, today: date, cfg: Config) -> Candidate | None:
    end = _parse_end_date(market.get("end_date"))
    if end is None:
        return None

    days = (end - today).days
    if days <= 0 or days > cfg.max_days_to_resolution:
        return None

    yes = market.get("yes_price")
    no = market.get("no_price")
    if yes is None or no is None:
        return None

    if yes >= no:
        side: Side = "YES"
        price = yes
    else:
        side = "NO"
        price = no

    if price < cfg.min_price:
        return None

    yield_apr = ((1 - price) / price) * (365 / days)
    if yield_apr < cfg.yield_threshold_apr:
        return None

    return Candidate(
        market_id=market["id"],
        side=side,
        price=price,
        days_to_resolution=days,
        yield_apr=yield_apr,
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_score.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/scout/score.py tests/test_score.py
git commit -m "feat: add yield scoring and candidate filter"
```

---

### Task 5: Fetch from Polymarket Gamma API

**Files:**
- Create: `tests/fixtures/gamma_response.json`
- Create: `src/scout/fetch.py`
- Create: `tests/test_fetch.py`

- [ ] **Step 1: Create test fixture `tests/fixtures/gamma_response.json`**

```json
[
  {
    "id": "0x111",
    "slug": "first-market",
    "question": "Will the first thing happen by 2026?",
    "tags": [{"label": "Politics"}],
    "endDate": "2026-12-31T23:59:59Z",
    "outcomes": "[\"Yes\", \"No\"]",
    "outcomePrices": "[\"0.04\", \"0.96\"]",
    "volume": 50000,
    "liquidity": 8000,
    "description": "Resolves YES if X happens by EOY 2026."
  },
  {
    "id": "0x222",
    "slug": "second-market",
    "question": "Will the second thing happen?",
    "tags": [{"label": "Crypto"}],
    "endDate": "2027-06-30T23:59:59Z",
    "outcomes": "[\"Yes\", \"No\"]",
    "outcomePrices": "[\"0.55\", \"0.45\"]",
    "volume": 1000,
    "liquidity": 200,
    "description": "Resolves YES on first official confirmation."
  }
]
```

- [ ] **Step 2: Write the failing tests**

`tests/test_fetch.py`:
```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_fetch.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Write `src/scout/fetch.py`**

```python
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
            if len(page) < page_size:
                break
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
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_fetch.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/scout/fetch.py tests/test_fetch.py tests/fixtures/gamma_response.json
git commit -m "feat: add Gamma API fetcher with pagination"
```

---

### Task 6: Judge agent (Claude Haiku)

**Files:**
- Create: `src/scout/judge.py`
- Create: `tests/test_judge.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_judge.py`:
```python
"""Tests for the Claude Haiku judge agent."""
import json
from pathlib import Path
from unittest.mock import MagicMock

from scout.db import connect, init_schema, upsert_market
from scout.judge import Judgment, build_prompt, judge_candidate, store_judgment
from scout.score import Candidate


def test_build_prompt_includes_market_details() -> None:
    market = {
        "id": "m1",
        "question": "Will X happen?",
        "description": "Resolves YES if X is officially announced.",
        "end_date": "2026-12-31",
    }
    cand = Candidate(
        market_id="m1",
        side="NO",
        price=0.94,
        days_to_resolution=200,
        yield_apr=0.10,
    )
    user_msg = build_prompt(market, cand)
    assert "Will X happen?" in user_msg
    assert "Resolves YES if X is officially announced." in user_msg
    assert "NO" in user_msg
    assert "0.94" in user_msg


def test_judge_candidate_parses_model_json() -> None:
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.content = [
        MagicMock(
            text=json.dumps(
                {
                    "risk_score": 2,
                    "risk_rationale": "Resolution criterion is mostly clear.",
                    "summary": "Bet NO that X happens, paying 10% APR.",
                }
            )
        )
    ]
    fake_client.messages.create.return_value = fake_response

    market = {
        "id": "m1",
        "question": "Will X happen?",
        "description": "Resolves YES if X announced.",
        "end_date": "2026-12-31",
    }
    cand = Candidate(
        market_id="m1",
        side="NO",
        price=0.94,
        days_to_resolution=200,
        yield_apr=0.10,
    )

    judgment = judge_candidate(fake_client, "claude-haiku-4-5", market, cand)
    assert isinstance(judgment, Judgment)
    assert judgment.risk_score == 2
    assert "mostly clear" in judgment.risk_rationale
    assert "10% APR" in judgment.summary


def test_store_judgment_writes_row(tmp_db: Path, sample_market: dict) -> None:
    conn = connect(tmp_db)
    init_schema(conn)
    upsert_market(conn, sample_market, fetched_at="2026-05-23T00:00:00Z")
    cand = Candidate(
        market_id=sample_market["id"],
        side="NO",
        price=0.94,
        days_to_resolution=220,
        yield_apr=0.10,
    )
    judgment = Judgment(
        risk_score=2, risk_rationale="Clear.", summary="Bet NO."
    )
    store_judgment(
        conn,
        cand,
        judgment,
        model="claude-haiku-4-5",
        judged_at="2026-05-23T01:00:00Z",
    )
    cur = conn.execute(
        "SELECT * FROM judgments WHERE market_id = ?", (sample_market["id"],)
    )
    row = cur.fetchone()
    assert row is not None
    assert row["risk_score"] == 2
    assert row["yield_apr"] == 0.10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_judge.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/scout/judge.py`**

```python
"""Claude Haiku judge agent."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from scout.score import Candidate

SYSTEM_PROMPT = """You are evaluating Polymarket prediction-market opportunities.

For each market, you receive: the question, the full resolution criteria, the end date, and which side a bettor is considering taking.

Output ONLY a single JSON object (no prose, no code fences) with three fields:

{
  "risk_score": <integer 1 to 5>,
  "risk_rationale": "<one sentence on what makes resolution clean or messy>",
  "summary": "<one sentence on the bet, mentioning side and approximate APR>"
}

Risk score rubric:
  1 — Objective external resolution: government data, official press release, on-chain event, sports score
  2 — Mostly objective with one minor source-of-truth ambiguity
  3 — Some judgement required (e.g. counting media mentions, interpreting a vague threshold)
  4 — Substantially subjective (e.g. operator discretion, hard-to-verify private events)
  5 — Highly subjective or untrustworthy resolution (e.g. social-media poll, religious/supernatural events with no clear arbiter)
"""


@dataclass(frozen=True)
class Judgment:
    risk_score: int
    risk_rationale: str
    summary: str


def build_prompt(market: dict, cand: Candidate) -> str:
    return (
        f"Question: {market.get('question', '')}\n"
        f"Resolution criteria: {market.get('description', '') or '(none provided)'}\n"
        f"End date: {market.get('end_date', '')}\n"
        f"Side under consideration: {cand.side}\n"
        f"Current price for {cand.side}: {cand.price}\n"
        f"Implied yield (APR): {cand.yield_apr:.2%}\n"
        f"Days to resolution: {cand.days_to_resolution}\n"
    )


def _extract_text(response: Any) -> str:
    for block in response.content:
        text = getattr(block, "text", None)
        if text:
            return text
    raise ValueError("Anthropic response contained no text blocks")


def judge_candidate(
    client: Any,
    model: str,
    market: dict,
    cand: Candidate,
) -> Judgment:
    response = client.messages.create(
        model=model,
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(market, cand)}],
    )
    text = _extract_text(response).strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    data = json.loads(text)
    return Judgment(
        risk_score=int(data["risk_score"]),
        risk_rationale=str(data["risk_rationale"]),
        summary=str(data["summary"]),
    )


def store_judgment(
    conn: sqlite3.Connection,
    cand: Candidate,
    judgment: Judgment,
    model: str,
    judged_at: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO judgments (
            market_id, side, price, yield_apr, days_to_resolution,
            risk_score, risk_rationale, summary, model, judged_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cand.market_id,
            cand.side,
            cand.price,
            cand.yield_apr,
            cand.days_to_resolution,
            judgment.risk_score,
            judgment.risk_rationale,
            judgment.summary,
            model,
            judged_at,
        ),
    )
    conn.commit()


def unjudged_candidates(
    conn: sqlite3.Connection,
    candidates: list[Candidate],
    model: str,
) -> list[Candidate]:
    """Return only the candidates that have no judgment yet for this model."""
    out: list[Candidate] = []
    for cand in candidates:
        cur = conn.execute(
            """
            SELECT 1 FROM judgments
             WHERE market_id = ? AND side = ? AND model = ?
            """,
            (cand.market_id, cand.side, model),
        )
        if cur.fetchone() is None:
            out.append(cand)
    return out
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_judge.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/scout/judge.py tests/test_judge.py
git commit -m "feat: add Claude Haiku judge agent with caching"
```

---

### Task 7: HTML report rendering

**Files:**
- Create: `templates/index.html.j2`
- Create: `src/scout/render.py`
- Create: `tests/test_render.py`

- [ ] **Step 1: Create the Jinja2 template `templates/index.html.j2`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Polymarket Scout</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 1200px; margin: 2em auto; padding: 0 1em; color: #1a1a1a; }
  h1 { margin-bottom: 0; }
  .meta { color: #666; font-size: 0.9em; margin-bottom: 1.5em; }
  .controls { margin-bottom: 1em; }
  select { font-size: 1em; padding: 0.3em; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 0.5em; border-bottom: 1px solid #eee; text-align: left;
           vertical-align: top; font-size: 0.92em; }
  th { background: #f6f6f6; cursor: pointer; user-select: none; position: sticky; top: 0; }
  th:hover { background: #ececec; }
  tr.detail { display: none; background: #fafafa; }
  tr.detail td { padding: 0.8em 1em; color: #333; }
  tr.row { cursor: pointer; }
  tr.row:hover { background: #fafafa; }
  .yield { font-weight: 600; color: #0a7; }
  .risk-1 { color: #0a7; }
  .risk-2 { color: #6a3; }
  .risk-3 { color: #c80; }
  .risk-4 { color: #d50; }
  .risk-5 { color: #c00; }
  a { color: #06c; text-decoration: none; }
  a:hover { text-decoration: underline; }
</style>
</head>
<body>
<h1>Polymarket Scout</h1>
<div class="meta">
  Last updated: {{ generated_at }} &middot;
  {{ rows | length }} candidate{{ "" if rows|length == 1 else "s" }} &middot;
  Yield floor {{ "%.1f%%" | format(yield_threshold_apr * 100) }} APR &middot;
  Min price ${{ "%.2f" | format(min_price) }}
</div>
<div class="controls">
  <label>Tag:
    <select id="tagFilter">
      <option value="">All</option>
      {% for tag in tags %}<option value="{{ tag }}">{{ tag }}</option>{% endfor %}
    </select>
  </label>
</div>
<table id="docket">
  <thead>
    <tr>
      <th data-sort="yield_apr" data-numeric="1">Yield APR</th>
      <th data-sort="days_to_resolution" data-numeric="1">Days</th>
      <th data-sort="price" data-numeric="1">Price</th>
      <th data-sort="side">Side</th>
      <th data-sort="risk_score" data-numeric="1">Risk</th>
      <th data-sort="primary_tag">Tag</th>
      <th data-sort="question">Question</th>
    </tr>
  </thead>
  <tbody>
  {% for r in rows %}
    <tr class="row" data-tag="{{ r.primary_tag or '' }}">
      <td class="yield">{{ "%.1f%%" | format(r.yield_apr * 100) }}</td>
      <td>{{ r.days_to_resolution }}</td>
      <td>${{ "%.3f" | format(r.price) }}</td>
      <td>{{ r.side }}</td>
      <td class="risk-{{ r.risk_score or 0 }}">{{ r.risk_score or "—" }}</td>
      <td>{{ r.primary_tag or "" }}</td>
      <td>{{ r.question }}</td>
    </tr>
    <tr class="detail">
      <td colspan="7">
        <strong>Summary:</strong> {{ r.summary or "—" }}<br>
        <strong>Risk:</strong> {{ r.risk_rationale or "—" }}<br>
        <a href="https://polymarket.com/event/{{ r.slug }}" target="_blank" rel="noopener">Open on Polymarket →</a>
      </td>
    </tr>
  {% endfor %}
  </tbody>
</table>
<script>
  // Row expand/collapse
  document.querySelectorAll("tr.row").forEach(row => {
    row.addEventListener("click", () => {
      const next = row.nextElementSibling;
      if (next && next.classList.contains("detail")) {
        next.style.display = next.style.display === "table-row" ? "none" : "table-row";
      }
    });
  });

  // Tag filter
  document.getElementById("tagFilter").addEventListener("change", e => {
    const tag = e.target.value;
    document.querySelectorAll("tr.row").forEach(row => {
      const show = !tag || row.dataset.tag === tag;
      row.style.display = show ? "" : "none";
      const detail = row.nextElementSibling;
      if (detail && detail.classList.contains("detail") && !show) detail.style.display = "none";
    });
  });

  // Column sort
  const tbody = document.querySelector("#docket tbody");
  const rows = Array.from(tbody.querySelectorAll("tr.row"));
  const data = window.SCOUT_DATA || [];
  let sortCol = "yield_apr";
  let sortDir = -1;

  function render() {
    const indexed = rows.map((r, i) => ({ row: r, detail: r.nextElementSibling, d: data[i] }));
    indexed.sort((a, b) => {
      const av = a.d[sortCol], bv = b.d[sortCol];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (av < bv) return -1 * sortDir;
      if (av > bv) return  1 * sortDir;
      return 0;
    });
    indexed.forEach(({ row, detail }) => {
      tbody.appendChild(row);
      if (detail) tbody.appendChild(detail);
    });
  }

  document.querySelectorAll("th[data-sort]").forEach(th => {
    th.addEventListener("click", () => {
      const col = th.dataset.sort;
      if (sortCol === col) sortDir *= -1; else { sortCol = col; sortDir = th.dataset.numeric ? -1 : 1; }
      render();
    });
  });
</script>
<script>
window.SCOUT_DATA = {{ rows_json | safe }};
</script>
</body>
</html>
```

- [ ] **Step 2: Write the failing tests**

`tests/test_render.py`:
```python
"""Tests for HTML and JSON rendering."""
import json
from pathlib import Path

from scout.config import Config
from scout.db import connect, init_schema, upsert_market
from scout.judge import Judgment, store_judgment
from scout.render import collect_rows, render_report
from scout.score import Candidate


def _cfg() -> Config:
    return Config(
        yield_threshold_apr=0.05,
        min_price=0.90,
        max_days_to_resolution=730,
        model="claude-haiku-4-5",
    )


def _seed(conn, sample_market):
    upsert_market(conn, sample_market, fetched_at="2026-05-23T00:00:00Z")
    cand = Candidate(
        market_id=sample_market["id"],
        side="NO",
        price=0.94,
        days_to_resolution=220,
        yield_apr=0.106,
    )
    judgment = Judgment(
        risk_score=5,
        risk_rationale="Resolution depends on supernatural verification — no clean arbiter.",
        summary="Bet NO on Jesus resurrection by 2026, paying ~10.6% APR.",
    )
    store_judgment(conn, cand, judgment, model="claude-haiku-4-5", judged_at="2026-05-23T01:00:00Z")


def test_collect_rows_joins_markets_and_judgments(tmp_db: Path, sample_market: dict) -> None:
    conn = connect(tmp_db)
    init_schema(conn)
    _seed(conn, sample_market)
    rows = collect_rows(conn, model="claude-haiku-4-5")
    assert len(rows) == 1
    row = rows[0]
    assert row["question"] == sample_market["question"]
    assert row["side"] == "NO"
    assert row["risk_score"] == 5
    assert row["slug"] == "jesus-resurrection-2026"
    assert row["primary_tag"] == "Religion"


def test_render_report_writes_html_and_json(tmp_db: Path, tmp_path: Path, sample_market: dict) -> None:
    conn = connect(tmp_db)
    init_schema(conn)
    _seed(conn, sample_market)
    out_dir = tmp_path / "docs"
    out_dir.mkdir()
    render_report(
        conn,
        cfg=_cfg(),
        out_dir=out_dir,
        generated_at="2026-05-23T02:00:00Z",
    )
    html = (out_dir / "index.html").read_text()
    assert "Polymarket Scout" in html
    assert "Jesus" in html
    assert "Religion" in html
    assert "10.6%" in html

    data = json.loads((out_dir / "data.json").read_text())
    assert data["generated_at"] == "2026-05-23T02:00:00Z"
    assert len(data["rows"]) == 1
    assert data["rows"][0]["risk_score"] == 5
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Write `src/scout/render.py`**

```python
"""HTML and JSON report rendering."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scout.config import Config

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"


def collect_rows(conn: sqlite3.Connection, model: str) -> list[dict]:
    cur = conn.execute(
        """
        SELECT j.market_id, j.side, j.price, j.yield_apr, j.days_to_resolution,
               j.risk_score, j.risk_rationale, j.summary,
               m.question, m.slug, m.primary_tag, m.end_date,
               m.volume, m.liquidity
          FROM judgments j
          JOIN markets m ON m.id = j.market_id
         WHERE j.model = ?
         ORDER BY j.yield_apr DESC
        """,
        (model,),
    )
    return [dict(row) for row in cur.fetchall()]


def render_report(
    conn: sqlite3.Connection,
    cfg: Config,
    out_dir: Path,
    generated_at: str,
) -> None:
    rows = collect_rows(conn, model=cfg.model)
    tags = sorted({r["primary_tag"] for r in rows if r["primary_tag"]})

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("index.html.j2")
    html = template.render(
        rows=rows,
        tags=tags,
        generated_at=generated_at,
        yield_threshold_apr=cfg.yield_threshold_apr,
        min_price=cfg.min_price,
        rows_json=json.dumps(rows),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html)
    (out_dir / "data.json").write_text(
        json.dumps(
            {"generated_at": generated_at, "rows": rows},
            indent=2,
        )
    )
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_render.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add templates/index.html.j2 src/scout/render.py tests/test_render.py
git commit -m "feat: render static HTML + JSON docket"
```

---

### Task 8: CLI orchestration with typer

**Files:**
- Create: `src/scout/cli.py`

- [ ] **Step 1: Write `src/scout/cli.py`**

```python
"""Polymarket Scout CLI."""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

from scout.config import Config, load_config
from scout.db import (
    connect,
    finish_run,
    init_schema,
    start_run,
)
from scout.fetch import fetch_markets, store_markets
from scout.judge import (
    judge_candidate,
    store_judgment,
    unjudged_candidates,
)
from scout.render import collect_rows, render_report
from scout.score import Candidate, score_market

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / "scout.db"
DEFAULT_CONFIG = PROJECT_ROOT / "config.toml"
DEFAULT_OUT = PROJECT_ROOT / "docs"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _open(db_path: Path) -> sqlite3.Connection:
    conn = connect(db_path)
    init_schema(conn)
    return conn


def _load(config_path: Path) -> Config:
    return load_config(config_path)


def _all_candidates(conn: sqlite3.Connection, cfg: Config, today: date) -> list[Candidate]:
    cur = conn.execute(
        "SELECT id, end_date, yes_price, no_price FROM markets"
    )
    out: list[Candidate] = []
    for row in cur.fetchall():
        market = dict(row)
        cand = score_market(market, today, cfg)
        if cand is not None:
            out.append(cand)
    return out


@app.command()
def fetch(
    db_path: Path = typer.Option(DEFAULT_DB, "--db"),
) -> None:
    """Pull latest markets from Polymarket Gamma API."""
    conn = _open(db_path)
    markets = fetch_markets()
    n = store_markets(conn, markets, fetched_at=_now_iso())
    console.print(f"Fetched and stored {n} markets.")


@app.command()
def score(
    db_path: Path = typer.Option(DEFAULT_DB, "--db"),
    config_path: Path = typer.Option(DEFAULT_CONFIG, "--config"),
) -> None:
    """Compute yields and report candidate count (does not persist)."""
    conn = _open(db_path)
    cfg = _load(config_path)
    cands = _all_candidates(conn, cfg, date.today())
    console.print(f"{len(cands)} markets meet the threshold.")


@app.command()
def judge(
    db_path: Path = typer.Option(DEFAULT_DB, "--db"),
    config_path: Path = typer.Option(DEFAULT_CONFIG, "--config"),
) -> None:
    """Call Claude Haiku on unjudged candidates and cache results."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red]ANTHROPIC_API_KEY is not set.[/red]")
        raise typer.Exit(code=1)

    conn = _open(db_path)
    cfg = _load(config_path)
    cands = _all_candidates(conn, cfg, date.today())
    new = unjudged_candidates(conn, cands, model=cfg.model)
    console.print(f"{len(new)} new candidates to judge ({len(cands) - len(new)} cached).")

    client = anthropic.Anthropic(api_key=api_key)
    for i, cand in enumerate(new, 1):
        cur = conn.execute("SELECT * FROM markets WHERE id = ?", (cand.market_id,))
        market = dict(cur.fetchone())
        try:
            judgment = judge_candidate(client, cfg.model, market, cand)
        except Exception as exc:
            console.print(f"  [yellow]skip {cand.market_id}: {exc}[/yellow]")
            continue
        store_judgment(conn, cand, judgment, model=cfg.model, judged_at=_now_iso())
        console.print(f"  [{i}/{len(new)}] {cand.market_id} risk={judgment.risk_score}")


@app.command()
def render(
    db_path: Path = typer.Option(DEFAULT_DB, "--db"),
    config_path: Path = typer.Option(DEFAULT_CONFIG, "--config"),
    out_dir: Path = typer.Option(DEFAULT_OUT, "--out"),
) -> None:
    """Write docs/index.html and docs/data.json."""
    conn = _open(db_path)
    cfg = _load(config_path)
    render_report(conn, cfg, out_dir=out_dir, generated_at=_now_iso())
    console.print(f"Wrote {out_dir / 'index.html'} and {out_dir / 'data.json'}.")


@app.command()
def run(
    db_path: Path = typer.Option(DEFAULT_DB, "--db"),
    config_path: Path = typer.Option(DEFAULT_CONFIG, "--config"),
    out_dir: Path = typer.Option(DEFAULT_OUT, "--out"),
) -> None:
    """Run fetch → score → judge → render in sequence."""
    conn = _open(db_path)
    cfg = _load(config_path)
    run_id = start_run(conn, started_at=_now_iso())

    markets = fetch_markets()
    n_fetched = store_markets(conn, markets, fetched_at=_now_iso())
    console.print(f"fetch: {n_fetched} markets")

    cands = _all_candidates(conn, cfg, date.today())
    console.print(f"score: {len(cands)} candidates")

    new = unjudged_candidates(conn, cands, model=cfg.model)
    if new:
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            console.print("[red]ANTHROPIC_API_KEY is not set; skipping judge stage.[/red]")
        else:
            client = anthropic.Anthropic(api_key=api_key)
            for i, cand in enumerate(new, 1):
                cur = conn.execute("SELECT * FROM markets WHERE id = ?", (cand.market_id,))
                market = dict(cur.fetchone())
                try:
                    judgment = judge_candidate(client, cfg.model, market, cand)
                except Exception as exc:
                    console.print(f"  [yellow]skip {cand.market_id}: {exc}[/yellow]")
                    continue
                store_judgment(conn, cand, judgment, model=cfg.model, judged_at=_now_iso())
                console.print(f"  judged [{i}/{len(new)}] {cand.market_id} risk={judgment.risk_score}")
    else:
        console.print("judge: all candidates already cached")

    render_report(conn, cfg, out_dir=out_dir, generated_at=_now_iso())
    console.print(f"render: {out_dir / 'index.html'}")

    finish_run(conn, run_id, finished_at=_now_iso(),
               n_fetched=n_fetched, n_candidates=len(cands), n_judged=len(new))


@app.command(name="list")
def list_cmd(
    db_path: Path = typer.Option(DEFAULT_DB, "--db"),
    config_path: Path = typer.Option(DEFAULT_CONFIG, "--config"),
    top: int = typer.Option(20, "--top"),
) -> None:
    """Print the top N current opportunities as a terminal table."""
    conn = _open(db_path)
    cfg = _load(config_path)
    rows = collect_rows(conn, model=cfg.model)[:top]
    table = Table(title=f"Top {len(rows)} opportunities")
    table.add_column("Yield APR", justify="right")
    table.add_column("Days", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Side")
    table.add_column("Risk")
    table.add_column("Tag")
    table.add_column("Question")
    for r in rows:
        table.add_row(
            f"{r['yield_apr']*100:.1f}%",
            str(r["days_to_resolution"]),
            f"${r['price']:.3f}",
            r["side"],
            str(r["risk_score"] or "—"),
            r["primary_tag"] or "",
            r["question"][:60],
        )
    console.print(table)


if __name__ == "__main__":
    app()
```

- [ ] **Step 2: Smoke-test the CLI help output**

Run: `uv run scout --help`
Expected: lists the commands `fetch`, `score`, `judge`, `render`, `run`, `list`.

- [ ] **Step 3: Smoke-test `scout score` against an empty DB**

Run: `uv run scout score`
Expected: prints `0 markets meet the threshold.` (DB is empty).

- [ ] **Step 4: Smoke-test `scout render` against an empty DB**

Run: `uv run scout render`
Expected: writes `docs/index.html` and `docs/data.json`. Both files exist; HTML contains the string "Polymarket Scout".

- [ ] **Step 5: Commit**

```bash
git add src/scout/cli.py
git commit -m "feat: add typer CLI wiring all pipeline stages"
```

---

### Task 9: End-to-end live test

This task hits the real Polymarket API and the real Anthropic API. It costs a small amount of money (pennies) and proves the whole pipeline works against production endpoints.

- [ ] **Step 1: Verify `ANTHROPIC_API_KEY` is set**

Run: `echo "key length: ${#ANTHROPIC_API_KEY}"`
Expected: a non-zero length. If unset, export it before continuing.

- [ ] **Step 2: Run the full pipeline**

Run: `uv run scout run`
Expected output (rough shape):
```
fetch: <N> markets        (e.g. 1500-2500)
score: <K> candidates     (e.g. 50-300)
  judged [1/K] ...
  ...
render: .../docs/index.html
```

If the judge stage errors on individual markets, that's fine — they'll be retried on the next run. The script should continue past per-market failures.

- [ ] **Step 3: Inspect the report**

Run: `open docs/index.html`
Expected: a browser opens showing the docket. Verify you can:
  - Sort by clicking column headers
  - Filter by tag using the dropdown
  - Click a row to expand it and see the risk rationale + summary + Polymarket link

- [ ] **Step 4: Check the terminal listing**

Run: `uv run scout list --top 10`
Expected: a Rich-formatted table of the top 10 opportunities.

- [ ] **Step 5: Re-run to verify the judge cache works**

Run: `uv run scout run`
Expected: `judge: all candidates already cached` (or a much smaller number of newly judged markets — only ones whose end date moved them into the eligible window).

- [ ] **Step 6: Commit the generated report**

```bash
git add docs/index.html docs/data.json
git commit -m "feat: first generated docket"
```

---

### Task 10: README and GitHub Pages setup

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# Polymarket Scout

Find Polymarket markets where the favored side trades near $1.00, producing a positive yield that may beat short-duration Treasuries. Produces a static HTML report.

## Setup

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
export ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```bash
uv run scout run         # fetch + score + judge + render
uv run scout list --top 20
open docs/index.html
```

Individual stages:

```bash
uv run scout fetch       # API → SQLite
uv run scout score       # report candidate count
uv run scout judge       # Haiku judges new candidates
uv run scout render      # write docs/index.html
```

## Configuration

Edit `config.toml`:

```toml
yield_threshold_apr   = 0.05   # APR floor for candidates
min_price             = 0.90   # favored side must trade this high
max_days_to_resolution = 730
model                 = "claude-haiku-4-5"
```

## Publishing the report

The `docs/` folder is structured for GitHub Pages.

1. Push the repo to GitHub.
2. Repo Settings → Pages → Source: **Deploy from a branch** → Branch: `main`, folder: `/docs`.
3. After each `scout run`, `git add docs/ && git commit && git push`. The page auto-updates.

## Data

Everything lives in one file: `scout.db` (SQLite). Three tables:

- `markets` — every market we've ever fetched, latest snapshot per id
- `judgments` — Haiku's per-(market, side, model) risk score, rationale, summary
- `runs` — one row per `scout run` invocation
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README"
```

- [ ] **Step 3 (manual, optional): Push to GitHub and enable Pages**

```bash
# Create a repo on GitHub (web UI or `gh repo create`), then:
git remote add origin <your-repo-url>
git branch -M main
git push -u origin main
```

Then in GitHub: Settings → Pages → Source: Deploy from a branch → `main` / `/docs` → Save.

---

## Done criteria

- All pytest tests pass (`uv run pytest`)
- `scout run` produces a non-empty `docs/index.html` you can open in a browser
- Sorting and tag filtering work in the browser
- Re-running `scout run` does not re-call the LLM for already-judged candidates
- README explains setup, usage, and GitHub Pages deploy
