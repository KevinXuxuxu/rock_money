#!/usr/bin/env python3
import argparse
import sys
from datetime import timezone


def cmd_init(args):
    """Initialize the database schema."""
    import db

    print("Initializing database schema...")
    db.init_schema()
    print("Done.")


def cmd_link(args):
    """Start Plaid Link flow to connect a bank account."""
    import db

    db.init_schema()
    import link_server

    link_server.run(port=args.port)


def cmd_sync(args):
    """Sync transactions for all linked accounts."""
    import logging
    import sync

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        level=logging.WARNING if args.quiet else logging.INFO,
    )
    sync.sync_all()


def cmd_list_items(args):
    """List all linked institutions."""
    import db

    items = db.list_items()
    if not items:
        print("No linked items. Run `python main.py link` to connect an account.")
        return

    print(f"{'Institution':<30} {'Item ID':<32} {'Last Synced'}")
    print("-" * 80)
    for item in items:
        name = (item.get("institution_name") or "—")[:29]
        item_id = item["item_id"][:31]
        synced_at = item.get("last_synced_at")
        synced_str = (
            synced_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if synced_at
            else "never"
        )
        print(f"{name:<30} {item_id:<32} {synced_str}")


def cmd_accounts(args):
    """List all accounts with transaction counts."""
    import analytics

    accounts = analytics.get_accounts()
    if not accounts:
        print("No accounts found. Link a bank account first.")
        return

    print(f"{'Account':<30} {'Type':<20} {'Institution':<22} {'Txns':>6}")
    print("-" * 82)
    for a in accounts:
        name = (a["name"] or "—")[:29]
        atype = f"{a.get('subtype') or a['type']}"[:19]
        inst = (a.get("institution_name") or "—")[:21]
        count = a["txn_count"]
        print(f"{name:<30} {atype:<20} {inst:<22} {count:>6}")


def cmd_list_txns(args):
    """List recent transactions."""
    import analytics

    kwargs = {"limit": args.limit}
    if args.account:
        kwargs["account_id"] = args.account
    if args.category:
        kwargs["category"] = args.category
    if args.month:
        kwargs["month"] = args.month
    if args.pending:
        kwargs["pending"] = True
    if getattr(args, "search", None):
        kwargs["q"] = args.search

    txns = analytics.get_transactions(**kwargs)
    if not txns:
        print("No transactions found.")
        return

    # Column widths
    print(
        f"{'Date':<12} {'Amount':>10} {'Merchant':<28} {'Account':<18} {'Category':<22} {'Txn ID'}"
    )
    print("-" * 130)
    for t in txns:
        date_str = str(t["date"]) if t["date"] else "—"
        amount = float(t["amount"])
        # Show credits with a minus sign
        amt_str = f"${abs(amount):,.2f}"
        if amount < 0:
            amt_str = f"-{amt_str}"  # credit
        merchant = (t["merchant_name"] or t["name"] or "—")[:27]
        acct = (t["account_name"] or "—")[:17]
        cat = (t.get("effective_category") or "—")[:21]
        txn_id = t["transaction_id"] or "—"

        print(
            f"{date_str:<12} {amt_str:>10} {merchant:<28} {acct:<18} {cat:<22} {txn_id}"
        )


def cmd_report_spend(args):
    """Show spending by category for a given month."""
    import analytics
    from datetime import datetime

    month = args.month
    if not month:
        month = datetime.now().strftime("%Y-%m")

    rows = analytics.spend_by_category(month)
    if not rows:
        print(f"No spending found for {month}.")
        return

    print(f"\nSpending by Category — {month}")
    print(f"{'Category':<36} {'Spend':>10} {'Txns':>6}")
    print("-" * 56)
    total = 0
    for r in rows:
        cat = (r["category"] or "Uncategorized")[:35]
        spend = float(r["total_spend"])
        count = r["txn_count"]
        total += spend
        print(f"{cat:<36} ${spend:>9,.2f} {count:>6}")
    print("-" * 56)
    print(f"{'TOTAL':<36} ${total:>9,.2f}")


def cmd_report_monthly(args):
    """Show month-over-month income vs spend summary."""
    import analytics

    rows = analytics.monthly_summary(months=args.months)
    if not rows:
        print("No transaction data found.")
        return

    print(f"\n{'Month':<10} {'Income':>12} {'Spend':>12} {'Net':>12}")
    print("-" * 50)
    for r in rows:
        month = str(r["month"])[:7]
        income = float(r["income"]) if r["income"] else 0
        spend = float(r["spend"]) if r["spend"] else 0
        net = float(r["net"]) if r["net"] else 0
        print(f"{month:<10} ${income:>11,.2f} ${spend:>11,.2f} ${net:>11,.2f}")


def cmd_categorize(args):
    """Set a user override category on a transaction."""
    import db

    db.upsert_category_override(args.transaction_id, args.category)
    print(f"Transaction {args.transaction_id} → {args.category}")


def cmd_uncategorize(args):
    """Remove a user override category from a transaction."""
    import db

    deleted = db.delete_category_override(args.transaction_id)
    if deleted:
        print(f"Override removed for {args.transaction_id}.")
    else:
        print(f"No override found for {args.transaction_id}.")


def cmd_rule_add(args):
    """Add a category rule."""
    import db

    rule_id = db.add_category_rule(
        match_pattern=args.match,
        match_field=args.field,
        category=args.category,
        priority=args.priority,
    )
    print(
        f"Rule #{rule_id} added: If {args.field} contains '{args.match}' → {args.category}"
    )


def cmd_rule_list(args):
    """List all category rules."""
    import db

    rules = db.list_category_rules()
    if not rules:
        print("No rules defined. Use `rule-add` to create one.")
        return

    print(f"{'ID':<6} {'Field':<22} {'Pattern':<30} {'Category':<24} {'Pri':>3}")
    print("-" * 88)
    for r in rules:
        print(
            f"{r['id']:<6} {r['match_field']:<22} {r['match_pattern']:<30} "
            f"{r['category']:<24} {r['priority']:>3}"
        )


def cmd_rule_remove(args):
    """Delete a category rule."""
    import db

    deleted = db.delete_category_rule(args.rule_id)
    if deleted:
        print(f"Rule #{args.rule_id} deleted.")
    else:
        print(f"No rule found with id {args.rule_id}.")


def cmd_budget_set(args):
    """Set (or update) a monthly budget for a category."""
    import db

    db.upsert_budget(args.category, args.amount)
    print(f"Budget set: {args.category} → ${args.amount:,.2f}/month")


def cmd_budget_list(args):
    """List all budgets."""
    import db

    budgets = db.list_budgets()
    if not budgets:
        print("No budgets set. Use `budget-set` to create one.")
        return

    print(f"{'Category':<36} {'Monthly Limit':>14}")
    print("-" * 52)
    for b in budgets:
        cat = b["category"][:35]
        print(f"{cat:<36} ${float(b['monthly_limit']):>13,.2f}")


def cmd_budget_delete(args):
    """Remove a budget."""
    import db

    deleted = db.delete_budget(args.category)
    if deleted:
        print(f"Budget for '{args.category}' removed.")
    else:
        print(f"No budget found for '{args.category}'.")


def cmd_budget_status(args):
    """Show budget vs actual spend for a month."""
    import analytics
    from datetime import datetime

    month = args.month or datetime.now().strftime("%Y-%m")
    rows = analytics.budget_status(month)
    if not rows:
        print("No budgets set. Use `budget-set` to create one.")
        return

    print(f"\nBudget Status — {month}")
    print(
        f"{'Category':<28} {'Limit':>10} {'Spent':>10} {'Remaining':>10} {'Used%':>7}"
    )
    print("-" * 70)
    for r in rows:
        cat = r["category"][:27]
        limit = r["monthly_limit"]
        actual = r["actual_spend"]
        remaining = r["remaining"]
        pct = r["pct_used"]
        flag = " !" if pct >= 100 else (" ~" if pct >= 80 else "")
        print(
            f"{cat:<28} ${limit:>9,.2f} ${actual:>9,.2f} ${remaining:>9,.2f} {pct:>6.1f}%{flag}"
        )


def cmd_budget_alert(args):
    """Show categories that are on pace to overshoot their budget."""
    import analytics
    from datetime import datetime

    month = args.month or datetime.now().strftime("%Y-%m")
    threshold = args.threshold
    rows = analytics.budget_alert(month, threshold=threshold)
    if not rows:
        print(f"No categories over {threshold:.0f}% of budget for {month}.")
        return

    print(f"\nBudget Alerts ({threshold:.0f}%+ used) — {month}")
    print(f"{'Category':<28} {'Limit':>10} {'Spent':>10} {'Used%':>7}")
    print("-" * 60)
    for r in rows:
        cat = r["category"][:27]
        flag = " OVER!" if r["pct_used"] >= 100 else ""
        print(
            f"{cat:<28} ${r['monthly_limit']:>9,.2f} ${r['actual_spend']:>9,.2f} "
            f"{r['pct_used']:>6.1f}%{flag}"
        )


def cmd_note(args):
    """Set or clear a note on a transaction."""
    import db

    note = args.note.strip()
    if note:
        db.upsert_transaction_note(args.transaction_id, note)
        print(f"Note saved for {args.transaction_id}.")
    else:
        db.delete_transaction_note(args.transaction_id)
        print(f"Note cleared for {args.transaction_id}.")


def cmd_tag_add(args):
    """Add a tag to a transaction."""
    import db

    tag = args.tag.strip().lower()
    db.add_transaction_tag(args.transaction_id, tag)
    print(f"Tag '{tag}' added to {args.transaction_id}.")


def cmd_tag_remove(args):
    """Remove a tag from a transaction."""
    import db

    deleted = db.remove_transaction_tag(args.transaction_id, args.tag)
    if deleted:
        print(f"Tag '{args.tag}' removed from {args.transaction_id}.")
    else:
        print(f"Tag '{args.tag}' not found on {args.transaction_id}.")


def cmd_search(args):
    """Search transactions by text."""
    import analytics

    kwargs = {"limit": args.limit}
    if args.query:
        kwargs["q"] = args.query
    if args.month:
        kwargs["month"] = args.month
    if args.category:
        kwargs["category"] = args.category

    txns = analytics.get_transactions(**kwargs)
    if not txns:
        print("No transactions found.")
        return

    print(f"{'Date':<12} {'Amount':>10} {'Merchant':<28} {'Category':<22} {'Note'}")
    print("-" * 100)
    for t in txns:
        date_str = str(t["date"]) if t["date"] else "—"
        amount = float(t["amount"])
        amt_str = f"${abs(amount):,.2f}"
        if amount < 0:
            amt_str = f"-{amt_str}"
        merchant = (t["merchant_name"] or t["name"] or "—")[:27]
        cat = (t.get("effective_category") or "—")[:21]
        note = (t.get("note") or "")[:20]
        print(f"{date_str:<12} {amt_str:>10} {merchant:<28} {cat:<22} {note}")


def cmd_view_save(args):
    """Save a named search view."""
    import db

    filters = {}
    if args.search:
        filters["q"] = args.search
    if args.month:
        filters["month"] = args.month
    if args.category:
        filters["category"] = args.category
    db.upsert_view(args.name, filters)
    print(f"View '{args.name}' saved.")


def cmd_view_list(args):
    """List all saved search views."""
    import db

    views = db.list_views()
    if not views:
        print("No saved views. Use `view-save` to create one.")
        return

    for v in views:
        parts = ", ".join(f"{k}={val}" for k, val in v["filters"].items() if val)
        print(f"  {v['name']:<24} {parts}")


def cmd_view_delete(args):
    """Delete a saved search view."""
    import db

    deleted = db.delete_view(args.name)
    if deleted:
        print(f"View '{args.name}' deleted.")
    else:
        print(f"No view found named '{args.name}'.")


def cmd_web(args):
    """Start the persistent web dashboard."""
    import logging
    import web_server

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    web_server.run(port=args.port)


def cmd_detect_transfers(args):
    """Detect internal TRANSFER_IN/OUT pairs and mark them as INTERNAL TRANSFER."""
    import analytics

    pairs = analytics.detect_internal_transfers(dry_run=args.dry_run)
    if not pairs:
        print("No new transfer pairs found.")
        return

    label = "Would mark" if args.dry_run else "Marked"
    print(f"\n{label} {len(pairs)} internal transfer pair(s):\n")
    print(f"  {'Amount':>10}  {'Transfer ID':<20} {'Account A':<24} {'Account B'}")
    print("  " + "-" * 76)
    for p in pairs:
        print(
            f"  ${p['amount']:>9,.2f}  {p['transfer_id']:<20} "
            f"{(p['account_a'] or '—'):<24} {p['account_b'] or '—'}"
        )


def cmd_remove_item(args):
    """Revoke a linked institution and delete all its data."""
    import db
    from plaid_client import PlaidClient

    item = db.get_item(args.item_id)
    if not item:
        print(f"No item found with ID {args.item_id}.")
        return

    name = item.get("institution_name") or args.item_id
    print(f"Institution:  {name}")
    print(f"Item ID:      {args.item_id}")
    print(
        "This will permanently delete all accounts, transactions, overrides, notes, "
        "tags, and rules associated with this item."
    )
    answer = input("Type 'yes' to confirm: ").strip().lower()
    if answer != "yes":
        print("Aborted.")
        return

    import os

    if os.environ.get("PLAID_SKIP_REVOKE"):
        print("PLAID_SKIP_REVOKE set — skipping Plaid revoke.")
    else:
        try:
            PlaidClient().remove_item(item["access_token"])
            print("Plaid access token revoked.")
        except Exception as exc:
            print(
                f"Warning: Plaid revoke failed ({exc}). Proceeding with local delete."
            )

    deleted = db.delete_item(args.item_id)
    if deleted:
        print(f"Deleted '{name}' and all associated data.")
    else:
        print("Item not found in DB (already deleted?).")


def cmd_rule_apply(args):
    """Apply rules to all un-categorized transactions."""
    import analytics

    results = analytics.apply_rules(dry_run=args.dry_run)
    if not results:
        print("No matching rules found.")
        return

    label = "Would match" if args.dry_run else "Matched"
    print(f"\n{label} {len(results)} transaction(s):")
    for r in results:
        print(
            f"  {r['transaction_id'][:16]}  {r['old_category'] or '—':<24} → {r['new_category']}"
        )


def main():
    parser = argparse.ArgumentParser(
        prog="finance",
        description="Personal finance tracker powered by Plaid + PostgreSQL",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Initialize database schema")
    p_init.set_defaults(func=cmd_init)

    # link
    p_link = sub.add_parser("link", help="Connect a bank account via Plaid Link")
    p_link.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Local port for the Link server (default: 8765)",
    )
    p_link.set_defaults(func=cmd_link)

    # sync
    p_sync = sub.add_parser("sync", help="Sync transactions for all linked accounts")
    p_sync.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress per-page output"
    )
    p_sync.set_defaults(func=cmd_sync)

    # accounts
    p_acct = sub.add_parser(
        "accounts", help="List all accounts with transaction counts"
    )
    p_acct.set_defaults(func=cmd_accounts)

    # report-spend
    p_rspend = sub.add_parser("report-spend", help="Spending by category for a month")
    p_rspend.add_argument(
        "--month", type=str, help="Month YYYY-MM (default: current month)"
    )
    p_rspend.set_defaults(func=cmd_report_spend)

    # report-monthly
    p_rmonth = sub.add_parser("report-monthly", help="Month-over-month income vs spend")
    p_rmonth.add_argument(
        "--months", type=int, default=12, help="Number of months to show (default: 12)"
    )
    p_rmonth.set_defaults(func=cmd_report_monthly)

    # list-txns
    p_txns = sub.add_parser("list-txns", help="List recent transactions")
    p_txns.add_argument(
        "--limit", type=int, default=50, help="Max transactions (default: 50)"
    )
    p_txns.add_argument("--account", type=str, help="Filter by account ID")
    p_txns.add_argument(
        "--category", type=str, help="Filter by Plaid personal_finance_category"
    )
    p_txns.add_argument("--month", type=str, help="Filter to month YYYY-MM")
    p_txns.add_argument(
        "--pending", action="store_true", help="Include pending transactions"
    )
    p_txns.add_argument(
        "--search", type=str, help="Full-text search (name, merchant, note)"
    )
    p_txns.set_defaults(func=cmd_list_txns)

    # categorize
    p_cat = sub.add_parser(
        "categorize", help="Override Plaid category on a transaction"
    )
    p_cat.add_argument("transaction_id", type=str, help="Transaction ID")
    p_cat.add_argument("category", type=str, help="New category name")
    p_cat.set_defaults(func=cmd_categorize)

    # uncategorize
    p_uncat = sub.add_parser("uncategorize", help="Remove a category override")
    p_uncat.add_argument("transaction_id", type=str, help="Transaction ID")
    p_uncat.set_defaults(func=cmd_uncategorize)

    # rule-add
    p_radd = sub.add_parser("rule-add", help="Add a category rule")
    p_radd.add_argument(
        "--match", type=str, required=True, help="Text to match (case-insensitive)"
    )
    p_radd.add_argument(
        "--field",
        type=str,
        default="merchant_name",
        choices=["merchant_name", "name", "personal_finance_category"],
        help="Field to match against (default: merchant_name)",
    )
    p_radd.add_argument(
        "--category",
        type=str,
        required=True,
        help="Category to assign when rule matches",
    )
    p_radd.add_argument(
        "--priority", type=int, default=0, help="Higher priority rules run first"
    )
    p_radd.set_defaults(func=cmd_rule_add)

    # rule-list
    p_rlist = sub.add_parser("rule-list", help="List all category rules")
    p_rlist.set_defaults(func=cmd_rule_list)

    # rule-remove
    p_rrem = sub.add_parser("rule-remove", help="Delete a category rule")
    p_rrem.add_argument("rule_id", type=int, help="Rule ID (from rule-list)")
    p_rrem.set_defaults(func=cmd_rule_remove)

    # rule-apply
    p_rapply = sub.add_parser(
        "rule-apply", help="Apply rules to uncategorized transactions"
    )
    p_rapply.add_argument(
        "--dry-run", action="store_true", help="Preview matches without saving"
    )
    p_rapply.set_defaults(func=cmd_rule_apply)

    # detect-transfers
    p_dtrans = sub.add_parser(
        "detect-transfers",
        help="Detect TRANSFER_IN/OUT pairs and mark them as INTERNAL TRANSFER",
    )
    p_dtrans.add_argument(
        "--dry-run", action="store_true", help="Preview pairs without saving"
    )
    p_dtrans.set_defaults(func=cmd_detect_transfers)

    # note
    p_note = sub.add_parser("note", help="Set or clear a note on a transaction")
    p_note.add_argument("transaction_id", type=str, help="Transaction ID")
    p_note.add_argument("note", type=str, help="Note text (empty string to clear)")
    p_note.set_defaults(func=cmd_note)

    # tag-add
    p_tadd = sub.add_parser("tag-add", help="Add a tag to a transaction")
    p_tadd.add_argument("transaction_id", type=str, help="Transaction ID")
    p_tadd.add_argument("tag", type=str, help="Tag to add")
    p_tadd.set_defaults(func=cmd_tag_add)

    # tag-remove
    p_trem = sub.add_parser("tag-remove", help="Remove a tag from a transaction")
    p_trem.add_argument("transaction_id", type=str, help="Transaction ID")
    p_trem.add_argument("tag", type=str, help="Tag to remove")
    p_trem.set_defaults(func=cmd_tag_remove)

    # search
    p_srch = sub.add_parser("search", help="Full-text search across transactions")
    p_srch.add_argument("query", type=str, nargs="?", default="", help="Search text")
    p_srch.add_argument("--month", type=str, help="Filter to month YYYY-MM")
    p_srch.add_argument("--category", type=str, help="Filter by category")
    p_srch.add_argument(
        "--limit", type=int, default=50, help="Max results (default: 50)"
    )
    p_srch.set_defaults(func=cmd_search)

    # view-save
    p_vsave = sub.add_parser("view-save", help="Save a named search view")
    p_vsave.add_argument("name", type=str, help="View name")
    p_vsave.add_argument("--search", type=str, default="", help="Search text")
    p_vsave.add_argument("--month", type=str, default="", help="Month YYYY-MM")
    p_vsave.add_argument("--category", type=str, default="", help="Category")
    p_vsave.set_defaults(func=cmd_view_save)

    # view-list
    p_vlist = sub.add_parser("view-list", help="List saved search views")
    p_vlist.set_defaults(func=cmd_view_list)

    # view-delete
    p_vdel = sub.add_parser("view-delete", help="Delete a saved search view")
    p_vdel.add_argument("name", type=str, help="View name")
    p_vdel.set_defaults(func=cmd_view_delete)

    # web
    p_web = sub.add_parser("web", help="Start the web dashboard")
    p_web.add_argument(
        "--port", type=int, default=8123, help="Port to listen on (default: 5000)"
    )
    p_web.add_argument(
        "--debug", action="store_true", help="Enable DEBUG logging (verbose)"
    )
    p_web.set_defaults(func=cmd_web)

    # budget-set
    p_bset = sub.add_parser("budget-set", help="Set a monthly budget for a category")
    p_bset.add_argument("category", type=str, help="Category name")
    p_bset.add_argument("amount", type=float, help="Monthly limit in dollars")
    p_bset.set_defaults(func=cmd_budget_set)

    # budget-list
    p_blist = sub.add_parser("budget-list", help="List all budgets")
    p_blist.set_defaults(func=cmd_budget_list)

    # budget-delete
    p_bdel = sub.add_parser("budget-delete", help="Remove a budget")
    p_bdel.add_argument("category", type=str, help="Category name")
    p_bdel.set_defaults(func=cmd_budget_delete)

    # budget-status
    p_bstat = sub.add_parser("budget-status", help="Budget vs actual spend for a month")
    p_bstat.add_argument(
        "--month", type=str, help="Month YYYY-MM (default: current month)"
    )
    p_bstat.set_defaults(func=cmd_budget_status)

    # budget-alert
    p_balert = sub.add_parser(
        "budget-alert", help="Flag categories over a usage threshold"
    )
    p_balert.add_argument(
        "--month", type=str, help="Month YYYY-MM (default: current month)"
    )
    p_balert.add_argument(
        "--threshold",
        type=float,
        default=80.0,
        help="Alert threshold as percent used (default: 80)",
    )
    p_balert.set_defaults(func=cmd_budget_alert)

    # list-items
    p_list = sub.add_parser("list-items", help="List all linked institutions")
    p_list.set_defaults(func=cmd_list_items)

    # remove-item
    p_rem = sub.add_parser(
        "remove-item",
        help="Revoke a linked institution and delete all its data",
    )
    p_rem.add_argument("item_id", type=str, help="Item ID (from list-items)")
    p_rem.set_defaults(func=cmd_remove_item)

    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(0)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
