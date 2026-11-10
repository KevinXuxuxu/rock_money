"""Tests for sync.py — focus on auto-rule-apply behaviour added after sync_all."""

import fcntl
import logging
from unittest.mock import MagicMock, patch

import pytest

import sync


@pytest.fixture(autouse=True)
def _private_lock_file(tmp_path, monkeypatch):
    """Point the cross-process sync lock at this test's own temp file, so runs
    never share the real /tmp lock."""
    monkeypatch.setattr(sync, "LOCK_PATH", tmp_path / "sync.lock")


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

        sync.sync_all()

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

        sync.sync_all()

        mock_apply.assert_not_called()

    @patch("analytics.apply_rules")
    @patch("sync.sync_item")
    @patch("db.list_category_rules")
    @patch("db.list_items")
    def test_skips_apply_when_no_items(
        self, mock_items, mock_rules, mock_sync_item, mock_apply, mock_db
    ):
        mock_items.return_value = []

        sync.sync_all()

        mock_sync_item.assert_not_called()
        mock_apply.assert_not_called()

    @patch("analytics.apply_rules")
    @patch("sync.sync_item")
    @patch("db.list_category_rules")
    @patch("db.list_items")
    def test_logs_categorised_count(
        self, mock_items, mock_rules, mock_sync_item, mock_apply, mock_db, caplog
    ):
        mock_items.return_value = [{"item_id": "item_1", "institution_name": "Chase"}]
        mock_rules.return_value = [{"id": 1}]
        mock_db.fetchone.return_value = ("access-token-xyz",)
        mock_apply.return_value = [{"transaction_id": "t1"}, {"transaction_id": "t2"}]

        with caplog.at_level(logging.INFO, logger="sync"):
            sync.sync_all()

        assert "1 rule" in caplog.text
        assert "Categorised 2" in caplog.text

    @patch("analytics.apply_rules")
    @patch("sync.sync_item")
    @patch("db.list_category_rules")
    @patch("db.list_items")
    def test_no_categorised_log_when_no_matches(
        self, mock_items, mock_rules, mock_sync_item, mock_apply, mock_db, caplog
    ):
        mock_items.return_value = [{"item_id": "item_1", "institution_name": "Chase"}]
        mock_rules.return_value = [{"id": 1}]
        mock_db.fetchone.return_value = ("access-token-xyz",)
        mock_apply.return_value = []

        with caplog.at_level(logging.INFO, logger="sync"):
            sync.sync_all()

        assert "Categorised" not in caplog.text

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

        sync.sync_all()

        mock_apply.assert_called_once_with(dry_run=False)

    @patch("analytics.apply_rules")
    @patch("sync.sync_item")
    @patch("db.list_category_rules")
    @patch("db.list_items")
    def test_logs_sync_complete(
        self, mock_items, mock_rules, mock_sync_item, mock_apply, mock_db, caplog
    ):
        mock_items.return_value = [{"item_id": "item_1", "institution_name": "Chase"}]
        mock_rules.return_value = []
        mock_db.fetchone.return_value = ("access-token-xyz",)

        with caplog.at_level(logging.INFO, logger="sync"):
            sync.sync_all()

        assert "Sync complete" in caplog.text
        assert "Chase" in caplog.text


class TestSyncLock:
    """sync_all() runs under 2 gunicorn workers and can overlap with
    `main.py sync`, so it must refuse to run twice at the same time."""

    def test_runs_and_returns_true_when_the_lock_is_free(self):
        with patch("db.list_items", return_value=[]) as mock_items:
            assert sync.sync_all() is True

        mock_items.assert_called_once_with()

    def test_skips_and_returns_false_while_another_sync_holds_the_lock(self):
        held = open(sync.LOCK_PATH, "a")
        fcntl.flock(held, fcntl.LOCK_EX)

        with patch("db.list_items") as mock_items, patch("sync.sync_item") as item:
            assert sync.sync_all() is False

        item.assert_not_called()
        mock_items.assert_not_called()
        held.close()

    def test_lock_is_released_after_a_run(self):
        """A finished sync must not block the next one."""
        with patch("db.list_items", return_value=[]) as mock_items:
            assert sync.sync_all() is True
            assert sync.sync_all() is True

        assert mock_items.call_count == 2

    def test_lock_is_released_after_a_crash(self):
        """Same shape as a worker killed mid-sync: whatever is raised, the lock
        comes back, so syncing is not wedged for good."""
        with patch("db.list_items", side_effect=[RuntimeError("db gone"), []]):
            with pytest.raises(RuntimeError):
                sync.sync_all()
            assert sync.sync_all() is True

    def test_error_inside_an_item_does_not_stop_the_run(self, mock_db):
        """Per-item failures are caught inside the sync, which still counts as
        having run (and still gives the lock back)."""
        mock_db.fetchone.return_value = ("access-token-xyz",)
        with (
            patch("db.list_items", return_value=[{"item_id": "i1"}]),
            patch("sync.sync_item", side_effect=Exception("Plaid error")),
            patch("db.list_category_rules", return_value=[]),
            patch("analytics.detect_internal_transfers", return_value=[]),
        ):
            assert sync.sync_all() is True
