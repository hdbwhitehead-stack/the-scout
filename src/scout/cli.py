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
