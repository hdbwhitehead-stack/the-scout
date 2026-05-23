"""HTML and JSON report rendering."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scout.config import Config

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"


def duration_bucket(days: int) -> str:
    """Map days-to-resolution into the bucket labels used by the report's filter chips."""
    if days <= 90:
        return "≤90d"
    if days <= 365:
        return "91–365d"
    return "366–730d"


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


def enrich_rows(rows: list[dict]) -> list[dict]:
    """Compute derived display fields (absolute_payoff_pct, duration_bucket)."""
    for r in rows:
        r["absolute_payoff_pct"] = (1 - r["price"]) * 100
        r["duration_bucket"] = duration_bucket(r["days_to_resolution"])
    return rows


def render_report(
    conn: sqlite3.Connection,
    cfg: Config,
    out_dir: Path,
    generated_at: str,
) -> None:
    rows = enrich_rows(collect_rows(conn, model=cfg.model))

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
