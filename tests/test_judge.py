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
