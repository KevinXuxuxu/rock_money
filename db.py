import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from dotenv import load_dotenv

load_dotenv()

_pool: ThreadedConnectionPool | None = None


def get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(1, 10, dsn=os.environ["DATABASE_URL"])
    return _pool


@contextmanager
def get_conn():
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def init_schema(schema_path: str = "schema.sql") -> None:
    with open(schema_path) as f:
        sql = f.read()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)


# ── Items ──────────────────────────────────────────────────────────────────────


def upsert_item(
    item_id: str,
    access_token: str,
    institution_id: str | None,
    institution_name: str | None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO items (item_id, access_token, institution_id, institution_name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (item_id) DO UPDATE SET
                    access_token     = EXCLUDED.access_token,
                    institution_id   = EXCLUDED.institution_id,
                    institution_name = EXCLUDED.institution_name
                """,
                (item_id, access_token, institution_id, institution_name),
            )
            cur.execute(
                "INSERT INTO sync_cursors (item_id, cursor) VALUES (%s, NULL) ON CONFLICT DO NOTHING",
                (item_id,),
            )


def list_items() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT i.item_id, i.institution_name, i.created_at,
                       sc.cursor IS NOT NULL AS has_cursor, sc.last_synced_at
                FROM items i
                LEFT JOIN sync_cursors sc ON sc.item_id = i.item_id
                ORDER BY i.created_at
                """
            )
            return [dict(row) for row in cur.fetchall()]


# ── Cursors ────────────────────────────────────────────────────────────────────


def get_cursor(item_id: str) -> str | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT cursor FROM sync_cursors WHERE item_id = %s", (item_id,)
            )
            row = cur.fetchone()
            return row[0] if row else None


def set_cursor(item_id: str, cursor: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sync_cursors (item_id, cursor, last_synced_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (item_id) DO UPDATE SET
                    cursor = EXCLUDED.cursor,
                    last_synced_at = EXCLUDED.last_synced_at
                """,
                (item_id, cursor),
            )


# ── Accounts ───────────────────────────────────────────────────────────────────


def upsert_accounts(accounts: list[dict]) -> None:
    if not accounts:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO accounts (account_id, item_id, name, official_name, type, subtype, mask, updated_at)
                VALUES %s
                ON CONFLICT (account_id) DO UPDATE SET
                    name          = EXCLUDED.name,
                    official_name = EXCLUDED.official_name,
                    type          = EXCLUDED.type,
                    subtype       = EXCLUDED.subtype,
                    mask          = EXCLUDED.mask,
                    updated_at    = EXCLUDED.updated_at
                """,
                [
                    (
                        a["account_id"],
                        a["item_id"],
                        a["name"],
                        a.get("official_name"),
                        a["type"],
                        a.get("subtype"),
                        a.get("mask"),
                    )
                    for a in accounts
                ],
                template="(%s, %s, %s, %s, %s, %s, %s, NOW())",
            )


# ── Transactions ───────────────────────────────────────────────────────────────


def upsert_transactions(txns: list[dict]) -> int:
    if not txns:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO transactions (
                    transaction_id, account_id, amount, iso_currency_code,
                    date, authorized_date, datetime, authorized_datetime,
                    name, merchant_name, payment_channel,
                    pending, pending_transaction_id,
                    category, personal_finance_category, personal_finance_category_confidence,
                    location, counterparties, updated_at
                ) VALUES %s
                ON CONFLICT (transaction_id) DO UPDATE SET
                    amount                               = EXCLUDED.amount,
                    date                                 = EXCLUDED.date,
                    authorized_date                      = EXCLUDED.authorized_date,
                    datetime                             = EXCLUDED.datetime,
                    authorized_datetime                  = EXCLUDED.authorized_datetime,
                    name                                 = EXCLUDED.name,
                    merchant_name                        = EXCLUDED.merchant_name,
                    payment_channel                      = EXCLUDED.payment_channel,
                    pending                              = EXCLUDED.pending,
                    pending_transaction_id               = EXCLUDED.pending_transaction_id,
                    category                             = EXCLUDED.category,
                    personal_finance_category            = EXCLUDED.personal_finance_category,
                    personal_finance_category_confidence = EXCLUDED.personal_finance_category_confidence,
                    location                             = EXCLUDED.location,
                    counterparties                       = EXCLUDED.counterparties,
                    updated_at                           = EXCLUDED.updated_at
                """,
                [
                    (
                        t["transaction_id"],
                        t["account_id"],
                        t["amount"],
                        t.get("iso_currency_code"),
                        t["date"],
                        t.get("authorized_date"),
                        t.get("datetime"),
                        t.get("authorized_datetime"),
                        t["name"],
                        t.get("merchant_name"),
                        t.get("payment_channel"),
                        t.get("pending", False),
                        t.get("pending_transaction_id"),
                        t.get("category"),
                        t.get("personal_finance_category"),
                        t.get("personal_finance_category_confidence"),
                        psycopg2.extras.Json(t["location"])
                        if t.get("location")
                        else None,
                        psycopg2.extras.Json(t["counterparties"])
                        if t.get("counterparties")
                        else None,
                    )
                    for t in txns
                ],
                template=(
                    "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())"
                ),
            )
            return cur.rowcount


# ── Category overrides ──────────────────────────────────────────────────────────


def upsert_category_override(transaction_id: str, category: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO category_overrides (transaction_id, category)
                VALUES (%s, %s)
                ON CONFLICT (transaction_id) DO UPDATE SET
                    category = EXCLUDED.category
                """,
                (transaction_id, category),
            )


def delete_category_override(transaction_id: str) -> bool:
    """Return True if a row was deleted."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM category_overrides WHERE transaction_id = %s",
                (transaction_id,),
            )
            return cur.rowcount > 0


def get_category_override(transaction_id: str) -> str | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT category FROM category_overrides WHERE transaction_id = %s",
                (transaction_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None


# ── Category rules ──────────────────────────────────────────────────────────────


def add_category_rule(
    match_pattern: str,
    match_field: str,
    category: str,
    priority: int = 0,
) -> int:
    """Insert a rule and return its id."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO category_rules (match_pattern, match_field, category, priority)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (match_pattern, match_field, category, priority),
            )
            return cur.fetchone()[0]


def delete_category_rule(rule_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM category_rules WHERE id = %s",
                (rule_id,),
            )
            return cur.rowcount > 0


def list_category_rules(
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict]:
    """
    Return category rules ordered by priority DESC, id ASC.

    Args:
        search: optional case-insensitive substring filter on match_pattern OR category
        limit: max rows to return (None = all)
        offset: rows to skip, for pagination (applied after ordering)
    """
    where, params = _rule_search_filter(search)
    query = f"""
        SELECT * FROM category_rules
        {where}
        ORDER BY priority DESC, id
    """
    if limit is not None:
        query += " LIMIT %s OFFSET %s"
        params += [limit, offset or 0]
    with get_conn() as conn:
        import psycopg2.extras

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]


def count_category_rules(search: str | None = None) -> int:
    """Count rules, optionally filtered by the same search as list_category_rules."""
    where, params = _rule_search_filter(search)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM category_rules {where}", params)
            return cur.fetchone()[0]


def _rule_search_filter(search: str | None) -> tuple[str, list]:
    """Build the shared WHERE clause for rule search (pattern OR category)."""
    if not search:
        return "", []
    like = f"%{search}%"
    return "WHERE match_pattern ILIKE %s OR category ILIKE %s", [like, like]


# ── Budgets ────────────────────────────────────────────────────────────────────


def upsert_budget(category: str, monthly_limit: float) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO budgets (category, monthly_limit)
                VALUES (%s, %s)
                ON CONFLICT (category) DO UPDATE SET
                    monthly_limit = EXCLUDED.monthly_limit,
                    updated_at    = NOW()
                """,
                (category, monthly_limit),
            )


def list_budgets() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM budgets ORDER BY category")
            return [dict(row) for row in cur.fetchall()]


def delete_budget(category: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM budgets WHERE category = %s", (category,))
            return cur.rowcount > 0


# ── Transaction notes ──────────────────────────────────────────────────────────


def upsert_transaction_note(transaction_id: str, note: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO transaction_notes (transaction_id, note)
                VALUES (%s, %s)
                ON CONFLICT (transaction_id) DO UPDATE SET
                    note = EXCLUDED.note, updated_at = NOW()
                """,
                (transaction_id, note),
            )


def delete_transaction_note(transaction_id: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM transaction_notes WHERE transaction_id = %s",
                (transaction_id,),
            )
            return cur.rowcount > 0


def get_transaction_note(transaction_id: str) -> str | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT note FROM transaction_notes WHERE transaction_id = %s",
                (transaction_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None


# ── Transaction tags ───────────────────────────────────────────────────────────


def add_transaction_tag(transaction_id: str, tag: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO transaction_tags (transaction_id, tag)
                VALUES (%s, %s) ON CONFLICT DO NOTHING
                """,
                (transaction_id, tag),
            )


def remove_transaction_tag(transaction_id: str, tag: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM transaction_tags WHERE transaction_id = %s AND tag = %s",
                (transaction_id, tag),
            )
            return cur.rowcount > 0


def get_transaction_tags(transaction_id: str) -> list[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tag FROM transaction_tags WHERE transaction_id = %s ORDER BY tag",
                (transaction_id,),
            )
            return [row[0] for row in cur.fetchall()]


# ── Saved views ────────────────────────────────────────────────────────────────


def upsert_view(name: str, filters: dict) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO saved_views (name, filters)
                VALUES (%s, %s)
                ON CONFLICT (name) DO UPDATE SET filters = EXCLUDED.filters
                """,
                (name, psycopg2.extras.Json(filters)),
            )


def delete_view(name: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM saved_views WHERE name = %s", (name,))
            return cur.rowcount > 0


def list_views() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM saved_views ORDER BY name")
            return [dict(row) for row in cur.fetchall()]


def get_item(item_id: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT item_id, access_token, institution_name FROM items WHERE item_id = %s",
                (item_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def delete_item(item_id: str) -> bool:
    """Delete an item and all cascade data (accounts, transactions, overrides, etc.)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM items WHERE item_id = %s", (item_id,))
            return cur.rowcount > 0


def delete_transactions(transaction_ids: list[str]) -> int:
    if not transaction_ids:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM transactions WHERE transaction_id = ANY(%s)",
                (transaction_ids,),
            )
            return cur.rowcount
