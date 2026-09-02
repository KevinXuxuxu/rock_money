"""
Shared test fixtures. Mock the database at the db.py boundary so tests
never touch PostgreSQL.
"""

from unittest.mock import MagicMock, patch

import pytest

import db


@pytest.fixture(autouse=True)
def _forbid_real_db(monkeypatch):
    """
    Fail loudly if any test tries to open a real database connection.

    Tests must mock at the db.py boundary (see mock_db). Without this guard a
    forgotten mock silently queries the developer's local Postgres (via
    DATABASE_URL from .env) — the test passes locally but fails in CI where no
    .env/DB exists. Replaced by mock_db's own patch in tests that request it.
    """

    def _boom(*args, **kwargs):
        raise AssertionError(
            "test attempted real DB access — patch db.get_conn (mock_db fixture) "
            "or mock the calling analytics/db function"
        )

    monkeypatch.setattr(db, "get_conn", _boom)


@pytest.fixture
def mock_db():
    """
    Patch db.get_conn to return a MagicMock connection with a mock cursor.

    Returns the mock **cursor** (not the connection). Tests set
    ``mock_db.fetchall.return_value`` or ``mock_db.fetchone.return_value``
    and optionally inspect ``mock_db.execute.call_args`` to verify the
    generated SQL and parameters.
    """
    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.cursor.return_value.__exit__.return_value = None

    with patch("db.get_conn", return_value=mock_conn):
        yield mock_cur


# ── Sample data builders ────────────────────────────────────────────────────


def make_txn(**overrides) -> dict:
    """Build a transaction dict as returned by the database (RealDictCursor row)."""
    defaults = {
        "transaction_id": "txn_001",
        "account_id": "acct_001",
        "amount": 29.99,
        "iso_currency_code": "USD",
        "date": "2026-06-01",
        "authorized_date": None,
        "name": "Sample Transaction",
        "merchant_name": "Sample Merchant",
        "payment_channel": "online",
        "pending": False,
        "personal_finance_category": "FOOD_AND_DRINK",
        "personal_finance_category_confidence": "HIGH",
        "category": ["Food and Drink", "Restaurants"],
        "account_name": "Checking",
        "account_mask": "1234",
        "account_type": "depository",
        "account_subtype": "checking",
    }
    return {**defaults, **overrides}


def make_account(**overrides) -> dict:
    """Build an account dict as returned by the database."""
    defaults = {
        "account_id": "acct_001",
        "name": "Checking",
        "official_name": "Premium Checking",
        "type": "depository",
        "subtype": "checking",
        "mask": "1234",
        "label": None,
        "item_id": "item_001",
        "institution_name": "Test Bank",
        "txn_count": 42,
        "total_debits": 5000.00,
        "total_credits": 6000.00,
    }
    return {**defaults, **overrides}
