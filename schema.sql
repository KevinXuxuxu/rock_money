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
