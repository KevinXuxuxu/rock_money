"""
Integration tests for the net-category semantics against a REAL PostgreSQL
database: the category tiles (analytics.spend_by_category /
income_by_category), the Sankey stages (income_by_account_category /
spend_by_category_account) and the cash-flow table (monthly_summary) all
partition a month's categories the same way — debit categories net their
spend, credits-only categories count as income.

Skipped unless ROCK_MONEY_TEST_DB_URL points at the *test* database, e.g.
    ROCK_MONEY_TEST_DB_URL=postgresql://postgres@host.docker.internal:5432/rock_money_test \
        uv run pytest tests/test_net_category_integration.py

The live_db fixture REFUSES to run against any URL that is not
rock_money_test, so these tests can never touch the live database. They
insert synthetic transactions (unique ID prefix, fixed far-future month) and
delete them afterwards; the test DB's own data is otherwise untouched.
"""

import os
import uuid
from contextlib import contextmanager

import psycopg2
import pytest

import analytics
import db

# Captured at import time, before any test's autouse mock patches db.get_conn.
_REAL_GET_CONN = db.get_conn

# Far-future month guaranteed to be empty in the test DB — only synthetic rows
# land here, so exact-set assertions below stay deterministic.
SYNTHETIC_MONTH = "2031-04"


def _test_db_url() -> str:
    return os.environ.get("ROCK_MONEY_TEST_DB_URL", "")


def _require_test_db(url: str) -> None:
    """Hard guard: refuse to run against anything but the test database."""
    if "rock_money_test" not in url:
        raise AssertionError(
            f"refusing to run integration tests against {url!r} — "
            "ROCK_MONEY_TEST_DB_URL must point at the rock_money_test database, "
            "never the live one"
        )


requires_test_db = pytest.mark.skipif(
    not _test_db_url(),
    reason="ROCK_MONEY_TEST_DB_URL not set (point it at the rock_money_test DB)",
)


@pytest.fixture()
def live_db(monkeypatch):
    """Route db.get_conn at the test database for the duration of one test."""
    url = _test_db_url()
    if not url:
        pytest.skip("ROCK_MONEY_TEST_DB_URL not set")
    _require_test_db(url)

    old_pool = db._pool
    db._pool = None  # force the pool to (re)connect using the DSN below
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(db, "get_conn", _REAL_GET_CONN)
    yield
    if db._pool is not None and db._pool is not old_pool:
        db._pool.closeall()
    db._pool = old_pool


# category: [(name, amount)] — positive = debit (money out), negative = credit
SYNTHETIC = {
    # Mixed signs: net 5312 with 973 of credits (the user's example case).
    "TRAVEL": [("Airfare", 5000.00), ("Hotel", 1285.00), ("Airfare refund", -973.00)],
    "GROCERY": [("T & T Supermarket", 80.00), ("Food4Less", 70.00), ("Return", -20.00)],
    # Refunds outrunning spend → net-negative, still a spend category.
    "MISC": [("Fee", 10.00), ("Refund", -50.00)],
    "INCOME": [("Paycheck", -2500.00), ("Bonus", -500.00)],
    # Credits-only → belongs to the income tile.
    "REFUND": [("Store credit", -100.00)],
    # Excluded category → must not appear in either tile.
    "CREDIT PAYMENT": [("CC autopay", 300.00)],
}


@contextmanager
def synthetic_data():
    """Insert the SYNTHETIC transactions into the test DB; delete on exit.

    All rows land in SYNTHETIC_MONTH under one item/account with a unique ID
    prefix, and teardown cascade-deletes the item, so the test DB's own data
    is untouched even if the body raises.
    """
    uid = uuid.uuid4().hex[:8]
    item_id, account_id = f"itg_item_{uid}", f"itg_acct_{uid}"
    conn = psycopg2.connect(_test_db_url())
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO items (item_id, access_token) VALUES (%s, %s)",
        (item_id, f"itg_token_{uid}"),
    )
    cur.execute(
        "INSERT INTO accounts (account_id, item_id, name, type) VALUES (%s, %s, %s, %s)",
        (account_id, item_id, "ITG Account", "depository"),
    )
    for i, (category, txns) in enumerate(SYNTHETIC.items()):
        for j, (name, amount) in enumerate(txns):
            cur.execute(
                """
                INSERT INTO transactions
                    (transaction_id, account_id, amount, date, name,
                     merchant_name, pending, personal_finance_category)
                VALUES (%s, %s, %s, %s, %s, %s, FALSE, %s)
                """,
                (
                    f"itg_txn_{uid}_{i}_{j}",
                    account_id,
                    amount,
                    f"{SYNTHETIC_MONTH}-15",
                    name,
                    name,
                    category,
                ),
            )
    try:
        yield
    finally:
        # Deleting the item cascades to its accounts and transactions.
        cur.execute("DELETE FROM items WHERE item_id = %s", (item_id,))
        conn.close()


class TestNetCategoryTiles:
    @requires_test_db
    def test_spend_tile_is_net_of_credits(self, live_db):
        with synthetic_data():
            spend = analytics.spend_by_category(SYNTHETIC_MONTH)
            income = analytics.income_by_category(SYNTHETIC_MONTH)

        spend_map = {r["category"]: r for r in spend}
        income_map = {r["category"]: r for r in income}

        # ── Spend tile: net of credits; only categories with a debit ────────
        assert set(spend_map) == {"TRAVEL", "GROCERY", "MISC"}
        assert float(spend_map["TRAVEL"]["total_spend"]) == 5312.00  # 6285 − 973
        assert float(spend_map["TRAVEL"]["debit_total"]) == 6285.00
        assert float(spend_map["TRAVEL"]["credit_total"]) == 973.00
        assert spend_map["TRAVEL"]["txn_count"] == 3
        assert float(spend_map["GROCERY"]["total_spend"]) == 130.00
        assert float(spend_map["GROCERY"]["credit_total"]) == 20.00
        assert float(spend_map["MISC"]["total_spend"]) == -40.00

        # ── Income tile: credits-only categories; refunds are NOT income ────
        assert set(income_map) == {"INCOME", "REFUND"}
        assert float(income_map["INCOME"]["total_income"]) == 3000.00
        assert income_map["INCOME"]["txn_count"] == 2
        assert float(income_map["REFUND"]["total_income"]) == 100.00
        assert "TRAVEL" not in income_map
        assert "GROCERY" not in income_map

        # ── Excluded categories never appear in either tile ─────────────────
        assert "CREDIT PAYMENT" not in spend_map
        assert "CREDIT PAYMENT" not in income_map

        # ── Ordering: net spend DESC / income DESC ──────────────────────────
        assert [r["category"] for r in spend] == ["TRAVEL", "GROCERY", "MISC"]
        assert [r["category"] for r in income] == ["INCOME", "REFUND"]

    @requires_test_db
    def test_sankey_and_cash_flow_use_net_semantics(self, live_db):
        with synthetic_data():
            inc_acct = analytics.income_by_account_category(SYNTHETIC_MONTH)
            spend_pairs = analytics.spend_by_category_account(SYNTHETIC_MONTH)
            summary = analytics.monthly_summary(months=100)

        # ── Sankey income stage: credits-only categories, by account ────────
        inc_map = {r["category"]: r for r in inc_acct}
        assert set(inc_map) == {"INCOME", "REFUND"}
        assert float(inc_map["INCOME"]["total_income"]) == 3000.00
        assert float(inc_map["REFUND"]["total_income"]) == 100.00
        assert all(r["account_name"] == "ITG Account" for r in inc_acct)
        # Refunds in spending categories are not Sankey income sources.
        assert "TRAVEL" not in inc_map

        # ── Sankey spend links: net per (category, account) ─────────────────
        pair_map = {r["category"]: r for r in spend_pairs}
        assert set(pair_map) == {"TRAVEL", "GROCERY", "MISC"}
        assert float(pair_map["TRAVEL"]["total_spend"]) == 5312.00  # 6285 − 973
        assert float(pair_map["GROCERY"]["total_spend"]) == 130.00
        # Refunds outrunning spend on the account → negative net pair; the
        # Sankey builder skips non-positive links, the tile shows the net.
        assert float(pair_map["MISC"]["total_spend"]) == -40.00
        assert "CREDIT PAYMENT" not in pair_map

        # ── Cash flow table: spend = net, income = credits-only categories ──
        row = next(r for r in summary if str(r["month"]) == f"{SYNTHETIC_MONTH}-01")
        assert float(row["income"]) == 3100.00  # 3000 + 100
        assert float(row["spend"]) == 5402.00  # 5312 + 130 − 40
        assert float(row["net"]) == -2302.00
