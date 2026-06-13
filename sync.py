import db
from plaid_client import PlaidClient


def sync_item(item_id: str, access_token: str, verbose: bool = True) -> dict:
    """
    Incrementally syncs one Plaid item using cursor-based pagination.
    Returns a summary dict with counts of added/modified/removed transactions.
    """
    client = PlaidClient()
    cursor = db.get_cursor(item_id)

    if verbose:
        status = "fresh start" if cursor is None else "resuming from cursor"
        print(f"  Syncing item {item_id} ({status})")

    total = {"added": 0, "modified": 0, "removed": 0}
    page = 0

    for page_data in client.sync_transactions(access_token, cursor=cursor):
        page += 1

        # Attach item_id to accounts (needed for FK)
        accounts = [{**a, "item_id": item_id} for a in page_data["accounts"]]
        db.upsert_accounts(accounts)

        db.upsert_transactions(page_data["added"] + page_data["modified"])
        n_removed = db.delete_transactions(page_data["removed"])
        db.set_cursor(item_id, page_data["next_cursor"])

        total["added"] += len(page_data["added"])
        total["modified"] += len(page_data["modified"])
        total["removed"] += n_removed

        if verbose:
            print(
                f"    page {page}: "
                f"+{len(page_data['added'])} added, "
                f"~{len(page_data['modified'])} modified, "
                f"-{n_removed} removed"
            )

    if verbose:
        print(
            f"  Done. Total: "
            f"+{total['added']} added, "
            f"~{total['modified']} modified, "
            f"-{total['removed']} removed"
        )

    return total


def sync_all(verbose: bool = True) -> None:
    """Syncs all linked items stored in the database."""
    items = db.list_items()
    if not items:
        print("No linked items found. Run `python main.py link` to connect an account.")
        return

    print(f"Syncing {len(items)} item(s)...")
    for item in items:
        name = item.get("institution_name") or item["item_id"]
        print(f"\n[{name}]")
        # Fetch access_token for this item
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT access_token FROM items WHERE item_id = %s",
                    (item["item_id"],),
                )
                row = cur.fetchone()
        if not row:
            print("  Skipping — access token not found.")
            continue
        try:
            sync_item(item["item_id"], row[0], verbose=verbose)
        except Exception as exc:
            print(f"  ERROR: {exc}")
