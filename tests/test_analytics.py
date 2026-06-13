"""Tests for analytics.py — all DB interaction is mocked via the mock_db fixture."""

from unittest.mock import patch

import analytics
from tests.conftest import make_txn, make_account


class TestGetTransactions:
    """Phase 1: get_transactions()"""

    def test_returns_transactions_newest_first(self, mock_db):
        mock_db.fetchall.return_value = [
            make_txn(transaction_id="t1", date="2026-06-10"),
            make_txn(transaction_id="t2", date="2026-06-01"),
        ]

        result = analytics.get_transactions()

        assert len(result) == 2
        assert result[0]["transaction_id"] == "t1"
        assert result[1]["transaction_id"] == "t2"

    def test_excludes_pending_by_default(self, mock_db):
        """Verify the SQL includes 'pending = FALSE'."""
        mock_db.fetchall.return_value = []

        analytics.get_transactions()

        sql = mock_db.execute.call_args[0][0]
        assert "t.pending = FALSE" in sql

    def test_includes_pending_when_requested(self, mock_db):
        mock_db.fetchall.return_value = [
            make_txn(pending=True),
        ]

        analytics.get_transactions(pending=True)

        sql = mock_db.execute.call_args[0][0]
        assert "t.pending = FALSE" not in sql

    def test_filters_by_account(self, mock_db):
        mock_db.fetchall.return_value = []

        analytics.get_transactions(account_id="acct_XYZ")

        sql = mock_db.execute.call_args[0][0]
        params = mock_db.execute.call_args[0][1]
        assert "t.account_id = %s" in sql
        assert "acct_XYZ" in params

    def test_filters_by_category(self, mock_db):
        mock_db.fetchall.return_value = []

        analytics.get_transactions(category="INCOME")

        sql = mock_db.execute.call_args[0][0]
        params = mock_db.execute.call_args[0][1]
        assert "INCOME" in params
        # Uses effective category (overrides included)
        assert "COALESCE(co.category, t.personal_finance_category)" in sql

    def test_left_joins_category_overrides(self, mock_db):
        """Verify the query joins category_overrides for effective_category."""
        mock_db.fetchall.return_value = []

        analytics.get_transactions()

        sql = mock_db.execute.call_args[0][0]
        assert "LEFT JOIN category_overrides co" in sql
        assert (
            "COALESCE(co.category, t.personal_finance_category) AS effective_category"
            in sql
        )

    def test_returns_effective_category_field(self, mock_db):
        """When an override exists, effective_category reflects it."""
        mock_db.fetchall.return_value = [
            make_txn(
                transaction_id="t1",
                personal_finance_category="GROCERIES",
                effective_category="Custom Grocery",
            ),
        ]

        result = analytics.get_transactions()
        assert result[0]["effective_category"] == "Custom Grocery"

    def test_effective_category_falls_back_to_plaid(self, mock_db):
        """When no override, effective_category equals plaid category."""
        mock_db.fetchall.return_value = [
            make_txn(
                transaction_id="t1",
                personal_finance_category="TRANSPORTATION",
                effective_category="TRANSPORTATION",
            ),
        ]

        result = analytics.get_transactions()
        assert result[0]["effective_category"] == "TRANSPORTATION"

    def test_filters_by_month(self, mock_db):
        mock_db.fetchall.return_value = []

        analytics.get_transactions(month="2026-06")

        params = mock_db.execute.call_args[0][1]
        assert any("2026-06-01" in str(p) for p in params)

    def test_uses_limit_parameter(self, mock_db):
        mock_db.fetchall.return_value = []

        analytics.get_transactions(limit=10)

        params = mock_db.execute.call_args[0][1]
        assert 10 in params


class TestGetAccounts:
    """Phase 1: get_accounts()"""

    def test_returns_accounts_with_counts(self, mock_db):
        mock_db.fetchall.return_value = [
            make_account(account_id="a1", name="Checking", txn_count=5),
            make_account(account_id="a2", name="Savings", txn_count=0),
        ]

        result = analytics.get_accounts()

        assert len(result) == 2
        assert result[0]["name"] == "Checking"
        assert result[0]["txn_count"] == 5
        assert result[1]["name"] == "Savings"


class TestSpendByCategory:
    """Phase 2: spend_by_category()"""

    def test_returns_categories_sorted_by_spend(self, mock_db):
        mock_db.fetchall.return_value = [
            {"category": "GROCERIES", "total_spend": 350.00, "txn_count": 8},
            {"category": "RESTAURANTS", "total_spend": 120.00, "txn_count": 3},
            {"category": None, "total_spend": 45.00, "txn_count": 1},
        ]

        result = analytics.spend_by_category("2026-06")

        assert len(result) == 3
        # Already sorted by spend DESC from SQL
        assert result[0]["category"] == "GROCERIES"
        assert result[0]["total_spend"] == 350.00

    def test_passes_month_param(self, mock_db):
        mock_db.fetchall.return_value = []

        analytics.spend_by_category("2026-03")

        params = mock_db.execute.call_args[0][1]
        assert "2026-03-01" in str(params[0])

    def test_only_positive_amounts_spending(self, mock_db):
        """Spending = only debits (positive amounts)."""
        mock_db.fetchall.return_value = []

        analytics.spend_by_category("2026-06")

        sql = mock_db.execute.call_args[0][0]
        assert "amount > 0" in sql


class TestMonthlySummary:
    """Phase 2: monthly_summary()"""

    def test_returns_ordered_by_month(self, mock_db):
        mock_db.fetchall.return_value = [
            {
                "month": "2026-04-01",
                "income": 5000.00,
                "spend": 3200.00,
                "net": 1800.00,
            },
            {
                "month": "2026-05-01",
                "income": 5100.00,
                "spend": 3400.00,
                "net": 1700.00,
            },
        ]

        result = analytics.monthly_summary()

        assert len(result) == 2
        assert result[0]["month"] == "2026-04-01"

    def test_default_limit_12_months(self, mock_db):
        mock_db.fetchall.return_value = []

        analytics.monthly_summary()

        params = mock_db.execute.call_args[0][1]
        assert params[-1] == 12

    def test_custom_month_count(self, mock_db):
        mock_db.fetchall.return_value = []

        analytics.monthly_summary(months=3)

        params = mock_db.execute.call_args[0][1]
        assert params[-1] == 3

    def test_sign_convention(self, mock_db):
        """Income = negated negative amounts. Spend = positive amounts."""
        mock_db.fetchall.return_value = []

        analytics.monthly_summary()

        sql = mock_db.execute.call_args[0][0]
        # Income: negate credits (amount < 0)
        assert "WHEN amount < 0 THEN -amount" in sql
        # Spend: sum debits (amount > 0)
        assert "WHEN amount > 0 THEN  amount" in sql


# ── Phase 3: Category resolution ─────────────────────────────────────────────


class TestRuleMatching:
    """Phase 3: _rule_matches() — pure logic, no DB."""

    def test_case_insensitive_match(self):
        assert analytics._rule_matches("Netflix", "netflix")

    def test_substring_match(self):
        assert analytics._rule_matches("Netflix.com", "netflix")

    def test_no_match(self):
        assert not analytics._rule_matches("Spotify", "netflix")

    def test_empty_field(self):
        assert not analytics._rule_matches("", "netflix")

    def test_empty_pattern(self):
        assert analytics._rule_matches("Anything", "")


class TestFieldValue:
    """_field_value falls back from merchant_name → name when merchant_name is NULL."""

    def test_merchant_name_present(self):
        txn = {"merchant_name": "Trader Joe's", "name": "TRADER JOES #123"}
        assert analytics._field_value(txn, "merchant_name") == "Trader Joe's"

    def test_merchant_name_null_falls_back_to_name(self):
        txn = {"merchant_name": None, "name": "TRADER JOES #123"}
        assert analytics._field_value(txn, "merchant_name") == "TRADER JOES #123"

    def test_name_field_no_fallback(self):
        txn = {"merchant_name": "Trader Joe's", "name": "TRADER JOES #123"}
        assert analytics._field_value(txn, "name") == "TRADER JOES #123"

    def test_personal_finance_category(self):
        txn = {"personal_finance_category": "FOOD_AND_DRINK", "name": "x"}
        assert (
            analytics._field_value(txn, "personal_finance_category") == "FOOD_AND_DRINK"
        )


# ── Phase 4: Budget management ────────────────────────────────────────────────


class TestBudgetStatus:
    """Phase 4: budget_status()"""

    def test_returns_budget_rows_with_actuals(self, mock_db):
        with (
            patch("db.list_budgets") as mock_budgets,
            patch("analytics.spend_by_category") as mock_spend,
        ):
            mock_budgets.return_value = [
                {"category": "GROCERIES", "monthly_limit": 600.00},
            ]
            mock_spend.return_value = [
                {"category": "GROCERIES", "total_spend": 350.00, "txn_count": 8},
            ]

            result = analytics.budget_status("2026-06")

        assert len(result) == 1
        row = result[0]
        assert row["category"] == "GROCERIES"
        assert row["monthly_limit"] == 600.00
        assert row["actual_spend"] == 350.00
        assert row["remaining"] == 250.00
        assert abs(row["pct_used"] - 58.33) < 0.01

    def test_zero_actual_when_no_spending(self, mock_db):
        with (
            patch("db.list_budgets") as mock_budgets,
            patch("analytics.spend_by_category") as mock_spend,
        ):
            mock_budgets.return_value = [
                {"category": "TRAVEL", "monthly_limit": 500.00},
            ]
            mock_spend.return_value = []  # no spending this month

            result = analytics.budget_status("2026-06")

        assert result[0]["actual_spend"] == 0.0
        assert result[0]["remaining"] == 500.00
        assert result[0]["pct_used"] == 0.0

    def test_sorted_by_pct_used_desc(self, mock_db):
        with (
            patch("db.list_budgets") as mock_budgets,
            patch("analytics.spend_by_category") as mock_spend,
        ):
            mock_budgets.return_value = [
                {"category": "GROCERIES", "monthly_limit": 600.00},
                {"category": "DINING", "monthly_limit": 200.00},
            ]
            mock_spend.return_value = [
                {"category": "GROCERIES", "total_spend": 120.00, "txn_count": 3},
                {"category": "DINING", "total_spend": 190.00, "txn_count": 5},
            ]

            result = analytics.budget_status("2026-06")

        # DINING is at 95%, GROCERIES at 20%
        assert result[0]["category"] == "DINING"
        assert result[1]["category"] == "GROCERIES"

    def test_returns_empty_when_no_budgets(self, mock_db):
        with patch("db.list_budgets") as mock_budgets:
            mock_budgets.return_value = []
            result = analytics.budget_status("2026-06")
        assert result == []

    def test_over_budget_shows_negative_remaining(self, mock_db):
        with (
            patch("db.list_budgets") as mock_budgets,
            patch("analytics.spend_by_category") as mock_spend,
        ):
            mock_budgets.return_value = [
                {"category": "DINING", "monthly_limit": 100.00},
            ]
            mock_spend.return_value = [
                {"category": "DINING", "total_spend": 150.00, "txn_count": 6},
            ]

            result = analytics.budget_status("2026-06")

        assert result[0]["remaining"] == -50.00
        assert result[0]["pct_used"] == 150.0


class TestBudgetAlert:
    """Phase 4: budget_alert()"""

    def test_returns_rows_above_threshold(self):
        with patch("analytics.budget_status") as mock_status:
            mock_status.return_value = [
                {
                    "category": "DINING",
                    "pct_used": 95.0,
                    "monthly_limit": 200.0,
                    "actual_spend": 190.0,
                },
                {
                    "category": "GROCERIES",
                    "pct_used": 50.0,
                    "monthly_limit": 600.0,
                    "actual_spend": 300.0,
                },
            ]

            result = analytics.budget_alert("2026-06", threshold=80.0)

        assert len(result) == 1
        assert result[0]["category"] == "DINING"

    def test_default_threshold_is_80(self):
        with patch("analytics.budget_status") as mock_status:
            mock_status.return_value = [
                {"category": "A", "pct_used": 79.9},
                {"category": "B", "pct_used": 80.0},
                {"category": "C", "pct_used": 100.0},
            ]

            result = analytics.budget_alert("2026-06")

        categories = [r["category"] for r in result]
        assert "A" not in categories
        assert "B" in categories
        assert "C" in categories

    def test_returns_empty_when_all_under_threshold(self):
        with patch("analytics.budget_status") as mock_status:
            mock_status.return_value = [
                {"category": "GROCERIES", "pct_used": 30.0},
            ]

            result = analytics.budget_alert("2026-06", threshold=80.0)

        assert result == []


# ── Phase 7: Search & detail ──────────────────────────────────────────────────


class TestGetCategories:
    """Phase 7: get_categories()"""

    def test_returns_sorted_distinct_categories(self, mock_db):
        mock_db.fetchall.return_value = [
            ("DINING",),
            ("GROCERIES",),
            ("TRANSPORTATION",),
        ]
        result = analytics.get_categories()
        assert result == ["DINING", "GROCERIES", "TRANSPORTATION"]

    def test_uses_coalesce_for_effective_category(self, mock_db):
        mock_db.fetchall.return_value = []
        analytics.get_categories()
        sql = mock_db.execute.call_args[0][0]
        assert "COALESCE(co.category, t.personal_finance_category)" in sql
        assert "LEFT JOIN category_overrides co" in sql


class TestSearchTransactions:
    """Phase 7: get_transactions(q=...) — full-text search."""

    def test_q_adds_ilike_condition(self, mock_db):
        mock_db.fetchall.return_value = []

        analytics.get_transactions(q="netflix")

        sql = mock_db.execute.call_args[0][0]
        params = mock_db.execute.call_args[0][1]
        assert "ILIKE" in sql
        assert any("netflix" in str(p) for p in params)

    def test_q_searches_name_and_merchant_and_note(self, mock_db):
        mock_db.fetchall.return_value = []

        analytics.get_transactions(q="coffee")

        sql = mock_db.execute.call_args[0][0]
        assert "t.name ILIKE" in sql
        assert "t.merchant_name ILIKE" in sql
        assert "tn.note ILIKE" in sql

    def test_joins_transaction_notes(self, mock_db):
        mock_db.fetchall.return_value = []

        analytics.get_transactions()

        sql = mock_db.execute.call_args[0][0]
        assert "LEFT JOIN transaction_notes tn" in sql

    def test_note_field_in_select(self, mock_db):
        mock_db.fetchall.return_value = [
            make_txn(note="business lunch"),
        ]

        result = analytics.get_transactions()
        assert result[0]["note"] == "business lunch"

    def test_no_q_no_ilike(self, mock_db):
        mock_db.fetchall.return_value = []

        analytics.get_transactions()

        sql = mock_db.execute.call_args[0][0]
        assert "ILIKE" not in sql


class TestGetTransactionDetail:
    """Phase 7: get_transaction_detail()"""

    def test_returns_none_when_not_found(self, mock_db):
        mock_db.fetchone.return_value = None

        with patch("db.get_transaction_tags", return_value=[]):
            result = analytics.get_transaction_detail("txn_missing")

        assert result is None

    def test_returns_detail_with_tags(self, mock_db):
        mock_db.fetchone.return_value = {
            **make_txn(transaction_id="txn_1"),
            "institution_name": "Chase",
            "override_category": None,
            "effective_category": "GROCERIES",
            "note": "weekly shop",
        }

        with patch("db.get_transaction_tags", return_value=["groceries", "weekly"]):
            result = analytics.get_transaction_detail("txn_1")

        assert result["transaction_id"] == "txn_1"
        assert result["tags"] == ["groceries", "weekly"]
        assert result["note"] == "weekly shop"


class TestResolveCategory:
    """Phase 3: resolve_category()"""

    def test_returns_override_when_set(self):
        txn = make_txn(transaction_id="txn_1", personal_finance_category="GROCERIES")
        with patch("analytics.effective_category", return_value="My Custom"):
            result = analytics.resolve_category(txn)
        assert result == "My Custom"

    def test_falls_back_to_plaid(self):
        txn = make_txn(
            transaction_id="txn_2", personal_finance_category="TRANSPORTATION"
        )
        with patch("analytics.effective_category", return_value=None):
            result = analytics.resolve_category(txn)
        assert result == "TRANSPORTATION"

    def test_falls_back_to_uncategorized(self):
        txn = make_txn(transaction_id="txn_3")
        txn["personal_finance_category"] = None
        with patch("analytics.effective_category", return_value=None):
            result = analytics.resolve_category(txn)
        assert result == "Uncategorized"


# ── apply_rules ───────────────────────────────────────────────────────────────


class TestApplyRules:
    """
    Tests for apply_rules():
    - dry_run queries ALL transactions; actual apply skips already-overridden ones
    - dry_run never writes overrides; actual apply does
    - merchant_name NULL falls back to name during matching
    - first matching rule wins (highest priority)
    """

    _RULE = {
        "id": 1,
        "match_field": "merchant_name",
        "match_pattern": "Netflix",
        "category": "Subscriptions",
        "priority": 0,
    }
    _TXN_MATCH = {
        "transaction_id": "txn_match",
        "name": "NETFLIX.COM",
        "merchant_name": "Netflix",
        "personal_finance_category": "ENTERTAINMENT",
    }
    _TXN_NO_MATCH = {
        "transaction_id": "txn_no_match",
        "name": "SPOTIFY",
        "merchant_name": "Spotify",
        "personal_finance_category": "ENTERTAINMENT",
    }

    @patch("db.list_category_rules")
    def test_returns_empty_when_no_rules(self, mock_rules):
        mock_rules.return_value = []
        assert analytics.apply_rules(dry_run=True) == []
        assert analytics.apply_rules(dry_run=False) == []

    @patch("db.upsert_category_override")
    @patch("db.list_category_rules")
    def test_dry_run_returns_matches_without_writing(
        self, mock_rules, mock_upsert, mock_db
    ):
        mock_rules.return_value = [self._RULE]
        mock_db.fetchall.return_value = [self._TXN_MATCH, self._TXN_NO_MATCH]

        results = analytics.apply_rules(dry_run=True)

        assert len(results) == 1
        assert results[0]["transaction_id"] == "txn_match"
        assert results[0]["new_category"] == "Subscriptions"
        assert results[0]["matched_on"] == "Netflix"
        mock_upsert.assert_not_called()

    @patch("db.upsert_category_override")
    @patch("db.list_category_rules")
    def test_apply_writes_override_for_match(self, mock_rules, mock_upsert, mock_db):
        mock_rules.return_value = [self._RULE]
        mock_db.fetchall.return_value = [self._TXN_MATCH]

        results = analytics.apply_rules(dry_run=False)

        assert len(results) == 1
        mock_upsert.assert_called_once_with("txn_match", "Subscriptions")

    @patch("db.upsert_category_override")
    @patch("db.list_category_rules")
    def test_apply_does_not_write_for_non_match(self, mock_rules, mock_upsert, mock_db):
        mock_rules.return_value = [self._RULE]
        mock_db.fetchall.return_value = [self._TXN_NO_MATCH]

        results = analytics.apply_rules(dry_run=False)

        assert results == []
        mock_upsert.assert_not_called()

    @patch("db.upsert_category_override")
    @patch("db.list_category_rules")
    def test_dry_run_sql_has_no_exists_filter(self, mock_rules, mock_upsert, mock_db):
        """dry_run must query ALL transactions, not just un-overridden ones."""
        mock_rules.return_value = [self._RULE]
        mock_db.fetchall.return_value = []

        analytics.apply_rules(dry_run=True)

        sql = mock_db.execute.call_args[0][0]
        assert "NOT EXISTS" not in sql

    @patch("db.upsert_category_override")
    @patch("db.list_category_rules")
    def test_apply_sql_has_not_exists_filter(self, mock_rules, mock_upsert, mock_db):
        """Actual apply must skip transactions that already have a manual override."""
        mock_rules.return_value = [self._RULE]
        mock_db.fetchall.return_value = []

        analytics.apply_rules(dry_run=False)

        sql = mock_db.execute.call_args[0][0]
        assert "NOT EXISTS" in sql

    @patch("db.upsert_category_override")
    @patch("db.list_category_rules")
    def test_merchant_name_null_falls_back_to_name(
        self, mock_rules, mock_upsert, mock_db
    ):
        """merchant_name=NULL should match via name fallback, mirroring the UI display."""
        mock_rules.return_value = [self._RULE]
        txn = {
            "transaction_id": "txn_null_merchant",
            "name": "NETFLIX SUBSCRIPTION",
            "merchant_name": None,
            "personal_finance_category": "ENTERTAINMENT",
        }
        mock_db.fetchall.return_value = [txn]

        results = analytics.apply_rules(dry_run=True)

        assert len(results) == 1
        assert results[0]["transaction_id"] == "txn_null_merchant"

    @patch("db.upsert_category_override")
    @patch("db.list_category_rules")
    def test_first_matching_rule_wins(self, mock_rules, mock_upsert, mock_db):
        """When multiple rules match a transaction, only the highest-priority one applies."""
        rules = [
            {**self._RULE, "id": 1, "category": "Subscriptions", "priority": 10},
            {**self._RULE, "id": 2, "category": "Entertainment", "priority": 5},
        ]
        mock_rules.return_value = rules
        mock_db.fetchall.return_value = [self._TXN_MATCH]

        results = analytics.apply_rules(dry_run=True)

        assert len(results) == 1
        assert results[0]["new_category"] == "Subscriptions"
        assert results[0]["rule_id"] == 1

    @patch("db.upsert_category_override")
    @patch("db.list_category_rules")
    def test_multiple_transactions_each_matched_independently(
        self, mock_rules, mock_upsert, mock_db
    ):
        rules = [
            {
                **self._RULE,
                "id": 1,
                "match_pattern": "Netflix",
                "category": "Subscriptions",
            },
            {
                "id": 2,
                "match_field": "merchant_name",
                "match_pattern": "Spotify",
                "category": "Music",
                "priority": 0,
            },
        ]
        mock_rules.return_value = rules
        mock_db.fetchall.return_value = [self._TXN_MATCH, self._TXN_NO_MATCH]

        results = analytics.apply_rules(dry_run=False)

        assert len(results) == 2
        cats = {r["transaction_id"]: r["new_category"] for r in results}
        assert cats["txn_match"] == "Subscriptions"
        assert cats["txn_no_match"] == "Music"
