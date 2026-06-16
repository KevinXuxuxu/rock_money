import logging

import analytics
import db
from plaid_client import PlaidClient

_log = logging.getLogger(__name__)


def sync_item(item_id: str, access_token: str) -> dict:
    """
    Incrementally syncs one Plaid item using cursor-based pagination.
    Returns a summary dict with counts of added/modified/removed transactions.
    """
    client = PlaidClient()
    cursor = db.get_cursor(item_id)
    status = "fresh start" if cursor is None else "resuming from cursor"
    _log.info("  syncing (%s)", status)

    total = {"added": 0, "modified": 0, "removed": 0}
    page = 0

    for page_data in client.sync_transactions(access_token, cursor=cursor):
        page += 1

        accounts = [{**a, "item_id": item_id} for a in page_data["accounts"]]
        db.upsert_accounts(accounts)
        db.upsert_transactions(page_data["added"] + page_data["modified"])
        n_removed = db.delete_transactions(page_data["removed"])
        db.set_cursor(item_id, page_data["next_cursor"])

        total["added"] += len(page_data["added"])
        total["modified"] += len(page_data["modified"])
        total["removed"] += n_removed

        _log.debug(
            "    page %d: +%d added, ~%d modified, -%d removed",
            page,
            len(page_data["added"]),
            len(page_data["modified"]),
            n_removed,
        )

    _log.info(
        "  done: +%d added, ~%d modified, -%d removed",
        total["added"],
        total["modified"],
        total["removed"],
    )
    return total


def sync_all() -> None:
    """Syncs all linked items stored in the database."""
    items = db.list_items()
    if not items:
        _log.warning(
            "No linked items found. Run `python main.py link` to connect an account."
        )
        return

    _log.info("Starting sync of %d item(s)", len(items))
    for item in items:
        name = item.get("institution_name") or item["item_id"]
        _log.info("[%s]", name)
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT access_token FROM items WHERE item_id = %s",
                    (item["item_id"],),
                )
                row = cur.fetchone()
        if not row:
            _log.warning("[%s] skipping — access token not found", name)
            continue
        try:
            sync_item(item["item_id"], row[0])
        except Exception as exc:
            _log.error("[%s] sync failed: %s", name, exc)

    rules = db.list_category_rules()
    if rules:
        _log.info("Applying %d rule(s) to new transactions...", len(rules))
        matched = analytics.apply_rules(dry_run=False)
        if matched:
            _log.info("Categorised %d transaction(s) via rules.", len(matched))

    _log.info("Detecting internal transfers...")
    pairs = analytics.detect_internal_transfers(dry_run=False)
    if pairs:
        _log.info("Marked %d transfer pair(s) as INTERNAL TRANSFER.", len(pairs))
    else:
        _log.info("No new transfer pairs found.")

    _log.info("Sync complete.")
