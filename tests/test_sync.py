"""Tests for sync.py — focus on auto-rule-apply behaviour added after sync_all."""

from unittest.mock import MagicMock, patch

import pytest

import sync


@pytest.fixture
def mock_db():
    """Patch db.get_conn for the access_token SELECT inside sync_all."""
    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.__exit__.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.cursor.return_value.__exit__.return_value = None
    with patch("db.get_conn", return_value=mock_conn):
        yield mock_cur


class TestSyncAllRuleApplication:
    """sync_all() should auto-apply saved rules to newly synced transactions."""

    @patch("analytics.apply_rules")
    @patch("sync.sync_item")
    @patch("db.list_category_rules")
    @patch("db.list_items")
    def test_applies_rules_when_rules_exist(
        self, mock_items, mock_rules, mock_sync_item, mock_apply, mock_db
    ):
        mock_items.return_value = [{"item_id": "item_1", "institution_name": "Chase"}]
        mock_rules.return_value = [{"id": 1, "match_pattern": "Netflix"}]
        mock_db.fetchone.return_value = ("access-token-xyz",)

        sync.sync_all(verbose=False)

        mock_apply.assert_called_once_with(dry_run=False)

    @patch("analytics.apply_rules")
    @patch("sync.sync_item")
    @patch("db.list_category_rules")
    @patch("db.list_items")
    def test_skips_apply_when_no_rules(
        self, mock_items, mock_rules, mock_sync_item, mock_apply, mock_db
    ):
        mock_items.return_value = [{"item_id": "item_1", "institution_name": "Chase"}]
        mock_rules.return_value = []
        mock_db.fetchone.return_value = ("access-token-xyz",)

        sync.sync_all(verbose=False)

        mock_apply.assert_not_called()

    @patch("analytics.apply_rules")
    @patch("sync.sync_item")
    @patch("db.list_category_rules")
    @patch("db.list_items")
    def test_skips_apply_when_no_items(
        self, mock_items, mock_rules, mock_sync_item, mock_apply, mock_db
    ):
        mock_items.return_value = []

        sync.sync_all(verbose=False)

        mock_sync_item.assert_not_called()
        mock_apply.assert_not_called()

    @patch("analytics.apply_rules")
    @patch("sync.sync_item")
    @patch("db.list_category_rules")
    @patch("db.list_items")
    def test_verbose_prints_categorised_count(
        self, mock_items, mock_rules, mock_sync_item, mock_apply, mock_db, capsys
    ):
        mock_items.return_value = [{"item_id": "item_1", "institution_name": "Chase"}]
        mock_rules.return_value = [{"id": 1}]
        mock_db.fetchone.return_value = ("access-token-xyz",)
        mock_apply.return_value = [{"transaction_id": "t1"}, {"transaction_id": "t2"}]

        sync.sync_all(verbose=True)

        out = capsys.readouterr().out
        assert "1 rule" in out
        assert "Categorised 2" in out

    @patch("analytics.apply_rules")
    @patch("sync.sync_item")
    @patch("db.list_category_rules")
    @patch("db.list_items")
    def test_verbose_silent_when_no_matches(
        self, mock_items, mock_rules, mock_sync_item, mock_apply, mock_db, capsys
    ):
        mock_items.return_value = [{"item_id": "item_1", "institution_name": "Chase"}]
        mock_rules.return_value = [{"id": 1}]
        mock_db.fetchone.return_value = ("access-token-xyz",)
        mock_apply.return_value = []

        sync.sync_all(verbose=True)

        out = capsys.readouterr().out
        assert "Categorised" not in out

    @patch("analytics.apply_rules")
    @patch("sync.sync_item")
    @patch("db.list_category_rules")
    @patch("db.list_items")
    def test_rules_applied_even_if_one_item_errors(
        self, mock_items, mock_rules, mock_sync_item, mock_apply, mock_db
    ):
        """Rule application runs after all items regardless of per-item errors."""
        mock_items.return_value = [
            {"item_id": "item_1", "institution_name": "Chase"},
            {"item_id": "item_2", "institution_name": "BoA"},
        ]
        mock_rules.return_value = [{"id": 1}]
        mock_db.fetchone.return_value = ("access-token-xyz",)
        mock_sync_item.side_effect = [Exception("Plaid error"), None]

        sync.sync_all(verbose=False)

        mock_apply.assert_called_once_with(dry_run=False)
