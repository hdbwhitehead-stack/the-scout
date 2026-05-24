"""Claude Haiku judge agent."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    query,
)

from scout.score import Candidate

SYSTEM_PROMPT = """You are evaluating Polymarket prediction-market opportunities for a bettor considering taking the favored side of a market trading near a dollar.

For each market you receive: the question, the full resolution criteria, the end date, the side being considered, and the current market price.

Output ONLY a single JSON object (no prose, no code fences) with four fields:

{
  "risk_score": <integer 1 to 5>,
  "risk_rationale": "<one sentence: what makes resolution clean or messy>",
  "subjective_p_win": <float 0.0 to 1.0>,
  "summary": "<one sentence: the bet, its side, approximate yield, headline risk>"
}

# risk_score rubric (resolution-criterion clarity only):
  1 — Objective: government data, official press release, on-chain event, sports box score
  2 — Mostly objective with one minor source-of-truth ambiguity
  3 — Some judgement required (counting media mentions, interpreting a vague threshold)
  4 — Substantially subjective (operator discretion, hard-to-verify private events)
  5 — Highly subjective or unarbitrable (social-media polls, supernatural events, vague public-perception questions)

# subjective_p_win — your independent estimate of P(favored side wins)

Give your honest probability. Reason from base rates, the underlying real-world event, the resolution mechanism, and any domain knowledge you can bring. Do NOT mechanically anchor to the market price. The market price is the wisdom of crowds — a reasonable prior when you have no independent view, but you should deviate confidently when you do.

Calibration anchors:
  • A well-defined market near a dollar typically deserves a subjective probability AT OR VERY SLIGHTLY ABOVE the market price — the market has the same information you do, and rarely makes systematic errors on objective binaries.
  • Markets with risk_score 3+ deserve subjective probabilities NOTICEABLY BELOW the market price. The market is pricing the underlying event; you should additionally discount for the probability that the question resolves contrary to objective reality due to oracle disputes, ambiguous wording, or operator discretion. This adjustment is typically 3–10 percentage points downward, occasionally more.
  • If the resolution criteria are subjective or the underlying event involves coordinated human behavior (markets, elections, sports), defer more to market price (it aggregates more information than you have).
  • If the resolution criteria are mechanical and the underlying event is well-modeled by base rates (mortality, scheduled events, mature processes), trust your own estimate more.

The output is consumed by a basket strategy that will compute (subjective_p_win − price) as the "edge." That edge column will only be useful if your estimates have genuine signal — anchoring to price destroys the signal. Be willing to estimate lower than market on messy markets, and to agree with market on clean ones.

Output should be a single decimal between 0 and 1, e.g. 0.97 for "I think the favored side wins 97% of the time."
"""


@dataclass(frozen=True)
class Judgment:
    risk_score: int
    risk_rationale: str
    summary: str
    subjective_p_win: float


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


def _parse_judgment(text: str, fallback_price: float | None = None) -> Judgment:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    data = json.loads(text)
    raw_p = data.get("subjective_p_win")
    if raw_p is None:
        p_win = float(fallback_price) if fallback_price is not None else 0.0
    else:
        p_win = float(raw_p)
    # Clamp to [0, 1] for safety.
    p_win = max(0.0, min(1.0, p_win))
    return Judgment(
        risk_score=int(data["risk_score"]),
        risk_rationale=str(data["risk_rationale"]),
        summary=str(data["summary"]),
        subjective_p_win=p_win,
    )


async def _collect_text(prompt: str, model: str) -> str:
    """Send a one-shot prompt via claude-agent-sdk and return the assistant text."""
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=model,
        allowed_tools=[],
        max_turns=1,
        setting_sources=None,
    )
    chunks: list[str] = []
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                text = getattr(block, "text", None)
                if text:
                    chunks.append(text)
    if not chunks:
        raise ValueError("claude-agent-sdk response contained no text blocks")
    return "".join(chunks)


def judge_candidate(
    model: str,
    market: dict,
    cand: Candidate,
) -> Judgment:
    text = asyncio.run(_collect_text(build_prompt(market, cand), model))
    return _parse_judgment(text, fallback_price=cand.price)


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
            risk_score, risk_rationale, summary, subjective_p_win,
            model, judged_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            judgment.subjective_p_win,
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
