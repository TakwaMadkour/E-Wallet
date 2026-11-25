import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
 user_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
 email TEXT NOT NULL COLLATE NOCASE UNIQUE, phone TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('customer','admin')),
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive')),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS wallets (
 wallet_id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL UNIQUE REFERENCES users(user_id),
 currency TEXT NOT NULL DEFAULT 'EGP' CHECK(currency='EGP'),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS transactions (
 transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
 idempotency_key TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL,
 transaction_type TEXT NOT NULL CHECK(transaction_type IN ('deposit','withdrawal','transfer','reversal')),
 amount_minor INTEGER NOT NULL CHECK(amount_minor>0),
 status TEXT NOT NULL CHECK(status IN ('completed')),
 description TEXT, reversal_of_transaction_id INTEGER REFERENCES transactions(transaction_id),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ledger_entries (
 entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
 transaction_id INTEGER NOT NULL REFERENCES transactions(transaction_id),
 wallet_id INTEGER NOT NULL REFERENCES wallets(wallet_id),
 amount_minor INTEGER NOT NULL CHECK(amount_minor!=0),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ledger_wallet ON ledger_entries(wallet_id);
CREATE INDEX IF NOT EXISTS idx_ledger_transaction ON ledger_entries(transaction_id);
CREATE TABLE IF NOT EXISTS journal_lines (
 line_id INTEGER PRIMARY KEY AUTOINCREMENT,
 transaction_id INTEGER NOT NULL REFERENCES transactions(transaction_id),
 account_code TEXT NOT NULL,
 account_id INTEGER,
 debit_minor INTEGER NOT NULL DEFAULT 0 CHECK(debit_minor>=0),
 credit_minor INTEGER NOT NULL DEFAULT 0 CHECK(credit_minor>=0),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CHECK ((debit_minor=0 AND credit_minor>0) OR (credit_minor=0 AND debit_minor>0))
);
CREATE INDEX IF NOT EXISTS idx_journal_transaction ON journal_lines(transaction_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_reversal_per_transaction ON transactions(reversal_of_transaction_id) WHERE reversal_of_transaction_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS transaction_workflows (
 transaction_id INTEGER PRIMARY KEY REFERENCES transactions(transaction_id),
 state TEXT NOT NULL CHECK(state IN ('pending','processing','completed','failed','cancelled','reversed')),
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS transaction_intents (
 intent_id INTEGER PRIMARY KEY AUTOINCREMENT,
 idempotency_key TEXT NOT NULL UNIQUE,
 user_id INTEGER NOT NULL REFERENCES users(user_id),
 wallet_id INTEGER NOT NULL REFERENCES wallets(wallet_id),
 counterparty_wallet_id INTEGER REFERENCES wallets(wallet_id),
 operation TEXT NOT NULL CHECK(operation IN ('deposit','withdrawal','transfer')),
 amount_minor INTEGER NOT NULL CHECK(amount_minor>0),
 state TEXT NOT NULL CHECK(state IN ('pending','processing','completed','failed','cancelled')),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS transaction_intent_events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 intent_id INTEGER NOT NULL REFERENCES transaction_intents(intent_id),
 old_state TEXT, new_state TEXT NOT NULL,
 actor_user_id INTEGER REFERENCES users(user_id), reason TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS transaction_state_events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 transaction_id INTEGER NOT NULL REFERENCES transactions(transaction_id),
 old_state TEXT, new_state TEXT NOT NULL, actor_user_id INTEGER REFERENCES users(user_id),
 reason TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS transaction_policies (
 policy_key TEXT PRIMARY KEY, policy_value INTEGER NOT NULL CHECK(policy_value>=0),
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT OR IGNORE INTO transaction_policies(policy_key,policy_value) VALUES
 ('max_single_minor',100000000),('daily_transfer_minor',200000000),
 ('daily_withdrawal_minor',50000000),('transfer_fee_bps',0),('transfer_fee_fixed_minor',0);
CREATE TABLE IF NOT EXISTS audit_logs (
 audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
 actor_user_id INTEGER REFERENCES users(user_id), action TEXT NOT NULL,
 entity_type TEXT NOT NULL, entity_id TEXT, old_value TEXT, new_value TEXT,
 reason TEXT, correlation_id TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);
CREATE TABLE IF NOT EXISTS notifications (
 notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(user_id), notification_type TEXT NOT NULL,
 title TEXT NOT NULL, message TEXT NOT NULL, transaction_id INTEGER REFERENCES transactions(transaction_id),
 is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0,1)),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id,is_read,created_at);
CREATE TABLE IF NOT EXISTS reconciliation_runs (
 run_id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL,
 discrepancies TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger_entries BEGIN SELECT RAISE(ABORT,'Ledger entries are immutable'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger_entries BEGIN SELECT RAISE(ABORT,'Ledger entries are immutable'); END;
CREATE TRIGGER IF NOT EXISTS transactions_no_update BEFORE UPDATE ON transactions BEGIN SELECT RAISE(ABORT,'Transactions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS transactions_no_delete BEFORE DELETE ON transactions BEGIN SELECT RAISE(ABORT,'Transactions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal_lines BEGIN SELECT RAISE(ABORT,'Journal lines are immutable'); END;
CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal_lines BEGIN SELECT RAISE(ABORT,'Journal lines are immutable'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_logs BEGIN SELECT RAISE(ABORT,'Audit logs are immutable'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_logs BEGIN SELECT RAISE(ABORT,'Audit logs are immutable'); END;
CREATE TRIGGER IF NOT EXISTS tx_state_events_no_update BEFORE UPDATE ON transaction_state_events BEGIN SELECT RAISE(ABORT,'Transaction state events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS tx_state_events_no_delete BEFORE DELETE ON transaction_state_events BEGIN SELECT RAISE(ABORT,'Transaction state events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS intent_events_no_update BEFORE UPDATE ON transaction_intent_events BEGIN SELECT RAISE(ABORT,'Intent state events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS intent_events_no_delete BEFORE DELETE ON transaction_intent_events BEGIN SELECT RAISE(ABORT,'Intent state events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS intent_payload_no_update BEFORE UPDATE OF idempotency_key,user_id,wallet_id,counterparty_wallet_id,operation,amount_minor ON transaction_intents BEGIN SELECT RAISE(ABORT,'Transaction intent payload is immutable'); END;
CREATE TRIGGER IF NOT EXISTS intent_state_transition_guard BEFORE UPDATE OF state ON transaction_intents
WHEN NOT ((OLD.state='pending' AND NEW.state IN ('processing','failed','cancelled')) OR (OLD.state='processing' AND NEW.state IN ('completed','failed')))
BEGIN SELECT RAISE(ABORT,'Invalid transaction intent state transition'); END;
CREATE TRIGGER IF NOT EXISTS workflow_state_transition_guard BEFORE UPDATE OF state ON transaction_workflows
WHEN NOT ((OLD.state='pending' AND NEW.state IN ('processing','failed','cancelled')) OR (OLD.state='processing' AND NEW.state IN ('completed','failed')) OR (OLD.state='completed' AND NEW.state='reversed'))
BEGIN SELECT RAISE(ABORT,'Invalid transaction workflow state transition'); END;
"""

class ClosingConnection(sqlite3.Connection):
    """SQLite context manager that also closes the connection on exit."""
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Database:
    def __init__(self, path="wallet.db"):
        self.path = str(Path(path))
        self.initialize()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    def initialize(self):
        conn = self.connect()
        try:
            conn.executescript(SCHEMA)
            # Lightweight additive migration for databases created by earlier project versions.
            conn.execute("CREATE TABLE IF NOT EXISTS journal_lines (line_id INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id INTEGER NOT NULL REFERENCES transactions(transaction_id), account_code TEXT NOT NULL, account_id INTEGER, debit_minor INTEGER NOT NULL DEFAULT 0 CHECK(debit_minor>=0), credit_minor INTEGER NOT NULL DEFAULT 0 CHECK(credit_minor>=0), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, CHECK ((debit_minor=0 AND credit_minor>0) OR (credit_minor=0 AND debit_minor>0)))")
            conn.execute("CREATE TABLE IF NOT EXISTS transaction_workflows (transaction_id INTEGER PRIMARY KEY REFERENCES transactions(transaction_id), state TEXT NOT NULL CHECK(state IN ('pending','processing','completed','failed','cancelled','reversed')), updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("CREATE TABLE IF NOT EXISTS transaction_intents (intent_id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE, user_id INTEGER NOT NULL REFERENCES users(user_id), wallet_id INTEGER NOT NULL REFERENCES wallets(wallet_id), counterparty_wallet_id INTEGER REFERENCES wallets(wallet_id), operation TEXT NOT NULL CHECK(operation IN ('deposit','withdrawal','transfer')), amount_minor INTEGER NOT NULL CHECK(amount_minor>0), state TEXT NOT NULL CHECK(state IN ('pending','processing','completed','failed','cancelled')), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("CREATE TABLE IF NOT EXISTS transaction_intent_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, intent_id INTEGER NOT NULL REFERENCES transaction_intents(intent_id), old_state TEXT, new_state TEXT NOT NULL, actor_user_id INTEGER REFERENCES users(user_id), reason TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("CREATE TABLE IF NOT EXISTS transaction_state_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id INTEGER NOT NULL REFERENCES transactions(transaction_id), old_state TEXT, new_state TEXT NOT NULL, actor_user_id INTEGER REFERENCES users(user_id), reason TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            for row in conn.execute("SELECT transaction_id FROM transactions WHERE transaction_id NOT IN (SELECT transaction_id FROM transaction_workflows)"):
                conn.execute("INSERT INTO transaction_workflows(transaction_id,state) VALUES(?,'completed')", (row[0],))
            # Backfill double-entry journal lines for transactions created before this upgrade.
            old_txs=conn.execute("SELECT transaction_id,transaction_type FROM transactions WHERE transaction_id NOT IN (SELECT DISTINCT transaction_id FROM journal_lines)").fetchall()
            for tx in old_txs:
                entries=conn.execute("SELECT wallet_id,amount_minor FROM ledger_entries WHERE transaction_id=?",(tx["transaction_id"],)).fetchall()
                lines=[]
                for entry in entries:
                    amount=int(entry["amount_minor"]); wid=int(entry["wallet_id"])
                    if amount>0: lines.append(("wallet_liability",wid,0,amount))
                    else: lines.append(("wallet_liability",wid,-amount,0))
                debit=sum(x[2] for x in lines); credit=sum(x[3] for x in lines)
                if debit>credit: lines.append(("opening_or_cash_clearing",None,0,debit-credit))
                elif credit>debit: lines.append(("opening_or_cash_clearing",None,credit-debit,0))
                for code,account_id,d,c in lines:
                    if d or c: conn.execute("INSERT INTO journal_lines(transaction_id,account_code,account_id,debit_minor,credit_minor) VALUES(?,?,?,?,?)",(tx["transaction_id"],code,account_id,d,c))
        finally:
            conn.close()

    def transaction(self):
        conn = self.connect()
        conn.execute("BEGIN IMMEDIATE")
        return conn
