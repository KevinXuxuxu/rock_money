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
    @patch("analytics.income_by_category")
    @patch("analytics.monthly_summary")
    @patch("analytics.spend_by_category")
    @patch("analytics.get_transactions")
    @patch("analytics.get_accounts")
    def test_returns_200(
        self, mock_accts, mock_txns, mock_spend, mock_summary, mock_income, client
    ):
        mock_accts.return_value = [make_account()]
        mock_txns.return_value = [make_txn()]
        mock_spend.return_value = _spend_rows()
        mock_summary.return_value = _summary_rows()
        mock_income.return_value = []

        resp = client.get("/")
        assert resp.status_code == 200

    @patch("analytics.income_by_category")
    @patch("analytics.monthly_summary")
    @patch("analytics.spend_by_category")
    @patch("analytics.get_transactions")
    @patch("analytics.get_accounts")
    def test_shows_account_count(
        self, mock_accts, mock_txns, mock_spend, mock_summary, mock_income, client
    ):
        mock_accts.return_value = [
            make_account(name="Checking"),
            make_account(name="Savings"),
        ]
        mock_txns.return_value = []
        mock_spend.return_value = []
        mock_summary.return_value = []
        mock_income.return_value = []

        resp = client.get("/")
        assert b"2" in resp.data

    @patch("analytics.income_by_category")
    @patch("analytics.monthly_summary")
    @patch("analytics.spend_by_category")
    @patch("analytics.get_transactions")
    @patch("analytics.get_accounts")
    def test_shows_spend_category(
        self, mock_accts, mock_txns, mock_spend, mock_summary, mock_income, client
    ):
        mock_accts.return_value = []
        mock_txns.return_value = []
        mock_spend.return_value = _spend_rows()
        mock_summary.return_value = []
        mock_income.return_value = []

        resp = client.get("/")
        assert b"FOOD_AND_DRINK" in resp.data

    @patch("analytics.income_by_category")
    @patch("analytics.monthly_summary")
    @patch("analytics.spend_by_category")
    @patch("analytics.get_transactions")
    @patch("analytics.get_accounts")
    def test_shows_recent_transactions(
        self, mock_accts, mock_txns, mock_spend, mock_summary, mock_income, client
    ):
        mock_accts.return_value = []
        mock_txns.return_value = [make_txn(merchant_name="Netflix", amount=15.99)]
        mock_spend.return_value = []
        mock_summary.return_value = []
        mock_income.return_value = []

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


class TestSyncAccounts:
    @patch("sync.sync_all")
    def test_redirects_on_success(self, mock_sync, client):
        mock_sync.return_value = None
        resp = client.post("/accounts/sync")
        assert resp.status_code == 302
        assert "/accounts" in resp.headers["Location"]
        mock_sync.assert_called_once_with()

    @patch("analytics.get_accounts")
    @patch("sync.sync_all")
    def test_flashes_success(self, mock_sync, mock_accts, client):
        mock_sync.return_value = None
        mock_accts.return_value = []
        resp = client.post("/accounts/sync", follow_redirects=True)
        assert b"Sync complete" in resp.data

    @patch("analytics.get_accounts")
    @patch("sync.sync_all")
    def test_flashes_error_on_failure(self, mock_sync, mock_accts, client):
        mock_sync.side_effect = RuntimeError("connection refused")
        mock_accts.return_value = []
        resp = client.post("/accounts/sync", follow_redirects=True)
        assert b"Sync failed" in resp.data
        assert b"connection refused" in resp.data


class TestApiLinkToken:
    @patch("web_server._get_plaid")
    def test_returns_link_token(self, mock_get_plaid, client):
        mock_get_plaid.return_value.create_link_token.return_value = "link-sandbox-abc"
        resp = client.get("/api/link-token")
        assert resp.status_code == 200
        assert resp.get_json()["link_token"] == "link-sandbox-abc"

    @patch("web_server._get_plaid")
    def test_returns_error_on_failure(self, mock_get_plaid, client):
        mock_get_plaid.return_value.create_link_token.side_effect = RuntimeError(
            "bad key"
        )
        resp = client.get("/api/link-token")
        assert resp.status_code == 500
        assert "error" in resp.get_json()


class TestApiExchange:
    @patch("db.upsert_item")
    @patch("web_server._get_plaid")
    def test_exchanges_and_saves(self, mock_get_plaid, mock_upsert, client):
        plaid = mock_get_plaid.return_value
        plaid.exchange_public_token.return_value = ("access-sandbox-123", "item-abc")
        plaid.get_institution_name.return_value = ("ins_1", "Chase")

        resp = client.post(
            "/api/exchange",
            json={"public_token": "public-sandbox-xyz"},
        )
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert data["institution_name"] == "Chase"
        mock_upsert.assert_called_once_with(
            "item-abc", "access-sandbox-123", "ins_1", "Chase"
        )

    def test_missing_public_token_returns_400(self, client):
        resp = client.post("/api/exchange", json={})
        assert resp.status_code == 400
        assert resp.get_json()["ok"] is False

    @patch("web_server._get_plaid")
    def test_exchange_failure_returns_error(self, mock_get_plaid, client):
        mock_get_plaid.return_value.exchange_public_token.side_effect = RuntimeError(
            "invalid token"
        )
        resp = client.post(
            "/api/exchange",
            json={"public_token": "public-sandbox-bad"},
        )
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["ok"] is False
        assert "invalid token" in data["error"]


class TestTransactionsPage:
    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_returns_200(self, mock_txns, mock_accts, mock_cats, mock_views, client):
        mock_accts.return_value = [make_account()]
        mock_txns.return_value = [make_txn()]
        mock_cats.return_value = []
        mock_views.return_value = []
        resp = client.get("/transactions")
        assert resp.status_code == 200

    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_shows_merchant_name(
        self, mock_txns, mock_accts, mock_cats, mock_views, client
    ):
        mock_accts.return_value = []
        mock_txns.return_value = [make_txn(merchant_name="Whole Foods")]
        mock_cats.return_value = []
        mock_views.return_value = []
        resp = client.get("/transactions")
        assert b"Whole Foods" in resp.data

    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_shows_net_sum_of_displayed(
        self, mock_txns, mock_accts, mock_cats, mock_views, client
    ):
        """Header shows the net total of the displayed rows (debits + credits)."""
        mock_accts.return_value = []
        # 100.00 debit + (-25.50) credit = 74.50 net.
        mock_txns.return_value = [make_txn(amount=100.00), make_txn(amount=-25.50)]
        mock_cats.return_value = []
        mock_views.return_value = []
        resp = client.get("/transactions")
        assert b"net" in resp.data
        assert b"$74.50" in resp.data

    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_filter_params_passed_through(
        self, mock_txns, mock_accts, mock_cats, mock_views, client
    ):
        mock_accts.return_value = []
        mock_txns.return_value = []
        mock_cats.return_value = []
        mock_views.return_value = []

        client.get("/transactions?month=2026-05&category=GROCERIES&limit=25")

        call_kwargs = mock_txns.call_args.kwargs
        assert call_kwargs["month"] == "2026-05"
        assert call_kwargs["category"] == "GROCERIES"
        assert call_kwargs["limit"] == 25

    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_empty_state(self, mock_txns, mock_accts, mock_cats, mock_views, client):
        mock_accts.return_value = []
        mock_txns.return_value = []
        mock_cats.return_value = []
        mock_views.return_value = []
        resp = client.get("/transactions")
        assert resp.status_code == 200
        assert b"No transactions" in resp.data

    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_shows_effective_category(
        self, mock_txns, mock_accts, mock_cats, mock_views, client
    ):
        mock_accts.return_value = []
        mock_txns.return_value = [make_txn(effective_category="My Custom")]
        mock_cats.return_value = []
        mock_views.return_value = []
        resp = client.get("/transactions")
        assert b"My Custom" in resp.data

    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_q_filter_passed_through(
        self, mock_txns, mock_accts, mock_cats, mock_views, client
    ):
        mock_accts.return_value = []
        mock_txns.return_value = []
        mock_cats.return_value = []
        mock_views.return_value = []

        client.get("/transactions?q=netflix")

        assert mock_txns.call_args.kwargs["q"] == "netflix"

    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_category_dropdown_populated(
        self, mock_txns, mock_accts, mock_cats, mock_views, client
    ):
        mock_accts.return_value = []
        mock_txns.return_value = []
        mock_cats.return_value = ["DINING", "GROCERIES", "TRANSPORTATION"]
        mock_views.return_value = []

        resp = client.get("/transactions")
        assert b"GROCERIES" in resp.data
        assert b"TRANSPORTATION" in resp.data

    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_saved_views_shown(
        self, mock_txns, mock_accts, mock_cats, mock_views, client
    ):
        mock_accts.return_value = []
        mock_txns.return_value = []
        mock_cats.return_value = []
        mock_views.return_value = [
            {
                "name": "Netflix",
                "filters": {"q": "netflix", "month": "", "category": "", "account": ""},
            },
        ]

        resp = client.get("/transactions")
        assert b"Netflix" in resp.data

    @patch("db.list_views")
    @patch("analytics.get_categories")
    @patch("analytics.get_accounts")
    @patch("analytics.get_transactions")
    def test_note_column_shown(
        self, mock_txns, mock_accts, mock_cats, mock_views, client
    ):
        mock_accts.return_value = []
        mock_txns.return_value = [make_txn(note="reimbursable")]
        mock_cats.return_value = []
        mock_views.return_value = []

        resp = client.get("/transactions")
        assert b"reimbursable" in resp.data


class TestSearchPage:
    def test_redirects_to_transactions(self, client):
        resp = client.get("/search")
        assert resp.status_code == 301
        assert "/transactions" in resp.headers["Location"]

    def test_preserves_query_params(self, client):
        resp = client.get("/search?q=netflix&month=2026-05")
        assert resp.status_code == 301
        location = resp.headers["Location"]
        assert "q=netflix" in location
        assert "month=2026-05" in location


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


class TestRulesPage:
    @patch("db.count_category_rules")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_returns_200(self, mock_rules, mock_cats, mock_count, client):
        mock_rules.return_value = []
        mock_cats.return_value = []
        mock_count.return_value = 0
        resp = client.get("/rules")
        assert resp.status_code == 200

    @patch("db.count_category_rules")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_shows_rules(self, mock_rules, mock_cats, mock_count, client):
        mock_rules.return_value = [
            {
                "id": 1,
                "match_field": "merchant_name",
                "match_pattern": "Netflix",
                "category": "Subscriptions",
                "priority": 10,
            },
        ]
        mock_cats.return_value = []
        mock_count.return_value = 1
        resp = client.get("/rules")
        assert b"Netflix" in resp.data
        assert b"Subscriptions" in resp.data

    @patch("db.count_category_rules")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_empty_state(self, mock_rules, mock_cats, mock_count, client):
        mock_rules.return_value = []
        mock_cats.return_value = []
        mock_count.return_value = 0
        resp = client.get("/rules")
        assert b"No saved rules" in resp.data

    @patch("db.count_category_rules")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_categories_populate_datalist(
        self, mock_rules, mock_cats, mock_count, client
    ):
        mock_rules.return_value = []
        mock_cats.return_value = ["GROCERIES", "DINING"]
        mock_count.return_value = 0
        resp = client.get("/rules")
        assert b"GROCERIES" in resp.data

    @patch("db.add_category_rule")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_add_rule_redirects(self, mock_rules, mock_cats, mock_add, client):
        mock_rules.return_value = []
        mock_cats.return_value = []
        mock_add.return_value = 5
        resp = client.post(
            "/rules",
            data={
                "match_pattern": "Netflix",
                "match_field": "merchant_name",
                "category": "Subscriptions",
                "priority": "10",
            },
        )
        assert resp.status_code == 302
        mock_add.assert_called_once()

    @patch("analytics.apply_rules")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_apply_rules_redirects(self, mock_rules, mock_cats, mock_apply, client):
        mock_rules.return_value = []
        mock_cats.return_value = []
        mock_apply.return_value = [{"transaction_id": "txn_1"}]
        resp = client.post("/rules/apply", data={"dry_run": "0"})
        assert resp.status_code == 302
        mock_apply.assert_called_once_with(dry_run=False)

    @patch("db.delete_category_rule")
    def test_delete_rule_redirects(self, mock_delete, client):
        """Plain delete (no search/page context) redirects back to the rules page."""
        resp = client.post("/rules/3/delete")
        assert resp.status_code == 302
        mock_delete.assert_called_once_with(3)
        assert resp.headers["Location"].endswith("/rules")

    @patch("db.delete_category_rule")
    def test_delete_rule_preserves_search_and_page(self, mock_delete, client):
        """Deleting from page 2 of a search returns the user to that exact view."""
        resp = client.post("/rules/3/delete", data={"q": "net", "page": "2"})
        assert resp.status_code == 302
        loc = resp.headers["Location"]
        assert "page=2" in loc and "q=net" in loc

    @patch("db.count_category_rules")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_search_passed_to_db(self, mock_rules, mock_cats, mock_count, client):
        mock_rules.return_value = []
        mock_cats.return_value = []
        mock_count.return_value = 0
        client.get("/rules?q=netflix")
        mock_rules.assert_called_once_with(search="netflix", limit=20, offset=0)
        mock_count.assert_any_call(search="netflix")
        mock_count.assert_any_call()  # unfiltered total for the "of N total" text

    @patch("db.count_category_rules")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_second_page_uses_offset(self, mock_rules, mock_cats, mock_count, client):
        mock_rules.return_value = []
        mock_cats.return_value = []
        mock_count.return_value = 45
        resp = client.get("/rules?page=3")
        assert resp.status_code == 200
        mock_rules.assert_called_once_with(search=None, limit=20, offset=40)
        assert b"Page 3 of 3" in resp.data

    @patch("db.count_category_rules")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_search_combines_with_pagination(
        self, mock_rules, mock_cats, mock_count, client
    ):
        mock_rules.return_value = []
        mock_cats.return_value = []
        mock_count.return_value = 25
        client.get("/rules?q=net&page=2")
        mock_rules.assert_called_once_with(search="net", limit=20, offset=20)

    @patch("db.count_category_rules")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_page_beyond_last_is_clamped(
        self, mock_rules, mock_cats, mock_count, client
    ):
        """?page=99 with 25 rules lands on the last page, not a 500 or empty view."""
        mock_rules.return_value = []
        mock_cats.return_value = []
        mock_count.return_value = 25
        resp = client.get("/rules?page=99")
        assert resp.status_code == 200
        mock_rules.assert_called_once_with(search=None, limit=20, offset=20)
        assert b"Page 2 of 2" in resp.data

    @patch("db.count_category_rules")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_invalid_page_defaults_to_first(
        self, mock_rules, mock_cats, mock_count, client
    ):
        mock_rules.return_value = []
        mock_cats.return_value = []
        mock_count.return_value = 45
        resp = client.get("/rules?page=abc")
        assert resp.status_code == 200
        mock_rules.assert_called_once_with(search=None, limit=20, offset=0)

    @patch("db.count_category_rules")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_search_result_count_shown(self, mock_rules, mock_cats, mock_count, client):
        """With an active search the header shows match count and total."""
        mock_rules.return_value = [
            {
                "id": 1,
                "match_field": "merchant_name",
                "match_pattern": "Netflix",
                "category": "Subscriptions",
                "priority": 10,
            },
        ]
        mock_cats.return_value = []
        mock_count.side_effect = [1, 45]  # filtered=1, total=45
        resp = client.get("/rules?q=net")
        assert b"1 match" in resp.data
        assert b"of 45 total" in resp.data

    @patch("db.count_category_rules")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_no_search_match_shows_clear_link(
        self, mock_rules, mock_cats, mock_count, client
    ):
        mock_rules.return_value = []
        mock_cats.return_value = []
        mock_count.side_effect = [0, 45]
        resp = client.get("/rules?q=zzz")
        assert b"No rules match" in resp.data
        assert b"Clear search" in resp.data

    @patch("db.add_category_rule")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_add_rule_empty_pattern_not_saved(
        self, mock_rules, mock_cats, mock_add, client
    ):
        mock_rules.return_value = []
        mock_cats.return_value = []
        resp = client.post(
            "/rules",
            data={
                "match_pattern": "",
                "match_field": "merchant_name",
                "category": "Subscriptions",
                "priority": "0",
            },
        )
        assert resp.status_code == 302
        mock_add.assert_not_called()

    @patch("db.add_category_rule")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_add_rule_empty_category_not_saved(
        self, mock_rules, mock_cats, mock_add, client
    ):
        mock_rules.return_value = []
        mock_cats.return_value = []
        resp = client.post(
            "/rules",
            data={
                "match_pattern": "Netflix",
                "match_field": "merchant_name",
                "category": "",
                "priority": "0",
            },
        )
        assert resp.status_code == 302
        mock_add.assert_not_called()

    @patch("db.count_category_rules")
    @patch("analytics.apply_rules")
    @patch("analytics.get_categories")
    @patch("db.list_category_rules")
    def test_dry_run_shows_match_count_in_flash(
        self, mock_rules, mock_cats, mock_apply, mock_count, client
    ):
        mock_rules.return_value = []
        mock_cats.return_value = []
        mock_count.return_value = 0
        mock_apply.return_value = [
            {"transaction_id": "txn_1"},
            {"transaction_id": "txn_2"},
        ]
        with client.session_transaction() as sess:
            sess["_fresh"] = True
        resp = client.post("/rules/apply", data={"dry_run": "1"}, follow_redirects=True)
        assert b"2" in resp.data


class TestReportsPage:
    @patch("analytics.income_by_category")
    @patch("analytics.budget_status")
    @patch("analytics.spend_by_category")
    @patch("analytics.monthly_summary")
    def test_returns_200(
        self, mock_summary, mock_spend, mock_budgets, mock_income, client
    ):
        mock_summary.return_value = _summary_rows()
        mock_spend.return_value = _spend_rows()
        mock_budgets.return_value = []
        mock_income.return_value = []
        resp = client.get("/reports")
        assert resp.status_code == 200

    @patch("analytics.income_by_category")
    @patch("analytics.budget_status")
    @patch("analytics.spend_by_category")
    @patch("analytics.monthly_summary")
    def test_shows_monthly_data(
        self, mock_summary, mock_spend, mock_budgets, mock_income, client
    ):
        mock_summary.return_value = _summary_rows()
        mock_spend.return_value = []
        mock_budgets.return_value = []
        mock_income.return_value = []
        resp = client.get("/reports")
        assert b"5,000.00" in resp.data
        assert b"3,000.00" in resp.data

    @patch("analytics.income_by_category")
    @patch("analytics.budget_status")
    @patch("analytics.spend_by_category")
    @patch("analytics.monthly_summary")
    def test_month_param_passed(
        self, mock_summary, mock_spend, mock_budgets, mock_income, client
    ):
        mock_summary.return_value = []
        mock_spend.return_value = []
        mock_budgets.return_value = []
        mock_income.return_value = []

        client.get("/reports?month=2026-03")

        called_month = mock_spend.call_args.args[0]
        assert called_month == "2026-03"
        assert mock_income.call_args.args[0] == "2026-03"

    @patch("analytics.income_by_category")
    @patch("analytics.budget_status")
    @patch("analytics.spend_by_category")
    @patch("analytics.monthly_summary")
    def test_categories_link_to_filtered_transactions(
        self, mock_summary, mock_spend, mock_budgets, mock_income, client
    ):
        """Spend and income categories link to transactions filtered by month + category."""
        mock_summary.return_value = []
        mock_spend.return_value = _spend_rows()
        mock_budgets.return_value = []
        mock_income.return_value = [
            {"category": "INCOME_WAGES", "total_income": 5000.0, "txn_count": 1}
        ]

        resp = client.get("/reports?month=2026-05")

        assert (
            b'href="/transactions?month=2026-05&amp;category=FOOD_AND_DRINK"'
            in resp.data
        )
        assert (
            b'href="/transactions?month=2026-05&amp;category=INCOME_WAGES"' in resp.data
        )

    @patch("analytics.income_by_category")
    @patch("analytics.budget_status")
    @patch("analytics.spend_by_category")
    @patch("analytics.monthly_summary")
    def test_shows_budget_status(
        self, mock_summary, mock_spend, mock_budgets, mock_income, client
    ):
        mock_summary.return_value = []
        mock_spend.return_value = []
        mock_income.return_value = []
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
