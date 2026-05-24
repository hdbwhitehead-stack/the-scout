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

SYSTEM_PROMPT = """You are evaluating a prediction-market question for a bettor considering taking the favored side.

For each market you receive: the question, the full resolution criteria, the end date, and the side under consideration.

Output ONLY a single JSON object (no prose, no code fences) with four fields:

{
  "risk_score": <integer 1 to 5>,
  "risk_rationale": "<one sentence: what makes resolution clean or messy>",
  "subjective_p_win": <float 0.0 to 1.0>,
  "summary": "<one sentence: the bet, its side, headline factor>"
}

# risk_score rubric (resolution-criterion clarity only — independent of probability)
  1 — Objective: government data, official press release, on-chain event, sports box score
  2 — Mostly objective with minor source-of-truth ambiguity
  3 — Some judgement required (vague threshold, counting media mentions)
  4 — Substantially subjective (operator discretion, hard-to-verify private events)
  5 — Highly subjective or unarbitrable (polls, supernatural events, vague public-perception questions)

# subjective_p_win — independent probability estimate

Estimate the probability that the SIDE under consideration wins, reasoning from first principles:
  • Base rates for the underlying event class (e.g. mortality tables, election incumbency, historical sports outcomes)
  • The mechanics of the resolution mechanism and what fraction of the time it produces the "right" answer
  • Domain knowledge about the specific situation
  • Time to resolution and what events could plausibly change the outcome

Output a probability you would honestly stand behind if forced to bet your own money. Use the full 0.0-1.0 range — there is no reason your answer should cluster near any particular number.

Do NOT use the market price as an input to your reasoning. The market price reflects a population of bettors with their own biases, incentives, and information asymmetries; it is being analysed separately by the consuming code and combining the two sources of signal here destroys the value of yours.

You will sometimes disagree sharply with the market. That disagreement is the entire reason your estimate is being collected. State it honestly.
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
    """Send a one-shot prompt via claude-agent-sdk and return the assistant text.

    ``model`` may carry a cache-busting suffix like ``claude-haiku-4-5:v3``; the
    SDK only accepts real Anthropic model ids, so we strip anything after the
    first ``:``. The full string remains the judgments-cache key.
    """
    api_model = model.split(":", 1)[0]
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=api_model,
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
