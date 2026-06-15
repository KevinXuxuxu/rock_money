# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run any command
uv run python main.py <command>

# First-time setup: initialize DB schema
uv run python main.py init

# Connect a bank account (opens browser → Plaid Link)
uv run python main.py link

# Sync transactions for all linked accounts
uv run python main.py sync

# List linked institutions and last sync time
uv run python main.py list-items
```

Dependencies are managed with `uv` (`pyproject.toml`). Python 3.12 required.

## Architecture

Five modules with a clear data flow: `main.py` → `link_server.py` or `sync.py` → `plaid_client.py` + `db.py`.

**`plaid_client.py`** — Wraps the plaid-python SDK. `PlaidClient.sync_transactions()` is a generator that yields pages of `{added, modified, removed, next_cursor, has_more, accounts}` until exhausted. `create_link_token()` accepts an optional `redirect_uri` (required for OAuth institutions in production).

**`db.py`** — Raw psycopg2 with a `ThreadedConnectionPool`. All writes use `ON CONFLICT DO UPDATE` (upsert) so syncs are idempotent. The `get_conn()` context manager handles acquire/commit/rollback/release. `execute_values` with an explicit `template=` is used for batch inserts — the tuple length must match the number of `%s` placeholders in the template exactly.

**`sync.py`** — `sync_item()` drives the cursor loop: load cursor from DB → call `plaid_client.sync_transactions()` → upsert accounts and transactions → delete removed → persist `next_cursor` after each page. Cursor is persisted per-page so a crash mid-sync doesn't re-fetch already-saved pages.

**`link_server.py`** — Temporary Flask server used only during account linking. Serves `templates/link.html` with Plaid Link JS, exchanges the public token for an access token via `/api/exchange`, then signals the main thread to shut down. `PLAID_REDIRECT_URI` env var enables OAuth-based institutions (Chase, BofA, etc.) in production; without it those institutions are unavailable.

## Database Schema

Four tables: `items` (one per linked institution, stores access token) → `accounts` (bank accounts within an item) → `transactions`. `sync_cursors` is a 1:1 with `items`, tracking the Plaid cursor position for incremental sync. Deleting an item cascades to all its accounts and transactions.

**Amount convention**: positive = debit (money out), negative = credit (money in) — matches Plaid's raw values.

**Schema migrations**: `init` uses `CREATE TABLE IF NOT EXISTS` throughout — safe to re-run, but it does not migrate. New tables in `schema.sql` are created automatically on re-init; new columns on existing tables are silently ignored. When adding a column to an existing table, run the `ALTER TABLE` manually via psql in addition to updating `schema.sql`.

## Environment

Copy `.env.example` to `.env`. Required vars: `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV` (`sandbox` or `production`), `DATABASE_URL`. Optional: `PLAID_REDIRECT_URI` (HTTPS URL for OAuth institutions in production — use ngrok locally).

Plaid sandbox test credentials: username `user_good` / password `pass_good`. Phone OTP: `123456`.
