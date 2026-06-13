"""Tests for web_server.py Flask routes — all analytics calls are mocked."""

from unittest.mock import patch

import pytest

import web_server
from tests.conftest import make_account, make_txn


@pytest.fixture
def client():
    web_server.app.config["TESTING"] = True
    with web_server.app.test_client() as c:
        yield c


def _spend_rows():
    return [
        {"category": "FOOD_AND_DRINK", "total_spend": 350.0, "txn_count": 8},
        {"category": "TRANSPORTATION", "total_spend": 80.0, "txn_count": 3},
    ]


def _summary_rows():
    return [
        {"month": "2026-05-01", "income": 5000.0, "spend": 3000.0, "net": 2000.0},
        {"month": "2026-06-01", "income": 5100.0, "spend": 3200.0, "net": 1900.0},
    ]


class TestDashboard:
    @patch("analytics.monthly_summary")
    @patch("analytics.spend_by_category")
    @patch("analytics.get_transactions")
    @patch("analytics.get_accounts")
    def test_returns_200(self, mock_accts, mock_txns, mock_spend, mock_summary, client):
        mock_accts.return_value = [make_account()]
        mock_txns.return_value = [make_txn()]
        mock_spend.return_value = _spend_rows()
        mock_summary.return_value = _summary_rows()

        resp = client.get("/")
        assert resp.status_code == 200

    @patch("analytics.monthly_summary")
    @patch("analytics.spend_by_category")
    @patch("analytics.get_transactions")
    @patch("analytics.get_accounts")
    def test_shows_account_count(
        self, mock_accts, mock_txns, mock_spend, mock_summary, client
    ):
        mock_accts.return_value = [
            make_account(name="Checking"),
            make_account(name="Savings"),
        ]
        mock_txns.return_value = []
        mock_spend.return_value = []
        mock_summary.return_value = []

        resp = client.get("/")
        assert b"2" in resp.data

    @patch("analytics.monthly_summary")
    @patch("analytics.spend_by_category")
    @patch("analytics.get_transactions")
    @patch("analytics.get_accounts")
    def test_shows_spend_category(
        self, mock_accts, mock_txns, mock_spend, mock_summary, client
    ):
        mock_accts.return_value = []
        mock_txns.return_value = []
        mock_spend.return_value = _spend_rows()
        mock_summary.return_value = []

        resp = client.get("/")
        assert b"FOOD_AND_DRINK" in resp.data

    @patch("analytics.monthly_summary")
    @patch("analytics.spend_by_category")
    @patch("analytics.get_transactions")
    @patch("analytics.get_accounts")
    def test_shows_recent_transactions(
        self, mock_accts, mock_txns, mock_spend, mock_summary, client
    ):
        mock_accts.return_value = []
        mock_txns.return_value = [make_txn(merchant_name="Netflix", amount=15.99)]
        mock_spend.return_value = []
        mock_summary.return_value = []

        resp = client.get("/")
        assert b"Netflix" in resp.data


class TestAccountsPage:
    @patch("analytics.get_accounts")
    def test_returns_200(self, mock_accts, client):
        mock_accts.return_value = [make_account()]
        resp = client.get("/accounts")
        assert resp.status_code == 200

    @patch("analytics.get_accounts")
    def test_shows_account_name(self, mock_accts, client):
        mock_accts.return_value = [
            make_account(name="Premium Checking", institution_name="Chase")
        ]
        resp = client.get("/accounts")
        assert b"Premium Checking" in resp.data
        assert b"Chase" in resp.data

    @patch("analytics.get_accounts")
    def test_empty_state(self, mock_accts, client):
        mock_accts.return_value = []
        resp = client.get("/accounts")
        assert resp.status_code == 200
        assert b"No accounts" in resp.data


class TestTransactionsPage:
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_returns_200(self, mock_txns, mock_accts, client):
        mock_accts.return_value = [make_account()]
        mock_txns.return_value = [make_txn()]
        resp = client.get("/transactions")
        assert resp.status_code == 200

    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_shows_merchant_name(self, mock_txns, mock_accts, client):
        mock_accts.return_value = []
        mock_txns.return_value = [make_txn(merchant_name="Whole Foods")]
        resp = client.get("/transactions")
        assert b"Whole Foods" in resp.data

    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_filter_params_passed_through(self, mock_txns, mock_accts, client):
        mock_accts.return_value = []
        mock_txns.return_value = []

        client.get("/transactions?month=2026-05&category=GROCERIES&limit=25")

        call_kwargs = mock_txns.call_args.kwargs
        assert call_kwargs["month"] == "2026-05"
        assert call_kwargs["category"] == "GROCERIES"
        assert call_kwargs["limit"] == 25

    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_empty_state(self, mock_txns, mock_accts, client):
        mock_accts.return_value = []
        mock_txns.return_value = []
        resp = client.get("/transactions")
        assert resp.status_code == 200
        assert b"No transactions" in resp.data

    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_shows_effective_category(self, mock_txns, mock_accts, client):
        mock_accts.return_value = []
        mock_txns.return_value = [make_txn(effective_category="My Custom")]
        resp = client.get("/transactions")
        assert b"My Custom" in resp.data


class TestSearchPage:
    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_returns_200(self, mock_txns, mock_accts, mock_cats, mock_views, client):
        mock_txns.return_value = []
        mock_accts.return_value = []
        mock_cats.return_value = ["GROCERIES", "DINING"]
        mock_views.return_value = []
        resp = client.get("/search")
        assert resp.status_code == 200

    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_q_passed_to_get_transactions(
        self, mock_txns, mock_accts, mock_cats, mock_views, client
    ):
        mock_txns.return_value = []
        mock_accts.return_value = []
        mock_cats.return_value = []
        mock_views.return_value = []

        client.get("/search?q=netflix")

        assert mock_txns.call_args.kwargs["q"] == "netflix"

    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_shows_result_merchant(
        self, mock_txns, mock_accts, mock_cats, mock_views, client
    ):
        mock_txns.return_value = [
            make_txn(merchant_name="Starbucks", effective_category="COFFEE")
        ]
        mock_accts.return_value = []
        mock_cats.return_value = ["COFFEE"]
        mock_views.return_value = []

        resp = client.get("/search?q=starbucks")
        assert b"Starbucks" in resp.data

    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_no_query_shows_no_results(
        self, mock_txns, mock_accts, mock_cats, mock_views, client
    ):
        mock_accts.return_value = []
        mock_cats.return_value = []
        mock_views.return_value = []

        resp = client.get("/search")
        mock_txns.assert_not_called()
        assert resp.status_code == 200

    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    def test_shows_saved_views(self, mock_accts, mock_cats, mock_views, client):
        mock_accts.return_value = []
        mock_cats.return_value = []
        mock_views.return_value = [
            {
                "name": "Netflix",
                "filters": {"q": "netflix"},
                "query_string": "q=netflix",
            },
        ]

        resp = client.get("/search")
        assert b"Netflix" in resp.data

    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_category_dropdown_populated(
        self, mock_txns, mock_accts, mock_cats, mock_views, client
    ):
        mock_txns.return_value = []
        mock_accts.return_value = []
        mock_cats.return_value = ["DINING", "GROCERIES", "TRANSPORTATION"]
        mock_views.return_value = []

        resp = client.get("/search")
        assert b"GROCERIES" in resp.data
        assert b"TRANSPORTATION" in resp.data


class TestTransactionDetailPage:
    @patch("db.get_transaction_tags")
    @patch("analytics.get_transaction_detail")
    def test_returns_200(self, mock_detail, mock_tags, client):
        mock_detail.return_value = {
            **make_txn(transaction_id="txn_1"),
            "institution_name": "Chase",
            "override_category": None,
            "effective_category": "GROCERIES",
            "note": None,
            "tags": [],
        }
        resp = client.get("/transactions/txn_1")
        assert resp.status_code == 200

    @patch("analytics.get_transaction_detail")
    def test_returns_404_when_not_found(self, mock_detail, client):
        mock_detail.return_value = None
        resp = client.get("/transactions/txn_missing")
        assert resp.status_code == 404

    @patch("db.get_transaction_tags")
    @patch("analytics.get_transaction_detail")
    def test_shows_note(self, mock_detail, mock_tags, client):
        mock_detail.return_value = {
            **make_txn(transaction_id="txn_1"),
            "institution_name": "Chase",
            "override_category": None,
            "effective_category": "GROCERIES",
            "note": "business dinner",
            "tags": [],
        }
        resp = client.get("/transactions/txn_1")
        assert b"business dinner" in resp.data

    @patch("db.get_transaction_tags")
    @patch("analytics.get_transaction_detail")
    def test_shows_tags(self, mock_detail, mock_tags, client):
        mock_detail.return_value = {
            **make_txn(transaction_id="txn_1"),
            "institution_name": "Chase",
            "override_category": None,
            "effective_category": "GROCERIES",
            "note": None,
            "tags": ["travel", "business"],
        }
        resp = client.get("/transactions/txn_1")
        assert b"travel" in resp.data
        assert b"business" in resp.data


class TestReportsPage:
    @patch("analytics.budget_status")
    @patch("analytics.spend_by_category")
    @patch("analytics.monthly_summary")
    def test_returns_200(self, mock_summary, mock_spend, mock_budgets, client):
        mock_summary.return_value = _summary_rows()
        mock_spend.return_value = _spend_rows()
        mock_budgets.return_value = []
        resp = client.get("/reports")
        assert resp.status_code == 200

    @patch("analytics.budget_status")
    @patch("analytics.spend_by_category")
    @patch("analytics.monthly_summary")
    def test_shows_monthly_data(self, mock_summary, mock_spend, mock_budgets, client):
        mock_summary.return_value = _summary_rows()
        mock_spend.return_value = []
        mock_budgets.return_value = []
        resp = client.get("/reports")
        assert b"5,000.00" in resp.data
        assert b"3,000.00" in resp.data

    @patch("analytics.budget_status")
    @patch("analytics.spend_by_category")
    @patch("analytics.monthly_summary")
    def test_month_param_passed(self, mock_summary, mock_spend, mock_budgets, client):
        mock_summary.return_value = []
        mock_spend.return_value = []
        mock_budgets.return_value = []

        client.get("/reports?month=2026-03")

        called_month = mock_spend.call_args.args[0]
        assert called_month == "2026-03"

    @patch("analytics.budget_status")
    @patch("analytics.spend_by_category")
    @patch("analytics.monthly_summary")
    def test_shows_budget_status(self, mock_summary, mock_spend, mock_budgets, client):
        mock_summary.return_value = []
        mock_spend.return_value = []
        mock_budgets.return_value = [
            {
                "category": "GROCERIES",
                "monthly_limit": 600.0,
                "actual_spend": 540.0,
                "remaining": 60.0,
                "pct_used": 90.0,
            }
        ]
        resp = client.get("/reports")
        assert b"GROCERIES" in resp.data
        assert b"90.0" in resp.data
