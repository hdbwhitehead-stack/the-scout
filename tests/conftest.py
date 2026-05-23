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
