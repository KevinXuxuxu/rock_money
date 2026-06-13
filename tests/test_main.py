"""Smoke tests for CLI command handlers — all analytics calls are mocked."""
from unittest.mock import patch

import pytest
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
            make_account(name="Checking", subtype="checking", institution_name="Chase", txn_count=42),
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
        main.cmd_list_txns(Namespace(limit=50, account=None, category=None, month=None, pending=False))
        out = capsys.readouterr().out
        assert "No transactions" in out

    @patch("analytics.get_transactions")
    def test_cmd_list_txns_passes_filters(self, mock_get, capsys):
        """Verify kwargs are passed through to get_transactions."""
        mock_get.return_value = []
        from argparse import Namespace
        main.cmd_list_txns(Namespace(limit=10, account="acct_x", category="INCOME", month="2026-06", pending=True))
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
        main.cmd_list_txns(Namespace(limit=50, account=None, category=None, month=None, pending=False))
        out = capsys.readouterr().out
        assert "-$500.00" in out

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
            {"month": "2026-06-01", "income": 5000.00, "spend": 3200.00, "net": 1800.00},
        ]
        from argparse import Namespace
        main.cmd_report_monthly(Namespace(months=12))
        out = capsys.readouterr().out
        assert "5,000.00" in out
        assert "3,200.00" in out
        assert "1,800.00" in out
