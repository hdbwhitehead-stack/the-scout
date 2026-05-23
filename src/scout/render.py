"""HTML and JSON report rendering."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scout.config import Config
from scout.score import Candidate

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"


def duration_bucket(days: int) -> str:
    """Map days-to-resolution into the bucket labels used by the report's filter chips."""
    if days <= 90:
        return "≤90d"
    if days <= 365:
        return "91–365d"
    return "366–730d"


def collect_rows(
    conn: sqlite3.Connection,
    candidates: list[Candidate],
    model: str,
) -> list[dict]:
    """Build display rows from today's candidates joined with markets and (optional) judgments.

    Every candidate appears as a row. Judgment fields are populated when a cached
    judgment exists for (market_id, side) under the given model; otherwise they
    remain None so the report can show unjudged candidates explicitly.
    """
    if not candidates:
        return []

    ids = [c.market_id for c in candidates]
    placeholders = ",".join("?" * len(ids))

    cur = conn.execute(
        f"SELECT id, platform, question, slug, primary_tag, end_date, "
        f"volume, liquidity FROM markets WHERE id IN ({placeholders})",
        ids,
    )
    markets = {row["id"]: dict(row) for row in cur.fetchall()}

    cur = conn.execute(
        f"SELECT market_id, side, risk_score, risk_rationale, summary, "
        f"subjective_p_win "
        f"FROM judgments WHERE model = ? AND market_id IN ({placeholders})",
        [model, *ids],
    )
    judgments = {(row["market_id"], row["side"]): dict(row) for row in cur.fetchall()}

    rows: list[dict] = []
    for c in candidates:
        m = markets.get(c.market_id, {})
        j = judgments.get((c.market_id, c.side), {})
        rows.append(
            {
                "market_id": c.market_id,
                "side": c.side,
                "price": c.price,
                "yield_apr": c.yield_apr,
                "days_to_resolution": c.days_to_resolution,
                "risk_score": j.get("risk_score"),
                "risk_rationale": j.get("risk_rationale"),
                "summary": j.get("summary"),
                "subjective_p_win": j.get("subjective_p_win"),
                "question": m.get("question", ""),
                "slug": m.get("slug", ""),
                "platform": m.get("platform"),
                "primary_tag": m.get("primary_tag"),
                "end_date": m.get("end_date"),
                "volume": m.get("volume"),
                "liquidity": m.get("liquidity"),
            }
        )

    rows.sort(key=lambda r: r["yield_apr"], reverse=True)
    return rows


def _kelly_fraction(price: float, p_win: float) -> float:
    """Classic binary-bet Kelly, clamped to [0, 1]. Returns 0 when no edge."""
    if price <= 0 or price >= 1 or p_win is None:
        return 0.0
    b = (1 - price) / price
    f = (b * p_win - (1 - p_win)) / b
    return max(0.0, min(1.0, f))


def enrich_rows(rows: list[dict]) -> list[dict]:
    """Compute derived display fields (absolute_payoff_pct, duration_bucket, edge, kelly)."""
    for r in rows:
        r["absolute_payoff_pct"] = (1 - r["price"]) * 100
        r["duration_bucket"] = duration_bucket(r["days_to_resolution"])
        p_win = r.get("subjective_p_win")
        if p_win is not None:
            r["edge_pct"] = (p_win - r["price"]) * 100
            r["kelly_fraction"] = _kelly_fraction(r["price"], p_win)
        else:
            r["edge_pct"] = None
            r["kelly_fraction"] = None
    return rows


def render_report(
    conn: sqlite3.Connection,
    candidates: list[Candidate],
    cfg: Config,
    out_dir: Path,
    generated_at: str,
) -> None:
    rows = enrich_rows(collect_rows(conn, candidates, model=cfg.model))

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("index.html.j2")
    html = template.render(
        rows_json=json.dumps(rows, ensure_ascii=False),
        generated_at=generated_at,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html)
    (out_dir / "data.json").write_text(
        json.dumps(
            {"generated_at": generated_at, "rows": rows},
            indent=2,
            ensure_ascii=False,
        )
    )
