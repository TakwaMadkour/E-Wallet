import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    phone TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('customer', 'admin')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'inactive')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wallets (
    wallet_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(user_id),
    currency TEXT NOT NULL DEFAULT 'EGP' CHECK(currency = 'EGP'),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL,
    transaction_type TEXT NOT NULL CHECK(transaction_type IN ('deposit','withdrawal','transfer','reversal')),
    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
    status TEXT NOT NULL CHECK(status IN ('completed')),
    description TEXT,
    reversal_of_transaction_id INTEGER REFERENCES transactions(transaction_id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL REFERENCES transactions(transaction_id),
    wallet_id INTEGER NOT NULL REFERENCES wallets(wallet_id),
    amount_minor INTEGER NOT NULL CHECK(amount_minor != 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ledger_wallet ON ledger_entries(wallet_id);
CREATE INDEX IF NOT EXISTS idx_ledger_transaction ON ledger_entries(transaction_id);

-- Protect posted financial history against ordinary UPDATE/DELETE statements.
CREATE TRIGGER IF NOT EXISTS ledger_no_update
BEFORE UPDATE ON ledger_entries BEGIN
    SELECT RAISE(ABORT, 'Ledger entries are immutable');
END;
CREATE TRIGGER IF NOT EXISTS ledger_no_delete
BEFORE DELETE ON ledger_entries BEGIN
    SELECT RAISE(ABORT, 'Ledger entries are immutable');
END;
CREATE TRIGGER IF NOT EXISTS transactions_no_update
BEFORE UPDATE ON transactions BEGIN
    SELECT RAISE(ABORT, 'Transactions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS transactions_no_delete
BEFORE DELETE ON transactions BEGIN
    SELECT RAISE(ABORT, 'Transactions are immutable');
END;
"""

class Database:
    def __init__(self, path="wallet.db"):
        self.path = str(Path(path))
        self.initialize()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    def initialize(self):
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def transaction(self):
        """Return a connection with an immediate write transaction started."""
        conn = self.connect()
        conn.execute("BEGIN IMMEDIATE")
        return conn
