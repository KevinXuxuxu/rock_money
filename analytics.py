"""
Query functions for analytics, reports, and dashboards.
All functions use the existing db.get_conn() pool and return lists of dicts.
"""

import db


def get_transactions(
    *,
    limit: int = 50,
    account_id: str | None = None,
    category: str | None = None,
    month: str | None = None,
    pending: bool = False,
) -> list[dict]:
    """
    Return recent transactions with account info, newest first.

    Args:
        limit: max rows to return
        account_id: filter to a single account
        category: filter by Plaid personal_finance_category
        month: YYYY-MM — filter to a specific month
        pending: include pending transactions (excluded by default)
    """
    conditions = ["1=1"]
    params: list = []

    if not pending:
        conditions.append("t.pending = FALSE")
    if account_id:
        conditions.append("t.account_id = %s")
        params.append(account_id)
    if category:
        conditions.append("t.personal_finance_category = %s")
        params.append(category)
    if month:
        conditions.append("date_trunc('month', t.date) = %s::date")
        params.append(f"{month}-01")

    where = " AND ".join(conditions)

    query = f"""
        SELECT t.transaction_id, t.account_id, t.amount, t.iso_currency_code,
               t.date, t.authorized_date, t.name, t.merchant_name,
               t.payment_channel, t.pending, t.personal_finance_category,
               t.personal_finance_category_confidence, t.category,
               a.name AS account_name, a.mask AS account_mask,
               a.type AS account_type, a.subtype AS account_subtype
        FROM transactions t
        JOIN accounts a ON a.account_id = t.account_id
        WHERE {where}
        ORDER BY t.date DESC, t.name
        LIMIT %s
    """
    params.append(limit)

    with db.get_conn() as conn:
        import psycopg2.extras

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]


def spend_by_category(month: str) -> list[dict]:
    """
    Return spending summed by Plaid personal_finance_category for a given month.

    Args:
        month: YYYY-MM — e.g. '2026-06'
    """
    with db.get_conn() as conn:
        import psycopg2.extras

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT personal_finance_category AS category,
                       SUM(amount) AS total_spend,
                       COUNT(*)   AS txn_count
                FROM transactions
                WHERE pending = FALSE
                  AND amount > 0
                  AND date_trunc('month', date) = %s::date
                GROUP BY personal_finance_category
                ORDER BY total_spend DESC
            """,
                (f"{month}-01",),
            )
            return [dict(row) for row in cur.fetchall()]


def monthly_summary(months: int = 12) -> list[dict]:
    """
    Return month-over-month income, spend, and net summary.

    Args:
        months: number of calendar months to look back (default 12)
    """
    with db.get_conn() as conn:
        import psycopg2.extras

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT month,
                       income,
                       spend,
                       (income - spend) AS net
                FROM (
                    SELECT date_trunc('month', date)::date AS month,
                           COALESCE(SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END), 0) AS income,
                           COALESCE(SUM(CASE WHEN amount > 0 THEN  amount ELSE 0 END), 0) AS spend
                    FROM transactions
                    WHERE pending = FALSE
                    GROUP BY date_trunc('month', date)
                    ORDER BY month DESC
                    LIMIT %s
                ) sub
                ORDER BY month
            """,
                (months,),
            )
            return [dict(row) for row in cur.fetchall()]


def get_accounts() -> list[dict]:
    """Return all accounts with transaction counts."""
    with db.get_conn() as conn:
        import psycopg2.extras

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT a.account_id, a.name, a.official_name, a.type, a.subtype,
                       a.mask, a.item_id, i.institution_name,
                       COUNT(t.transaction_id) FILTER (WHERE NOT t.pending) AS txn_count,
                       COALESCE(SUM(t.amount) FILTER (WHERE NOT t.pending), 0) AS total_debits,
                       COALESCE(SUM(-t.amount) FILTER (WHERE t.amount < 0 AND NOT t.pending), 0) AS total_credits
                FROM accounts a
                JOIN items i ON i.item_id = a.item_id
                LEFT JOIN transactions t ON t.account_id = a.account_id
                GROUP BY a.account_id, a.name, a.official_name, a.type, a.subtype,
                         a.mask, a.item_id, i.institution_name
                ORDER BY i.institution_name, a.name
            """)
            return [dict(row) for row in cur.fetchall()]
