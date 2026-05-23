# Polymarket Scout — Design

**Date:** 2026-05-23
**Status:** Approved (brainstorming → ready for implementation plan)

## Purpose

Find Polymarket markets where the favored side trades near $1.00, producing a small-but-positive expected yield that beats short-duration Treasuries — the "Jesus resurrection 2026 paying 6%" archetype. Build a research-grade docket of such opportunities so the user can hand-pick a diversified basket.

This is an **on-demand research tool** (option A). Future stages may add scheduled docket-building, basket sizing, and execution; the design accommodates growth but does not implement those now.

## Scope

**In scope (v1):**
- Scrape all active Polymarket markets via the Gamma API
- Compute annualized yield on the favored side of each market
- Filter to candidates above a configurable yield threshold
- LLM judge produces a risk score + rationale + summary per candidate
- Output: SQLite database, CSV export, and a static HTML report deployable to GitHub Pages

**Out of scope (v1):**
- Order book depth analysis (use Gamma's `liquidity` field as a proxy)
- Position sizing / basket construction
- Automated execution via the CLOB API
- Multi-user features, auth, hosted dashboard
- Backtesting / historical performance tracking (history is recorded but not analyzed)

## Stack

- **Python 3.12+**, managed with `uv`
- **httpx** — Polymarket API client
- **SQLite** (stdlib) — single-file persistence
- **anthropic** SDK — Claude Haiku 4.5 for the judge agent
- **Jinja2** — HTML template
- **typer** — CLI

No web server, no ORM, no build step for the HTML.

## Folder layout

```
polymarket-scout/
├── pyproject.toml
├── config.toml              # user-tunable thresholds + model id
├── scout.db                 # SQLite — gitignored
├── src/scout/
│   ├── __init__.py
│   ├── cli.py               # typer entrypoint
│   ├── fetch.py             # Gamma API client → markets table
│   ├── score.py             # yield math, candidate filter
│   ├── judge.py             # Haiku judge agent
│   ├── render.py            # Jinja2 → docs/index.html + docs/data.json
│   └── db.py                # SQLite schema + connection helpers
├── templates/
│   └── index.html.j2
├── docs/                    # GitHub Pages root
│   ├── index.html           # generated, committed
│   └── data.json            # generated, committed
└── tests/
```

## Data sources

- `https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=500` (paginated via `offset`)
- Fields used: `id`, `slug`, `question`, `tags`, `endDate`, `outcomes`, `outcomePrices`, `volume`, `liquidity`, `description`
- The full response is stored as `raw_json` per market — cheap insurance for fields we later realize we want

The CLOB API (`https://clob.polymarket.com`) is **not** used in v1. We rely on Gamma's `liquidity` field as a depth proxy.

## Schema

```sql
CREATE TABLE markets (
    id              TEXT PRIMARY KEY,
    slug            TEXT NOT NULL,
    question        TEXT NOT NULL,
    tags_json       TEXT,             -- JSON array of tags from Gamma
    primary_tag     TEXT,             -- first tag, denormalized for sort/filter
    end_date        TEXT,             -- ISO 8601
    outcomes_json   TEXT,             -- JSON array
    yes_price       REAL,
    no_price        REAL,
    volume          REAL,
    liquidity       REAL,
    description     TEXT,
    raw_json        TEXT,
    fetched_at      TEXT NOT NULL
);

CREATE TABLE judgments (
    market_id       TEXT NOT NULL,
    side            TEXT NOT NULL,    -- 'YES' | 'NO'
    price           REAL NOT NULL,
    yield_apr       REAL NOT NULL,
    days_to_resolution INTEGER NOT NULL,
    risk_score      INTEGER,          -- 1 (clean) .. 5 (ambiguous)
    risk_rationale  TEXT,
    summary         TEXT,
    model           TEXT NOT NULL,
    judged_at       TEXT NOT NULL,
    PRIMARY KEY (market_id, side, model),
    FOREIGN KEY (market_id) REFERENCES markets(id)
);

CREATE TABLE runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    n_fetched       INTEGER,
    n_candidates    INTEGER,
    n_judged        INTEGER
);
```

The `(market_id, side, model)` primary key on `judgments` means switching models triggers re-judging without losing old judgments.

## CLI

```
scout fetch          # pull latest markets → markets table
scout score          # compute yields, identify candidates
scout judge          # call Haiku on unjudged candidates only (idempotent)
scout render         # write docs/index.html + docs/data.json
scout run            # all four in order
scout list --top 20  # quick terminal table of current best opportunities
```

`scout run` is the typical daily invocation. The other commands exist so individual stages can be re-run or tested in isolation.

## Configuration

`config.toml` at the project root:

```toml
yield_threshold_apr   = 0.05   # 5% APR floor for a market to be a candidate
min_price             = 0.90   # favored side must trade ≥ $0.90
max_days_to_resolution = 730   # skip multi-year markets — resolution risk dominates
model                 = "claude-haiku-4-5"
```

API key read from the `ANTHROPIC_API_KEY` env var.

## Ranking logic

For each market, evaluate the favored (higher-priced) side:

```
side_price    = max(yes_price, no_price)
gain_if_right = 1 - side_price
days          = (end_date - today).days
yield_apr     = (gain_if_right / side_price) * (365 / days)
```

A market is a **candidate** iff:
- `side_price >= min_price` AND
- `yield_apr >= yield_threshold_apr` AND
- `0 < days <= max_days_to_resolution`

Candidates are ranked by `yield_apr` descending. The judge agent's `risk_score` is displayed but does **not** re-rank — the user decides how to discount.

## Judge agent

One Haiku call per unjudged candidate. Cached forever; re-runs only when the configured model changes.

Prompt structure:
- **System:** rubric for `risk_score` (1 = objective external resolution like an official press release or government data; 5 = subjective resolution like a social-media poll, vague wording, or operator discretion). Output JSON schema.
- **User:** market question, full resolution criteria (`description`), end date, the side being bet on, current price.

Output JSON shape:
```json
{
  "risk_score": 1,
  "risk_rationale": "Resolves on SEC's official filing tracker — unambiguous data source.",
  "summary": "Bet NO that the SEC will not approve XYZ ETF by Dec 2026, paying ~7% APR."
}
```

Estimated cost: ~500 input tokens × ~500 candidates per run ≈ pennies.

## HTML report

`docs/index.html` — single-file static page, no build step:
- Sortable table: yield APR, days to resolution, price, risk score, primary tag, question
- Tag filter dropdown (multi-select; markets are matched if any tag matches)
- Row expansion shows risk rationale, summary, link to Polymarket
- "Last updated" timestamp at top
- Vanilla JS for sort/filter (no React, no bundler)

`docs/data.json` is the underlying data so the page can re-render without a server.

## Deployment

GitHub Pages from the `/docs` folder. Workflow:
1. `scout run` generates `docs/index.html` and `docs/data.json`
2. `git commit && git push`
3. Pages serves from `main:/docs` — no Actions, no Vercel, no deploy step

## Testing

- Unit tests for `score.py` yield math (edge cases: today's date, prices at exactly 0.90, multi-year markets)
- Unit tests for `db.py` schema migrations and idempotent inserts
- Integration test for `fetch.py` against a recorded Gamma API response fixture
- `judge.py` tested with a mocked Anthropic client (verify prompt construction + JSON parsing, not the model's output)

## Future extensions (deliberately not built now)

- CLOB depth lookup to validate fillability of high-yield markets
- Position sizing recommendations (Kelly, fixed-fraction)
- Scheduled run + diff alerts ("yield on market X rose 3% today")
- Curated basket layer on top of the candidate list
- Historical performance tracking (judgments table already records the data needed)
