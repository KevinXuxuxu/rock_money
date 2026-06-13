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
    import sync
    sync.sync_all(verbose=not args.quiet)


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
        name      = (item.get("institution_name") or "—")[:29]
        item_id   = item["item_id"][:31]
        synced_at = item.get("last_synced_at")
        synced_str = synced_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if synced_at else "never"
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
        name      = (a["name"] or "—")[:29]
        atype     = f"{a.get('subtype') or a['type']}"[:19]
        inst      = (a.get("institution_name") or "—")[:21]
        count     = a["txn_count"]
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

    txns = analytics.get_transactions(**kwargs)
    if not txns:
        print("No transactions found.")
        return

    # Column widths
    print(f"{'Date':<12} {'Amount':>10} {'Merchant':<32} {'Account':<20} {'Category'}")
    print("-" * 110)
    for t in txns:
        date_str  = str(t["date"]) if t["date"] else "—"
        amount    = float(t["amount"])
        # Show credits with a minus sign
        amt_str   = f"${abs(amount):,.2f}"
        if amount < 0:
            amt_str = f"-{amt_str}"  # credit
        merchant  = (t["merchant_name"] or t["name"] or "—")[:31]
        acct      = (t["account_name"] or "—")[:19]
        cat       = t.get("personal_finance_category") or "—"

        print(f"{date_str:<12} {amt_str:>10} {merchant:<32} {acct:<20} {cat}")


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
    p_link.add_argument("--port", type=int, default=8765, help="Local port for the Link server (default: 8765)")
    p_link.set_defaults(func=cmd_link)

    # sync
    p_sync = sub.add_parser("sync", help="Sync transactions for all linked accounts")
    p_sync.add_argument("-q", "--quiet", action="store_true", help="Suppress per-page output")
    p_sync.set_defaults(func=cmd_sync)

    # accounts
    p_acct = sub.add_parser("accounts", help="List all accounts with transaction counts")
    p_acct.set_defaults(func=cmd_accounts)

    # list-txns
    p_txns = sub.add_parser("list-txns", help="List recent transactions")
    p_txns.add_argument("--limit", type=int, default=50, help="Max transactions (default: 50)")
    p_txns.add_argument("--account", type=str, help="Filter by account ID")
    p_txns.add_argument("--category", type=str, help="Filter by Plaid personal_finance_category")
    p_txns.add_argument("--month", type=str, help="Filter to month YYYY-MM")
    p_txns.add_argument("--pending", action="store_true", help="Include pending transactions")
    p_txns.set_defaults(func=cmd_list_txns)

    # list-items
    p_list = sub.add_parser("list-items", help="List all linked institutions")
    p_list.set_defaults(func=cmd_list_items)

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
