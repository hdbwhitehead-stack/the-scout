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
