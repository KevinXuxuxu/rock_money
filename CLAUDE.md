# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Self-hosted personal finance tracker: Plaid → PostgreSQL, with a Flask web dashboard. Goal is a local replacement for Rocket Money. Python 3.12, deps managed by `uv`.

## Commands

```bash
uv run python main.py <command>   # CLI: init, link, sync, list-items, accounts,
                                  # list-txns, report-spend, report-monthly,
                                  # categorize, uncategorize, rule-add|list|remove|apply,
                                  # budget-set|list|delete|status|alert, note,
                                  # tag-add|remove, search, view-save|list|delete,
                                  # detect-transfers, remove-item, web
uv run pytest                     # 344 tests, all DB-mocked (see Testing)
uv run ruff format --check . && uv run ruff check .   # CI gates
```

Web dashboard: `uv run python main.py web --port 8123` (production: gunicorn `web_server:app`, see Dockerfile).

## Architecture

Data flow: `main.py` (CLI) and `web_server.py` (dashboard) → `sync.py` / `analytics.py` → `plaid_client.py` + `db.py`.

**`plaid_client.py`** — plaid-python wrapper. `sync_transactions()` yields pages of `{added, modified, removed, next_cursor, has_more, accounts}` until `has_more` is false. `create_link_token()` takes optional `redirect_uri` (required for OAuth institutions in production).

**`db.py`** — raw psycopg2, `ThreadedConnectionPool`. All writes are `ON CONFLICT DO UPDATE` upserts (idempotent). `get_conn()` context manager: acquire → commit/rollback → release. `execute_values` batch inserts: tuple length must exactly match `%s` count in `template=`.

**`sync.py`** — cursor loop per item: load cursor → fetch pages → upsert accounts/txns → delete removed → persist cursor **per page** (crash-safe). After all items: `analytics.apply_rules()` then `analytics.detect_internal_transfers()`.

**`analytics.py`** — all read queries + rule engine + transfer detection. See "Domain rules" below.

**`web_server.py`** — Flask dashboard: `/` (dashboard), `/accounts` (labels, sync now, link, remove item), `/transactions` (search, month/category/account filters, saved views, inline category edit preserving filters, CSV export), `/transactions/<id>` (note, tags, category), `/reports` (Sankey via Plotly, bar charts, budgets), `/rules` (search + pagination).

**`export.py`** — CSV in Rocket Money's exact export format (re-importable into RM); header row in `CSV_HEADER` must not change.

**`link_server.py`** — temporary Flask server for the Plaid Link flow only.

## Domain rules

- **Amounts**: positive = spend (debit), negative = income (credit) — Plaid's raw convention.
- **`EXCLUDED_CATEGORIES`** (`analytics.py`): `INTERNAL TRANSFER`, `CREDIT PAYMENT`, `INVESTMENT` are excluded from ALL spend/income/cash-flow aggregations. Any new exclusion must go in this set so dashboard, reports, and Sankey stay in sync.
- **`_NOT_SUPERSEDED` guard** (in `analytics.py`): a pending transaction that a posted row already points to via `pending_transaction_id` is excluded, so nothing double-counts before Plaid removes the pending row. Assumes the `transactions` alias is `t`.
- **Category resolution**: user override (`category_overrides`) > rule match > Plaid `personal_finance_category` > "Uncategorized". `effective_category` is `COALESCE(co.category, t.personal_finance_category)` in SQL.
- **Rules**: case-insensitive substring match on `merchant_name` (falls back to `name`), `name`, or `personal_finance_category`; first match wins, ordered by `priority DESC, id`. `apply_rules(dry_run=True)` matches ALL transactions (for testing); real apply skips already-overridden rows.
- **Internal transfers**: paired by bank transfer ref IDs extracted from `name` (regexes in `_TRANSFER_ID_PATTERNS` — Citi `IITCIT…`, Chase `transaction#: N`); amounts must cancel within $0.01. Marked legs get an `INTERNAL TRANSFER` override. Self-heals Plaid's pending→posted ID churn (a reposted leg re-pairs with its already-marked partner). New bank patterns are added to `_TRANSFER_ID_PATTERNS`.

## Database schema

Ten tables (see `schema.sql`): `items` (access token) → `accounts` (has user `label` column, never touched by sync upserts) → `transactions`. Plus `sync_cursors` (1:1 with items), `category_overrides`, `category_rules`, `budgets`, `transaction_notes`, `transaction_tags`, `saved_views`. Deleting an item cascades to everything.

**Migrations**: `init` is `CREATE TABLE IF NOT EXISTS` — safe to re-run, does NOT migrate. New tables appear automatically on re-init; new columns on existing tables are silently ignored. When adding a column, update `schema.sql` AND run `ALTER TABLE` manually on both DBs.

## Development environment

- **Runs inside a container; PostgreSQL is on the host.** DB is reachable at `host.docker.internal:5432` (verified working). `.env` has `DATABASE_URL=...localhost:5432/...`, which does NOT resolve from the container — always override explicitly:
  ```bash
  DATABASE_URL=postgresql://postgres@host.docker.internal:5432/rock_money uv run python main.py <cmd>
  ```
- **Two databases exist** (user `postgres`, no password):
  - `rock_money` — **live data** (linked institutions, real txns through today).
  - `rock_money_test` — stale test snapshot (fewer items/txns, older date range). The checked-in `.env` points here, so a bare `uv run python main.py sync` writes test data into the test DB using live Plaid tokens.
- The `.venv` may be built for the wrong platform (e.g. macOS). `uv` recreates it automatically on first run if the interpreter is missing — this is normal, not an error.
- Git remotes: `origin` (GitHub), `local` (git.local.fzxu.me). Branch `main`.

## Environment variables (`.env`)

Required: `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV` (`sandbox`|`production`), `DATABASE_URL`.
Optional: `PLAID_REDIRECT_URI` (HTTPS URL for OAuth institutions in production — currently set), `PLAID_SKIP_REVOKE=1` (skip Plaid `item/remove` when deleting an item — set in this env).

Plaid sandbox test credentials: `user_good` / `pass_good`. Phone OTP: `123456`.

## Testing

`tests/` never touch a real DB: an autouse fixture replaces `db.get_conn` with a guard that fails loudly on any real connection. Use the `mock_db` fixture (patches `db.get_conn`, yields the mock cursor — set `fetchall`/`fetchone` return values, inspect `execute.call_args` for SQL). `make_txn()` / `make_account()` in `conftest.py` build sample row dicts.
