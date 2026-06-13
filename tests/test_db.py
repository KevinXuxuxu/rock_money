"""Tests for db.py Phase 3 additions — category overrides and rules."""

import db


class TestCategoryOverrides:
    """upsert_category_override, delete_category_override, get_category_override"""

    def test_upsert_inserts(self, mock_db):
        mock_db.rowcount = 1
        db.upsert_category_override("txn_1", "Shopping")
        sql = mock_db.execute.call_args[0][0]
        params = mock_db.execute.call_args[0][1]
        assert "INSERT INTO category_overrides" in sql
        assert "ON CONFLICT" in sql
        assert params == ("txn_1", "Shopping")

    def test_delete_returns_true_when_row_deleted(self, mock_db):
        mock_db.rowcount = 1
        result = db.delete_category_override("txn_1")
        assert result is True

    def test_delete_returns_false_when_not_found(self, mock_db):
        mock_db.rowcount = 0
        result = db.delete_category_override("txn_nonexistent")
        assert result is False

    def test_get_returns_category(self, mock_db):
        mock_db.fetchone.return_value = ("Groceries",)
        result = db.get_category_override("txn_1")
        assert result == "Groceries"

    def test_get_returns_none_when_not_found(self, mock_db):
        mock_db.fetchone.return_value = None
        result = db.get_category_override("txn_1")
        assert result is None


class TestCategoryRules:
    """add_category_rule, delete_category_rule, list_category_rules"""

    def test_add_rule_returns_id(self, mock_db):
        mock_db.fetchone.return_value = (42,)
        rule_id = db.add_category_rule("Netflix", "merchant_name", "Subscriptions")
        params = mock_db.execute.call_args[0][1]
        assert rule_id == 42
        assert params == ("Netflix", "merchant_name", "Subscriptions", 0)

    def test_add_rule_with_priority(self, mock_db):
        mock_db.fetchone.return_value = (7,)
        rule_id = db.add_category_rule("Rent", "name", "Housing", priority=10)
        params = mock_db.execute.call_args[0][1]
        assert rule_id == 7
        assert params[3] == 10

    def test_delete_rule_returns_true(self, mock_db):
        mock_db.rowcount = 1
        assert db.delete_category_rule(5) is True

    def test_delete_rule_returns_false(self, mock_db):
        mock_db.rowcount = 0
        assert db.delete_category_rule(999) is False

    def test_list_rules_returns_sorted(self, mock_db):
        mock_db.fetchall.return_value = [
            {
                "id": 2,
                "match_pattern": "Spotify",
                "match_field": "merchant_name",
                "category": "Entertainment",
                "priority": 0,
                "created_at": None,
            },
            {
                "id": 1,
                "match_pattern": "Netflix",
                "match_field": "merchant_name",
                "category": "Subscriptions",
                "priority": 10,
                "created_at": None,
            },
        ]
        rules = db.list_category_rules()
        assert len(rules) == 2
        # Verify SQL orders by priority desc
        sql = mock_db.execute.call_args[0][0]
        assert "ORDER BY priority DESC" in sql
