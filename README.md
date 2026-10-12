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
- Cascading deletes: removing an item (via `remove-item` or the Accounts
  page) cleans up its accounts and transactions.

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
- **Dashboard** (`/`): current-month spent/income/net tiles, spend and
  income by category, a 6-month income-vs-spend summary, and the most recent
  transactions. Figures include pending transactions (shown in grey).
- **Accounts** (`/accounts`): per-account transaction counts and
  debit/credit totals, editable account labels, "Sync now" and "Link new
  account" buttons, and removing a linked institution (with confirm).
- **Transactions** (`/transactions`): full-text search (merchant, name,
  note), month/category/account filters, saved search views, a live total
  for the current filter, and inline category override right from the list —
  your current filters are preserved when you edit.
- **Transaction detail** (`/transactions/<id>`): override category, add a
  note, add/remove tags.
- **Reports** (`/reports`): month navigation with a "view all transactions
  for this month" link; money-flow Sankey diagram: income by account (with
  last-4 mask) and category → total → spending by category → which accounts
  the spending hit → grouped by account label. Unspent income shows as a
  green "Saved" flow, overspent months add a grey "Withdraw" inflow;
  investment contributions, internal transfers, and credit-card payments are
  excluded (Plotly, SRI-pinned). Spend- and income-by-category bar charts,
  a 6-month cash-flow table, and per-category budget progress (budgets are
  set via `budget-set`) — report categories link through to the filtered
  transactions list.
- **Rules** (`/rules`): create, delete, and apply rules, with search
  (pattern or category) and pagination — browsable even with hundreds of
  rules.
- Every page shows the last Plaid sync time — a relative phrase ("3 hours
  ago") within the last day, otherwise an absolute UTC time localised in the
  browser.

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

### CLI reference

Everything runs through `uv run python main.py <command>` (add `--help` for
per-command flags):

| Command | What it does |
| --- | --- |
| `init` | Create the database schema (safe to re-run) |
| `link` | Connect a bank via Plaid Link (`--port`, default 8765) |
| `sync` | Sync transactions for all linked institutions (`-q` for quiet) |
| `list-items` | Linked institutions and their last sync time |
| `remove-item <item_id>` | Revoke an institution and delete all its data (typed confirm) |
| `accounts` | Accounts with transaction counts |
| `list-txns` | Recent transactions; `--account` / `--category` / `--month` / `--pending` / `--search` filters |
| `search [query]` | Full-text search; `--month`, `--category`, `--limit` |
| `report-spend` | Spending by category for a month (`--month`) |
| `report-monthly` | Income vs spend per month (`--months`, default 12) |
| `categorize <txn_id> <category>` | Set a manual category override |
| `uncategorize <txn_id>` | Remove a manual category override |
| `rule-add --match <text> --category <cat> [--field] [--priority]` | Create a category rule (field: `merchant_name`, `name`, `personal_finance_category`) |
| `rule-list` / `rule-remove <id>` / `rule-apply [--dry-run]` | Manage rules; apply them to uncategorized transactions |
| `detect-transfers [--dry-run]` | Mark TRANSFER_IN/OUT pairs as INTERNAL TRANSFER |
| `budget-set <category> <amount>` | Set a monthly budget for a category |
| `budget-list` / `budget-delete <category>` | Manage budgets |
| `budget-status [--month]` | Budget vs actual spend for a month |
| `budget-alert [--month] [--threshold]` | Flag categories at/over a usage threshold (default 80%) |
| `note <txn_id> <text>` | Set a note (empty text clears it) |
| `tag-add <txn_id> <tag>` / `tag-remove <txn_id> <tag>` | Add/remove tags |
| `view-save <name> [--search] [--month] [--category]` | Save a named search view |
| `view-list` / `view-delete <name>` | Manage saved views |
| `web` | Web dashboard (`--port`, default 8123; `--debug`) |

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

1. Manual override set by the user (detail page or inline from the
   transactions list)
2. Rule match (highest-priority rule wins; rules auto-apply after sync)
3. Plaid's `personal_finance_category`

`INTERNAL TRANSFER` (written by the transfer detector), `CREDIT PAYMENT`, and
`INVESTMENT` are excluded from every spend/income aggregation — the dashboard
totals, the month-over-month cash flow, and the reports charts/Sankey all share
one exclusion list (`analytics.EXCLUDED_CATEGORIES`) so their numbers agree.
Investment contributions fold into the reports "Saved" surplus rather than
counting as spending.

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
