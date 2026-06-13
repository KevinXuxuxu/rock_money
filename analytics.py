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
    q: str | None = None,
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
        conditions.append("COALESCE(co.category, t.personal_finance_category) = %s")
        params.append(category)
    if month:
        conditions.append("date_trunc('month', t.date) = %s::date")
        params.append(f"{month}-01")
    if q:
        conditions.append(
            "(t.name ILIKE %s OR t.merchant_name ILIKE %s OR tn.note ILIKE %s)"
        )
        like = f"%{q}%"
        params.extend([like, like, like])

    where = " AND ".join(conditions)

    query = f"""
        SELECT t.transaction_id, t.account_id, t.amount, t.iso_currency_code,
               t.date, t.authorized_date, t.name, t.merchant_name,
               t.payment_channel, t.pending, t.personal_finance_category,
               t.personal_finance_category_confidence, t.category,
               a.name AS account_name, a.mask AS account_mask,
               a.type AS account_type, a.subtype AS account_subtype,
               COALESCE(co.category, t.personal_finance_category) AS effective_category,
               tn.note
        FROM transactions t
        JOIN accounts a ON a.account_id = t.account_id
        LEFT JOIN category_overrides co ON co.transaction_id = t.transaction_id
        LEFT JOIN transaction_notes tn ON tn.transaction_id = t.transaction_id
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


def get_categories() -> list[str]:
    """Return all distinct effective categories (override > Plaid), sorted."""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT COALESCE(co.category, t.personal_finance_category) AS cat
                FROM transactions t
                LEFT JOIN category_overrides co ON co.transaction_id = t.transaction_id
                WHERE COALESCE(co.category, t.personal_finance_category) IS NOT NULL
                  AND t.pending = FALSE
                ORDER BY cat
            """)
            return [row[0] for row in cur.fetchall()]


def get_transaction_detail(transaction_id: str) -> dict | None:
    """Return a single transaction with note and tags, or None if not found."""
    with db.get_conn() as conn:
        import psycopg2.extras

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT t.*,
                       a.name AS account_name, a.mask AS account_mask,
                       a.type AS account_type, a.subtype AS account_subtype,
                       i.institution_name,
                       COALESCE(co.category, t.personal_finance_category) AS effective_category,
                       co.category AS override_category,
                       tn.note
                FROM transactions t
                JOIN accounts a ON a.account_id = t.account_id
                JOIN items i ON i.item_id = a.item_id
                LEFT JOIN category_overrides co ON co.transaction_id = t.transaction_id
                LEFT JOIN transaction_notes tn ON tn.transaction_id = t.transaction_id
                WHERE t.transaction_id = %s
                """,
                (transaction_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            result = dict(row)
    result["tags"] = db.get_transaction_tags(transaction_id)
    return result


def budget_status(month: str) -> list[dict]:
    """
    Return budget vs actual spend per category for a given month.

    Each row: {category, monthly_limit, actual_spend, remaining, pct_used}
    Categories with a budget but no spending are included (actual=0).
    """
    budgets = db.list_budgets()
    if not budgets:
        return []

    spend_rows = spend_by_category(month)
    spend_map = {r["category"]: float(r["total_spend"]) for r in spend_rows}

    results = []
    for b in budgets:
        cat = b["category"]
        limit = float(b["monthly_limit"])
        actual = spend_map.get(cat, 0.0)
        remaining = limit - actual
        pct_used = (actual / limit * 100) if limit > 0 else 0.0
        results.append(
            {
                "category": cat,
                "monthly_limit": limit,
                "actual_spend": actual,
                "remaining": remaining,
                "pct_used": pct_used,
            }
        )
    results.sort(key=lambda r: r["pct_used"], reverse=True)
    return results


def budget_alert(month: str, threshold: float = 80.0) -> list[dict]:
    """
    Return budget rows where pct_used >= threshold (default 80%).
    Rows are sorted by pct_used descending.
    """
    return [r for r in budget_status(month) if r["pct_used"] >= threshold]


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


# ── Category resolution ──────────────────────────────────────────────────────


def effective_category(transaction_id: str) -> str | None:
    """Return the user's override category, or None if not set.
    Caller should fall back to Plaid's personal_finance_category, then 'Uncategorized'.
    """
    return db.get_category_override(transaction_id)


def resolve_category(transaction: dict) -> str:
    """
    Resolve the best category for a transaction dict.
    Priority: user override > rule match > Plaid category > 'Uncategorized'.
    """
    txn_id = transaction["transaction_id"]
    override = effective_category(txn_id)
    if override:
        return override
    return transaction.get("personal_finance_category") or "Uncategorized"


def apply_rules(dry_run: bool = False) -> list[dict]:
    """
    Apply all category rules to transactions that don't already have an override.
    Returns a list of {transaction_id, old_category, new_category} for matches.

    When dry_run=True, report matches but don't persist them.
    """
    rules = db.list_category_rules()
    if not rules:
        return []

    # Get all non-overridden transactions
    with db.get_conn() as conn:
        import psycopg2.extras

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT t.transaction_id, t.name, t.merchant_name,
                       t.personal_finance_category
                FROM transactions t
                WHERE NOT EXISTS (
                    SELECT 1 FROM category_overrides co
                    WHERE co.transaction_id = t.transaction_id
                )
            """)
            transactions = [dict(row) for row in cur.fetchall()]

    results = []
    for txn in transactions:
        for rule in rules:
            field_value = txn.get(rule["match_field"]) or ""
            if _rule_matches(field_value, rule["match_pattern"]):
                results.append(
                    {
                        "transaction_id": txn["transaction_id"],
                        "old_category": txn.get("personal_finance_category"),
                        "new_category": rule["category"],
                        "rule_id": rule["id"],
                        "matched_on": field_value,
                    }
                )
                if not dry_run:
                    db.upsert_category_override(txn["transaction_id"], rule["category"])
                break  # first matching rule wins (sorted by priority desc)

    return results


def _rule_matches(field_value: str, pattern: str) -> bool:
    """Case-insensitive substring match."""
    return pattern.lower() in field_value.lower()
