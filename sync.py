import fcntl
import logging
import tempfile
from pathlib import Path

import analytics
import db
from plaid_client import PlaidClient

_log = logging.getLogger(__name__)

# Path of the sync lock below. A module constant so tests can point it at a
# private temp file.
LOCK_PATH = Path(tempfile.gettempdir()) / "rock_money_sync.lock"


def _try_sync_lock():
    """Take the "one sync at a time" lock, or return None if a sync is already
    running.

    The dashboard runs under gunicorn with 2 workers and `main.py sync` can
    overlap with the Sync button, so this has to be a real cross-process lock,
    not a threading.Lock. The kernel drops it when the holder exits, so a worker
    killed mid-sync cannot wedge syncing forever.
    """
    handle = open(LOCK_PATH, "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


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


def sync_all() -> dict:
    """Sync every linked item, unless another sync is still running.

    Returns a summary dict:
      ran: False when the lock was busy (nothing was synced)
      items_total: number of items the run attempted
      failed_items: names of items whose sync raised (empty on full success)
      added/modified/removed: totals across all items
    """
    lock = _try_sync_lock()
    if lock is None:
        _log.warning("another sync is still running — skipping this one")
        return {
            "ran": False,
            "items_total": 0,
            "failed_items": [],
            "added": 0,
            "modified": 0,
            "removed": 0,
        }
    try:
        return _sync_all()
    finally:
        lock.close()


def _sync_all() -> dict:
    """Syncs all linked items stored in the database.

    A failing item is logged and retried on the next sync; it does not stop
    the other items, but it IS reported in failed_items so the caller can say
    the sync did not complete.
    """
    items = db.list_items()
    summary = {
        "ran": True,
        "items_total": len(items),
        "failed_items": [],
        "added": 0,
        "modified": 0,
        "removed": 0,
    }
    if not items:
        _log.warning(
            "No linked items found. Run `python main.py link` to connect an account."
        )
        return summary

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
            summary["failed_items"].append(name)
            continue
        try:
            totals = sync_item(item["item_id"], row[0])
            summary["added"] += totals["added"]
            summary["modified"] += totals["modified"]
            summary["removed"] += totals["removed"]
        except Exception as exc:
            _log.error("[%s] sync failed: %s", name, exc)
            summary["failed_items"].append(name)

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
    return summary
