"""Tests for db.py — category overrides, rules, notes, tags, views."""

import db


class TestItems:
    """get_item, delete_item"""

    def test_get_item_returns_row(self, mock_db):
        mock_db.fetchone.return_value = {
            "item_id": "item_1",
            "access_token": "tok_abc",
            "institution_name": "Chase",
        }
        result = db.get_item("item_1")
        assert result["item_id"] == "item_1"
        assert result["access_token"] == "tok_abc"

    def test_get_item_returns_none_when_not_found(self, mock_db):
        mock_db.fetchone.return_value = None
        assert db.get_item("item_nope") is None

    def test_get_item_queries_by_item_id(self, mock_db):
        mock_db.fetchone.return_value = None
        db.get_item("item_xyz")
        sql = mock_db.execute.call_args[0][0]
        params = mock_db.execute.call_args[0][1]
        assert "FROM items" in sql
        assert "item_id = %s" in sql
        assert params == ("item_xyz",)

    def test_delete_item_returns_true_when_found(self, mock_db):
        mock_db.rowcount = 1
        assert db.delete_item("item_1") is True

    def test_delete_item_returns_false_when_not_found(self, mock_db):
        mock_db.rowcount = 0
        assert db.delete_item("item_nope") is False

    def test_delete_item_deletes_from_items_table(self, mock_db):
        mock_db.rowcount = 1
        db.delete_item("item_1")
        sql = mock_db.execute.call_args[0][0]
        params = mock_db.execute.call_args[0][1]
        assert "DELETE FROM items" in sql
        assert params == ("item_1",)


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


class TestTransactionNotes:
    """Phase 7: upsert/delete/get transaction notes."""

    def test_upsert_note(self, mock_db):
        db.upsert_transaction_note("txn_1", "Business expense")
        sql = mock_db.execute.call_args[0][0]
        params = mock_db.execute.call_args[0][1]
        assert "INSERT INTO transaction_notes" in sql
        assert "ON CONFLICT" in sql
        assert params == ("txn_1", "Business expense")

    def test_delete_note_returns_true(self, mock_db):
        mock_db.rowcount = 1
        assert db.delete_transaction_note("txn_1") is True

    def test_delete_note_returns_false(self, mock_db):
        mock_db.rowcount = 0
        assert db.delete_transaction_note("txn_x") is False

    def test_get_note_found(self, mock_db):
        mock_db.fetchone.return_value = ("My note",)
        assert db.get_transaction_note("txn_1") == "My note"

    def test_get_note_not_found(self, mock_db):
        mock_db.fetchone.return_value = None
        assert db.get_transaction_note("txn_1") is None


class TestTransactionTags:
    """Phase 7: add/remove/get transaction tags."""

    def test_add_tag(self, mock_db):
        db.add_transaction_tag("txn_1", "business")
        sql = mock_db.execute.call_args[0][0]
        params = mock_db.execute.call_args[0][1]
        assert "INSERT INTO transaction_tags" in sql
        assert "ON CONFLICT DO NOTHING" in sql
        assert params == ("txn_1", "business")

    def test_remove_tag_returns_true(self, mock_db):
        mock_db.rowcount = 1
        assert db.remove_transaction_tag("txn_1", "business") is True

    def test_remove_tag_returns_false(self, mock_db):
        mock_db.rowcount = 0
        assert db.remove_transaction_tag("txn_1", "missing") is False

    def test_get_tags(self, mock_db):
        mock_db.fetchall.return_value = [("business",), ("travel",)]
        tags = db.get_transaction_tags("txn_1")
        assert tags == ["business", "travel"]

    def test_get_tags_empty(self, mock_db):
        mock_db.fetchall.return_value = []
        assert db.get_transaction_tags("txn_1") == []


class TestSavedViews:
    """Phase 7: upsert/delete/list saved views."""

    def test_upsert_view(self, mock_db):
        db.upsert_view("My Search", {"q": "netflix", "month": ""})
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO saved_views" in sql
        assert "ON CONFLICT" in sql

    def test_delete_view_returns_true(self, mock_db):
        mock_db.rowcount = 1
        assert db.delete_view("My Search") is True

    def test_delete_view_returns_false(self, mock_db):
        mock_db.rowcount = 0
        assert db.delete_view("Missing") is False

    def test_list_views(self, mock_db):
        mock_db.fetchall.return_value = [
            {
                "id": 1,
                "name": "Netflix",
                "filters": {"q": "netflix"},
                "created_at": None,
            },
        ]
        views = db.list_views()
        assert len(views) == 1
        assert views[0]["name"] == "Netflix"
