# rock-money

A self-hosted personal finance tracker. Today it's a thin wrapper around the
[Plaid](https://plaid.com) API for linking bank accounts and pulling
transactions into a local PostgreSQL database. The goal is to grow into a
full replacement for Rocket Money, Copilot, Monarch, and similar
subscription-priced finance apps — fully owned, fully local, no monthly fee
and no third party holding onto your data.

## What works today

- Link bank, brokerage, and credit card accounts via Plaid Link (sandbox or
  production).
- Incremental transaction sync using Plaid's `/transactions/sync` cursor API.
  Crash-safe: cursors are persisted per-page so a re-run never re-fetches.
- Idempotent upserts — running `sync` repeatedly is safe.
- Cascading deletes: removing an item cleans up its accounts and transactions.

## Setup

Requires Python 3.12, [uv](https://github.com/astral-sh/uv), and a running
PostgreSQL instance.

```bash
# 1. Install dependencies
uv sync

# 2. Configure environment
cp .env.example .env
# edit .env with PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV, DATABASE_URL

# 3. Initialize the database
uv run python main.py init
```

For OAuth-based institutions (Chase, Bank of America, etc.) in production,
also set `PLAID_REDIRECT_URI` to an HTTPS URL registered in your Plaid
dashboard. Locally you can tunnel with [ngrok](https://ngrok.com).

## Usage

```bash
# Connect a bank account — opens a browser to Plaid Link
uv run python main.py link

# Pull new transactions for every linked institution
uv run python main.py sync

# See what's connected and when it was last synced
uv run python main.py list-items
```

Plaid sandbox test credentials: username `user_good`, password `pass_good`,
phone OTP `123456`.

## Data model

Four tables in PostgreSQL:

- `items` — one row per linked institution (holds the Plaid access token)
- `accounts` — bank/credit/investment accounts within an item
- `transactions` — individual transactions
- `sync_cursors` — Plaid sync cursor per item

Amount convention follows Plaid's raw values: **positive = debit (money out),
negative = credit (money in)**.

## Roadmap

The current CLI is just the ingestion layer. The plan is to build a complete
finance management system on top of it.

### Near term — analytics on top of the existing data

- [ ] **Income & spend categorization** — auto-classify transactions using
      Plaid's `personal_finance_category` plus user-defined rules and
      overrides.
- [ ] **Recurring transaction detection** — surface subscriptions, bills,
      and paychecks so the obvious "this charge again" cases don't need
      manual tagging.
- [ ] **Monthly cash-flow reports** — income vs. spend by category, month
      over month, with a CLI summary.
- [ ] **Budgets** — per-category monthly budgets with progress and rollover
      rules. Alerting when a category is on pace to overshoot.

### Mid term — frontend

- [ ] **Web dashboard** — accounts overview, net worth chart, recent
      transactions, spend by category, budget progress. Local-first, runs
      next to the database.
- [ ] **Transaction editor** — split transactions, recategorize, add notes
      and tags, hide internal transfers from spend totals.
- [ ] **Search & filters** — across all transactions, with saved views.

### Longer term — feature parity with Rocket Money / Copilot / Monarch

- [ ] **Net worth tracking** — historical balances per account, including
      manually-tracked assets (real estate, vehicles, private investments).
- [ ] **Goals** — savings targets, debt paydown projections.
- [ ] **Subscription management** — flag subscriptions, surface price
      changes, estimate annual cost.
- [ ] **Bill negotiation reminders** — flag candidates, but no third-party
      "we'll negotiate for a cut of the savings" middleman.
- [ ] **Investment account drill-down** — holdings, cost basis, allocation.
- [ ] **Multi-user / household mode** — shared accounts with per-user
      visibility rules.
- [ ] **Mobile-friendly UI or companion app**.
- [ ] **Import from CSV / OFX / QIF** — for accounts Plaid can't reach, and
      for historical data backfill.
- [ ] **Export everything** — your data, your database, easy to leave.

## Architecture

Five modules with a clear data flow:
`main.py` → `link_server.py` or `sync.py` → `plaid_client.py` + `db.py`.

- `plaid_client.py` — wraps the plaid-python SDK; `sync_transactions()` is a
  generator over cursor pages.
- `db.py` — raw psycopg2 with a `ThreadedConnectionPool`; all writes are
  upserts.
- `sync.py` — drives the cursor loop and persists progress per-page.
- `link_server.py` — short-lived Flask server that hosts Plaid Link during
  the connect flow, then shuts itself down.
- `main.py` — argparse CLI entrypoint.

See [CLAUDE.md](CLAUDE.md) for deeper notes on each module.
