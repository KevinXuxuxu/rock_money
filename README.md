# rock-money

A self-hosted personal finance tracker. Wraps the [Plaid](https://plaid.com)
API for linking bank accounts and pulling transactions into a local PostgreSQL
database. The goal is to grow into a full replacement for Rocket Money, Copilot,
Monarch, and similar subscription-priced finance apps — fully owned, fully
local, no monthly fee and no third party holding onto your data.

## What works today

**Ingestion**
- Link bank, brokerage, and credit card accounts via Plaid Link (sandbox or
  production).
- Incremental transaction sync using Plaid's `/transactions/sync` cursor API.
  Crash-safe: cursors are persisted per-page so a re-run never re-fetches.
- Idempotent upserts — running `sync` repeatedly is safe.
- Pending transactions are counted in stats; a pending row already superseded
  by its posted twin is excluded so nothing is double-counted.
- Cascading deletes: removing an item cleans up its accounts and transactions.

**Internal transfer detection**
- Runs automatically after every sync (or standalone via `detect-transfers`).
- Matches transfer legs by bank-assigned reference IDs (Citi `IITCIT…`, Chase
  `transaction#: N` today) and requires the amounts to cancel within $0.01.
- Marked pairs get an `INTERNAL TRANSFER` category and are excluded from
  spend/income aggregations so moving money between your own accounts never
  distorts reports.
- Self-healing: handles Plaid's pending→posted ID churn (a reposted leg
  re-pairs with its already-marked partner), never clobbers manual or rule
  overrides, and `--dry-run` previews pairs without writing.

**Web dashboard** (`uv run python main.py web`)
- Account summary with transaction counts and debit/credit totals.
- Transactions page with full-text search (merchant, name, note), month/
  category/account filters, saved search views, and a live total for the
  current filter.
- Transaction detail page: override category, add a note, add/remove tags.
- Spend-by-category bar chart and month-over-month cash-flow report; report
  categories link through to the filtered transactions list.
- Budget tracking: set per-category monthly limits and track progress.
- Rules page with search (pattern or category) and pagination — browsable
  even with hundreds of rules.

**Category rules engine**
- Define rules that match transactions by merchant name, display name, or
  category (substring match, case-insensitive).
- Rules auto-apply after every sync — new transactions are categorized without
  manual work.
- Dry-run mode lets you preview which transactions a rule would match before
  saving.
- Manual category overrides on individual transactions are never clobbered by
  rules.

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

# Launch the web dashboard (default: http://localhost:8123)
uv run python main.py web

# Enable verbose logging
uv run python main.py web --debug

# Detect internal transfers (also runs automatically after every sync)
uv run python main.py detect-transfers --dry-run  # preview only
uv run python main.py detect-transfers            # mark pairs as INTERNAL TRANSFER
```

Plaid sandbox test credentials: username `user_good`, password `pass_good`,
phone OTP `123456`.

## Data model

Ten tables in PostgreSQL:

- `items` — one row per linked institution (holds the Plaid access token)
- `accounts` — bank/credit/investment accounts within an item
- `transactions` — individual transactions
- `sync_cursors` — Plaid sync cursor per item
- `category_overrides` — user-set category for a transaction (overrides Plaid)
- `category_rules` — pattern-based auto-categorization rules
- `transaction_notes` — free-text notes attached to transactions
- `transaction_tags` — many-to-many tags on transactions
- `saved_views` — named transaction filter presets
- `budgets` — monthly spending limits per category

Amount convention follows Plaid's raw values: **positive = debit (money out),
negative = credit (money in)**.

## Category resolution

Effective category priority (highest wins):

1. Manual override set by the user on the transaction detail page
2. Rule match (highest-priority rule wins; rules auto-apply after sync)
3. Plaid's `personal_finance_category`

`INTERNAL TRANSFER` (written by the transfer detector) and `CREDIT PAYMENT`
are treated as internal noise and excluded from spend/income summaries.

## Architecture

`main.py` → `link_server.py` or `sync.py` → `plaid_client.py` + `db.py`  
`main.py` → `web_server.py` → `analytics.py` + `db.py`

- `plaid_client.py` — wraps the plaid-python SDK; `sync_transactions()` is a
  generator over cursor pages.
- `db.py` — raw psycopg2 with a `ThreadedConnectionPool`; all writes are
  upserts.
- `sync.py` — drives the cursor loop, persists progress per-page, and after
  each full sync auto-applies category rules, then runs internal transfer
  detection.
- `link_server.py` — short-lived Flask server that hosts Plaid Link during
  the connect flow, then shuts itself down.
- `analytics.py` — all query and report logic: transaction search, spend
  summaries, budget status, category rule matching, and internal transfer
  detection.
- `web_server.py` — persistent Flask dashboard; routes map to analytics
  queries and template renders.
- `main.py` — argparse CLI entrypoint.

See [CLAUDE.md](CLAUDE.md) for deeper notes on each module.

## Development

Tests, linter, and formatter run in CI (GitHub Actions) on every push and PR:

```bash
uv run pytest            # unit tests (all DB access is mocked; a conftest
                         # guard fails any test that tries a real connection)
uv run ruff check .      # lint
uv run ruff format --check .
```

## Roadmap

### Near term

- [ ] **Recurring transaction detection** — surface subscriptions, bills, and
      paychecks automatically.
- [ ] **Net worth tracking** — historical balances per account.

### Longer term

- [ ] **Goals** — savings targets, debt paydown projections.
- [ ] **Subscription management** — flag subscriptions, surface price changes.
- [ ] **Investment account drill-down** — holdings, cost basis, allocation.
- [ ] **Multi-user / household mode** — shared accounts with per-user visibility.
- [ ] **Import from CSV / OFX / QIF** — for accounts Plaid can't reach and
      historical backfill.
- [ ] **Export everything** — your data, your database, easy to leave.
