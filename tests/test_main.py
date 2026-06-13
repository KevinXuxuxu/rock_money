"""Smoke tests for CLI command handlers — all analytics calls are mocked."""

from unittest.mock import patch

import main


class TestCliSmoke:
    """Smoke-test each handler with mocked dependencies."""

    @patch("analytics.get_accounts")
    def test_cmd_accounts_empty(self, mock_get, capsys):
        mock_get.return_value = []
        main.cmd_accounts(None)
        out = capsys.readouterr().out
        assert "No accounts" in out

    @patch("analytics.get_accounts")
    def test_cmd_accounts_with_data(self, mock_get, capsys):
        from tests.conftest import make_account

        mock_get.return_value = [
            make_account(
                name="Checking",
                subtype="checking",
                institution_name="Chase",
                txn_count=42,
            ),
        ]
        main.cmd_accounts(None)
        out = capsys.readouterr().out
        assert "Checking" in out
        assert "Chase" in out
        assert "42" in out

    @patch("analytics.get_transactions")
    def test_cmd_list_txns_empty(self, mock_get, capsys):
        mock_get.return_value = []
        from argparse import Namespace

        main.cmd_list_txns(
            Namespace(limit=50, account=None, category=None, month=None, pending=False)
        )
        out = capsys.readouterr().out
        assert "No transactions" in out

    @patch("analytics.get_transactions")
    def test_cmd_list_txns_passes_filters(self, mock_get, capsys):
        """Verify kwargs are passed through to get_transactions."""
        mock_get.return_value = []
        from argparse import Namespace

        main.cmd_list_txns(
            Namespace(
                limit=10,
                account="acct_x",
                category="INCOME",
                month="2026-06",
                pending=True,
            )
        )
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["limit"] == 10
        assert call_kwargs["account_id"] == "acct_x"
        assert call_kwargs["category"] == "INCOME"
        assert call_kwargs["month"] == "2026-06"
        assert call_kwargs["pending"] is True

    @patch("analytics.get_transactions")
    def test_cmd_list_txns_formats_credit_amounts(self, mock_get, capsys):
        """Negative amounts (credits) shown with minus prefix."""
        from tests.conftest import make_txn

        mock_get.return_value = [
            make_txn(amount=-500.00, date="2026-06-01", merchant_name="Employer"),
        ]
        from argparse import Namespace

        main.cmd_list_txns(
            Namespace(limit=50, account=None, category=None, month=None, pending=False)
        )
        out = capsys.readouterr().out
        assert "-$500.00" in out

    @patch("analytics.get_transactions")
    def test_cmd_list_txns_shows_effective_category(self, mock_get, capsys):
        """The effective_category field (override > Plaid) is displayed."""
        from tests.conftest import make_txn

        mock_get.return_value = [
            make_txn(effective_category="My Override"),
        ]
        from argparse import Namespace

        main.cmd_list_txns(
            Namespace(limit=50, account=None, category=None, month=None, pending=False)
        )
        out = capsys.readouterr().out
        assert "My Override" in out

    @patch("analytics.get_transactions")
    def test_cmd_list_txns_cat_falls_back(self, mock_get, capsys):
        """When effective_category is None, display shows '—'."""
        from tests.conftest import make_txn

        mock_get.return_value = [
            make_txn(effective_category=None),
        ]
        from argparse import Namespace

        main.cmd_list_txns(
            Namespace(limit=50, account=None, category=None, month=None, pending=False)
        )
        out = capsys.readouterr().out
        assert "—" in out

    @patch("analytics.spend_by_category")
    def test_cmd_report_spend(self, mock_spend, capsys):
        mock_spend.return_value = [
            {"category": "GROCERIES", "total_spend": 350.00, "txn_count": 8},
        ]
        from argparse import Namespace

        main.cmd_report_spend(Namespace(month="2026-06"))
        out = capsys.readouterr().out
        assert "GROCERIES" in out
        assert "350.00" in out
        assert "TOTAL" in out

    @patch("analytics.spend_by_category")
    def test_cmd_report_spend_defaults_current_month(self, mock_spend, capsys):
        mock_spend.return_value = []
        from argparse import Namespace

        main.cmd_report_spend(Namespace(month=None))
        # Should call with current YYYY-MM
        called_month = mock_spend.call_args.args[0]
        import datetime

        expected = datetime.datetime.now().strftime("%Y-%m")
        assert called_month == expected

    @patch("analytics.monthly_summary")
    def test_cmd_report_monthly(self, mock_summary, capsys):
        mock_summary.return_value = [
            {
                "month": "2026-06-01",
                "income": 5000.00,
                "spend": 3200.00,
                "net": 1800.00,
            },
        ]
        from argparse import Namespace

        main.cmd_report_monthly(Namespace(months=12))
        out = capsys.readouterr().out
        assert "5,000.00" in out
        assert "3,200.00" in out
        assert "1,800.00" in out


class TestPhase7Commands:
    """Phase 7: note, tag-add, tag-remove, search, view-* commands."""

    @patch("db.upsert_transaction_note")
    def test_cmd_note_set(self, mock_upsert, capsys):
        from argparse import Namespace

        main.cmd_note(Namespace(transaction_id="txn_1", note="Business lunch"))
        mock_upsert.assert_called_once_with("txn_1", "Business lunch")
        assert "saved" in capsys.readouterr().out.lower()

    @patch("db.delete_transaction_note")
    def test_cmd_note_clear(self, mock_delete, capsys):
        from argparse import Namespace

        main.cmd_note(Namespace(transaction_id="txn_1", note=""))
        mock_delete.assert_called_once_with("txn_1")
        assert "cleared" in capsys.readouterr().out.lower()

    @patch("db.add_transaction_tag")
    def test_cmd_tag_add(self, mock_add, capsys):
        from argparse import Namespace

        main.cmd_tag_add(Namespace(transaction_id="txn_1", tag="Travel"))
        mock_add.assert_called_once_with("txn_1", "travel")
        assert "travel" in capsys.readouterr().out

    @patch("db.remove_transaction_tag")
    def test_cmd_tag_remove_found(self, mock_remove, capsys):
        mock_remove.return_value = True
        from argparse import Namespace

        main.cmd_tag_remove(Namespace(transaction_id="txn_1", tag="travel"))
        assert "removed" in capsys.readouterr().out

    @patch("db.remove_transaction_tag")
    def test_cmd_tag_remove_not_found(self, mock_remove, capsys):
        mock_remove.return_value = False
        from argparse import Namespace

        main.cmd_tag_remove(Namespace(transaction_id="txn_1", tag="ghost"))
        assert "not found" in capsys.readouterr().out

    @patch("analytics.get_transactions")
    def test_cmd_search_with_results(self, mock_get, capsys):
        from tests.conftest import make_txn

        mock_get.return_value = [make_txn(merchant_name="Netflix", amount=15.99)]
        from argparse import Namespace

        main.cmd_search(Namespace(query="netflix", month=None, category=None, limit=50))
        out = capsys.readouterr().out
        assert "Netflix" in out
        assert mock_get.call_args.kwargs["q"] == "netflix"

    @patch("analytics.get_transactions")
    def test_cmd_search_no_results(self, mock_get, capsys):
        mock_get.return_value = []
        from argparse import Namespace

        main.cmd_search(Namespace(query="xyzzy", month=None, category=None, limit=50))
        assert "No transactions" in capsys.readouterr().out

    @patch("db.upsert_view")
    def test_cmd_view_save(self, mock_upsert, capsys):
        from argparse import Namespace

        main.cmd_view_save(
            Namespace(name="My View", search="netflix", month="", category="")
        )
        mock_upsert.assert_called_once()
        assert "saved" in capsys.readouterr().out.lower()

    @patch("db.list_views")
    def test_cmd_view_list_empty(self, mock_list, capsys):
        mock_list.return_value = []
        from argparse import Namespace

        main.cmd_view_list(Namespace())
        assert "No saved views" in capsys.readouterr().out

    @patch("db.list_views")
    def test_cmd_view_list_with_data(self, mock_list, capsys):
        mock_list.return_value = [
            {"name": "Netflix", "filters": {"q": "netflix", "month": ""}},
        ]
        from argparse import Namespace

        main.cmd_view_list(Namespace())
        assert "Netflix" in capsys.readouterr().out

    @patch("db.delete_view")
    def test_cmd_view_delete_found(self, mock_delete, capsys):
        mock_delete.return_value = True
        from argparse import Namespace

        main.cmd_view_delete(Namespace(name="My View"))
        assert "deleted" in capsys.readouterr().out

    @patch("db.delete_view")
    def test_cmd_view_delete_not_found(self, mock_delete, capsys):
        mock_delete.return_value = False
        from argparse import Namespace

        main.cmd_view_delete(Namespace(name="Ghost"))
        assert "No view" in capsys.readouterr().out


class TestBudgetCommands:
    """Phase 4: budget-set, budget-list, budget-delete, budget-status, budget-alert"""

    @patch("db.upsert_budget")
    def test_cmd_budget_set(self, mock_upsert, capsys):
        from argparse import Namespace

        main.cmd_budget_set(Namespace(category="Groceries", amount=600.0))
        out = capsys.readouterr().out
        mock_upsert.assert_called_once_with("Groceries", 600.0)
        assert "Groceries" in out
        assert "600.00" in out

    @patch("db.list_budgets")
    def test_cmd_budget_list_empty(self, mock_list, capsys):
        mock_list.return_value = []
        from argparse import Namespace

        main.cmd_budget_list(Namespace())
        out = capsys.readouterr().out
        assert "No budgets" in out

    @patch("db.list_budgets")
    def test_cmd_budget_list_with_data(self, mock_list, capsys):
        mock_list.return_value = [
            {"category": "Groceries", "monthly_limit": 600.00},
        ]
        from argparse import Namespace

        main.cmd_budget_list(Namespace())
        out = capsys.readouterr().out
        assert "Groceries" in out
        assert "600.00" in out

    @patch("db.delete_budget")
    def test_cmd_budget_delete_found(self, mock_delete, capsys):
        mock_delete.return_value = True
        from argparse import Namespace

        main.cmd_budget_delete(Namespace(category="Groceries"))
        out = capsys.readouterr().out
        assert "removed" in out

    @patch("db.delete_budget")
    def test_cmd_budget_delete_not_found(self, mock_delete, capsys):
        mock_delete.return_value = False
        from argparse import Namespace

        main.cmd_budget_delete(Namespace(category="Groceries"))
        out = capsys.readouterr().out
        assert "No budget" in out

    @patch("analytics.budget_status")
    def test_cmd_budget_status(self, mock_status, capsys):
        mock_status.return_value = [
            {
                "category": "GROCERIES",
                "monthly_limit": 600.0,
                "actual_spend": 350.0,
                "remaining": 250.0,
                "pct_used": 58.3,
            },
        ]
        from argparse import Namespace

        main.cmd_budget_status(Namespace(month="2026-06"))
        out = capsys.readouterr().out
        assert "GROCERIES" in out
        assert "600.00" in out
        assert "350.00" in out
        assert "58.3" in out

    @patch("analytics.budget_status")
    def test_cmd_budget_status_defaults_current_month(self, mock_status, capsys):
        mock_status.return_value = []
        from argparse import Namespace

        main.cmd_budget_status(Namespace(month=None))
        import datetime

        called_month = mock_status.call_args.args[0]
        assert called_month == datetime.datetime.now().strftime("%Y-%m")

    @patch("analytics.budget_alert")
    def test_cmd_budget_alert_with_alerts(self, mock_alert, capsys):
        mock_alert.return_value = [
            {
                "category": "DINING",
                "monthly_limit": 200.0,
                "actual_spend": 190.0,
                "pct_used": 95.0,
            },
        ]
        from argparse import Namespace

        main.cmd_budget_alert(Namespace(month="2026-06", threshold=80.0))
        out = capsys.readouterr().out
        mock_alert.assert_called_once_with("2026-06", threshold=80.0)
        assert "DINING" in out
        assert "95.0" in out

    @patch("analytics.budget_alert")
    def test_cmd_budget_alert_empty(self, mock_alert, capsys):
        mock_alert.return_value = []
        from argparse import Namespace

        main.cmd_budget_alert(Namespace(month="2026-06", threshold=80.0))
        out = capsys.readouterr().out
        assert "No categories" in out


class TestCategoryCommands:
    """Phase 3: categorize, uncategorize, rule-* commands"""

    @patch("db.upsert_category_override")
    def test_cmd_categorize(self, mock_upsert, capsys):
        from argparse import Namespace

        main.cmd_categorize(Namespace(transaction_id="txn_abc", category="Groceries"))
        out = capsys.readouterr().out
        mock_upsert.assert_called_once_with("txn_abc", "Groceries")
        assert "txn_abc" in out
        assert "Groceries" in out

    @patch("db.delete_category_override")
    def test_cmd_uncategorize_found(self, mock_delete, capsys):
        mock_delete.return_value = True
        from argparse import Namespace

        main.cmd_uncategorize(Namespace(transaction_id="txn_abc"))
        out = capsys.readouterr().out
        assert "removed" in out.lower()

    @patch("db.delete_category_override")
    def test_cmd_uncategorize_not_found(self, mock_delete, capsys):
        mock_delete.return_value = False
        from argparse import Namespace

        main.cmd_uncategorize(Namespace(transaction_id="txn_abc"))
        out = capsys.readouterr().out
        assert "No override" in out

    @patch("db.add_category_rule")
    def test_cmd_rule_add(self, mock_add, capsys):
        mock_add.return_value = 7
        from argparse import Namespace

        main.cmd_rule_add(
            Namespace(
                match="Netflix",
                field="merchant_name",
                category="Subscriptions",
                priority=5,
            )
        )
        out = capsys.readouterr().out
        mock_add.assert_called_once_with(
            match_pattern="Netflix",
            match_field="merchant_name",
            category="Subscriptions",
            priority=5,
        )
        assert "7" in out
        assert "Netflix" in out

    @patch("db.list_category_rules")
    def test_cmd_rule_list_empty(self, mock_list, capsys):
        mock_list.return_value = []
        from argparse import Namespace

        main.cmd_rule_list(Namespace())
        out = capsys.readouterr().out
        assert "No rules" in out

    @patch("db.list_category_rules")
    def test_cmd_rule_list_with_data(self, mock_list, capsys):
        mock_list.return_value = [
            {
                "id": 1,
                "match_field": "merchant_name",
                "match_pattern": "Netflix",
                "category": "Subscriptions",
                "priority": 10,
            },
        ]
        from argparse import Namespace

        main.cmd_rule_list(Namespace())
        out = capsys.readouterr().out
        assert "Netflix" in out
        assert "Subscriptions" in out

    @patch("db.delete_category_rule")
    def test_cmd_rule_remove_found(self, mock_delete, capsys):
        mock_delete.return_value = True
        from argparse import Namespace

        main.cmd_rule_remove(Namespace(rule_id=3))
        out = capsys.readouterr().out
        assert "deleted" in out

    @patch("db.delete_category_rule")
    def test_cmd_rule_remove_not_found(self, mock_delete, capsys):
        mock_delete.return_value = False
        from argparse import Namespace

        main.cmd_rule_remove(Namespace(rule_id=99))
        out = capsys.readouterr().out
        assert "No rule" in out

    @patch("analytics.apply_rules")
    def test_cmd_rule_apply_matches(self, mock_apply, capsys):
        mock_apply.return_value = [
            {
                "transaction_id": "txn_1",
                "old_category": None,
                "new_category": "Subscriptions",
            },
        ]
        from argparse import Namespace

        main.cmd_rule_apply(Namespace(dry_run=False))
        out = capsys.readouterr().out
        mock_apply.assert_called_once_with(dry_run=False)
        assert "Matched 1" in out

    @patch("analytics.apply_rules")
    def test_cmd_rule_apply_dry_run(self, mock_apply, capsys):
        mock_apply.return_value = [
            {
                "transaction_id": "txn_1",
                "old_category": None,
                "new_category": "Subscriptions",
            },
        ]
        from argparse import Namespace

        main.cmd_rule_apply(Namespace(dry_run=True))
        out = capsys.readouterr().out
        mock_apply.assert_called_once_with(dry_run=True)
        assert "Would match" in out

    @patch("analytics.apply_rules")
    def test_cmd_rule_apply_empty(self, mock_apply, capsys):
        mock_apply.return_value = []
        from argparse import Namespace

        main.cmd_rule_apply(Namespace(dry_run=False))
        out = capsys.readouterr().out
        assert "No matching" in out
