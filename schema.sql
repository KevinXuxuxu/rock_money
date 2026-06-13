-- Plaid finance tracker schema

CREATE TABLE IF NOT EXISTS items (
    item_id          TEXT PRIMARY KEY,
    access_token     TEXT NOT NULL UNIQUE,
    institution_id   TEXT,
    institution_name TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sync_cursors (
    item_id        TEXT PRIMARY KEY REFERENCES items(item_id) ON DELETE CASCADE,
    cursor         TEXT,          -- NULL means start from beginning
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id    TEXT PRIMARY KEY,
    item_id       TEXT NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    official_name TEXT,
    type          TEXT NOT NULL,
    subtype       TEXT,
    mask          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Positive amount = debit (money out). Negative amount = credit (money in).
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id               TEXT PRIMARY KEY,
    account_id                   TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    amount                       NUMERIC(14, 4) NOT NULL,
    iso_currency_code            TEXT,
    date                         DATE NOT NULL,
    authorized_date              DATE,
    datetime                     TIMESTAMPTZ,
    authorized_datetime          TIMESTAMPTZ,
    name                         TEXT NOT NULL,
    merchant_name                TEXT,
    payment_channel              TEXT,
    pending                      BOOLEAN NOT NULL DEFAULT FALSE,
    pending_transaction_id       TEXT,
    category                     TEXT[],
    personal_finance_category    TEXT,
    personal_finance_category_confidence TEXT,
    location                     JSONB,
    counterparties               JSONB,
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transactions_account_id ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_pending ON transactions(pending);
CREATE INDEX IF NOT EXISTS idx_accounts_item_id ON accounts(item_id);

-- ── User category overrides and rules ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS category_overrides (
    transaction_id TEXT PRIMARY KEY REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    category       TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS category_rules (
    id            SERIAL PRIMARY KEY,
    match_pattern TEXT NOT NULL,
    match_field   TEXT NOT NULL DEFAULT 'merchant_name',
    category      TEXT NOT NULL,
    priority      INT NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_category_overrides_category ON category_overrides(category);

-- ── Budgets ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS budgets (
    category   TEXT    PRIMARY KEY,
    monthly_limit NUMERIC(14, 4) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Transaction annotations ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS transaction_notes (
    transaction_id TEXT PRIMARY KEY REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    note           TEXT NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transaction_tags (
    transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    tag            TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (transaction_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_transaction_tags_tag ON transaction_tags(tag);

-- ── Saved search views ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS saved_views (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    filters    JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
