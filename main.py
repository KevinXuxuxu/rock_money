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
