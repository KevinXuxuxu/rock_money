"""
Query functions for analytics, reports, and dashboards.
All functions use the existing db.get_conn() pool and return lists of dicts.
"""

import logging

import db

_log = logging.getLogger(__name__)

# Categories treated as internal noise — excluded from spend/income aggregations.
# CREDIT PAYMENT: credit card payments (covered by user rules).
# INTERNAL TRANSFER: detected TRANSFER_IN/OUT pairs between linked accounts.
INTERNAL_CATEGORIES: frozenset[str] = frozenset({"INTERNAL TRANSFER", "CREDIT PAYMENT"})


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
    Return spending summed by effective category for a given month.

    Args:
        month: YYYY-MM — e.g. '2026-06'
    """
    with db.get_conn() as conn:
        import psycopg2.extras

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT COALESCE(co.category, t.personal_finance_category) AS category,
                       SUM(t.amount) AS total_spend,
                       COUNT(*)      AS txn_count
                FROM transactions t
                LEFT JOIN category_overrides co ON co.transaction_id = t.transaction_id
                WHERE t.pending = FALSE
                  AND t.amount > 0
                  AND date_trunc('month', t.date) = %s::date
                  AND COALESCE(co.category, t.personal_finance_category)
                      NOT IN ('INTERNAL TRANSFER', 'CREDIT PAYMENT')
                GROUP BY COALESCE(co.category, t.personal_finance_category)
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
                    SELECT date_trunc('month', t.date)::date AS month,
                           COALESCE(SUM(CASE WHEN t.amount < 0 THEN -t.amount ELSE 0 END), 0) AS income,
                           COALESCE(SUM(CASE WHEN t.amount > 0 THEN  t.amount ELSE 0 END), 0) AS spend
                    FROM transactions t
                    LEFT JOIN category_overrides co ON co.transaction_id = t.transaction_id
                    WHERE t.pending = FALSE
                      AND COALESCE(co.category, t.personal_finance_category)
                          NOT IN ('INTERNAL TRANSFER', 'CREDIT PAYMENT')
                    GROUP BY date_trunc('month', t.date)
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


# ── Internal transfer detection ──────────────────────────────────────────────

_TRANSFER_PLAID_CATEGORIES = frozenset({"TRANSFER_IN", "TRANSFER_OUT"})


def detect_internal_transfers(dry_run: bool = False) -> list[dict]:
    """
    Find TRANSFER_IN / TRANSFER_OUT pairs across different accounts whose amounts
    cancel out (within $0.01) and that settled within 5 days of each other.
    Writes 'INTERNAL TRANSFER' overrides for both legs unless either already has
    a manual override.

    Returns a list of matched pairs:
        {txn_id_a, txn_id_b, amount, date_a, date_b, account_a, account_b}
    """
    with db.get_conn() as conn:
        import psycopg2.extras

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT t1.transaction_id AS txn_id_a,
                       t2.transaction_id AS txn_id_b,
                       t1.amount         AS amount,
                       t1.date           AS date_a,
                       t2.date           AS date_b,
                       a1.name           AS account_a,
                       a2.name           AS account_b
                FROM transactions t1
                JOIN transactions t2 ON (
                    t1.account_id != t2.account_id
                    AND ABS(t1.amount + t2.amount) < 0.01
                    AND ABS(t1.date - t2.date) <= 5
                    AND t2.personal_finance_category IN ('TRANSFER_IN', 'TRANSFER_OUT')
                )
                JOIN accounts a1 ON a1.account_id = t1.account_id
                JOIN accounts a2 ON a2.account_id = t2.account_id
                WHERE t1.transaction_id < t2.transaction_id
                  AND t1.personal_finance_category IN ('TRANSFER_IN', 'TRANSFER_OUT')
                  AND NOT EXISTS (
                      SELECT 1 FROM category_overrides
                      WHERE transaction_id = t1.transaction_id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM category_overrides
                      WHERE transaction_id = t2.transaction_id
                  )
                ORDER BY t1.date DESC
            """)
            pairs = [dict(row) for row in cur.fetchall()]

    _log.info(
        "detect_internal_transfers: %d pair(s) found, dry_run=%s", len(pairs), dry_run
    )

    if not dry_run:
        for pair in pairs:
            db.upsert_category_override(pair["txn_id_a"], "INTERNAL TRANSFER")
            db.upsert_category_override(pair["txn_id_b"], "INTERNAL TRANSFER")

    return pairs


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
    Apply all category rules to transactions.
    Dry-run matches ALL transactions (including already-categorised ones) so the
    user can verify a rule works before committing. Actual apply skips transactions
    that already have a manual override.
    Returns a list of {transaction_id, old_category, new_category} for matches.
    """
    rules = db.list_category_rules()
    _log.info("apply_rules: %d rule(s), dry_run=%s", len(rules), dry_run)
    if not rules:
        return []

    with db.get_conn() as conn:
        import psycopg2.extras

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if dry_run:
                # Match against all transactions so the user can test the rule.
                cur.execute("""
                    SELECT t.transaction_id, t.name, t.merchant_name,
                           t.personal_finance_category
                    FROM transactions t
                """)
            else:
                # Only categorise transactions without an existing manual override.
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

    _log.info("apply_rules: %d transaction(s) to check", len(transactions))

    results = []
    for txn in transactions:
        for rule in rules:
            field_value = _field_value(txn, rule["match_field"])
            matched = _rule_matches(field_value, rule["match_pattern"])
            _log.debug(
                "txn %s | %s=%r | pattern=%r | match=%s",
                txn["transaction_id"][:16],
                rule["match_field"],
                field_value[:60],
                rule["match_pattern"],
                matched,
            )
            if matched:
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

    _log.info("apply_rules: %d match(es)", len(results))
    return results


def _field_value(txn: dict, match_field: str) -> str:
    """
    Return the value to match against for a given field name.
    For merchant_name, fall back to name when NULL — matching what the UI displays.
    """
    if match_field == "merchant_name":
        return txn.get("merchant_name") or txn.get("name") or ""
    return txn.get(match_field) or ""


def _rule_matches(field_value: str, pattern: str) -> bool:
    """Case-insensitive substring match."""
    return pattern.lower() in field_value.lower()
