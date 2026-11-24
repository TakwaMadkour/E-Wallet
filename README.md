# Electronic Wallet (Python + SQLite)

A console-based educational wallet system with a ledger-first design.

## Features
- Customer registration and login; initial admin setup on first run
- One EGP wallet per customer
- Simulated deposits and withdrawals
- Wallet-to-wallet transfers
- Append-only ledger and transaction records
- Integer piastres for exact money arithmetic
- Idempotency keys for financial requests
- SQLite `BEGIN IMMEDIATE` transactions to serialize writers
- Structured service results (`Result`) instead of printing from services
- Admin customer management and transaction/ledger inspection

## Requirements
- Python 3.10+
- No third-party packages

## Run
From this directory:

```bash
python main.py
```

On first run, create the initial administrator when prompted. The SQLite database is created as `wallet.db`.

## Run tests

```bash
python -m unittest discover -s tests -v
```

## Important design notes
- `wallets` deliberately has no mutable balance column. The balance is `SUM(ledger_entries.amount_minor)`.
- Amounts are stored as integer piastres (100 piastres = 1 EGP).
- Every successful financial request creates one immutable transaction. Transfers create two ledger entries in the same database transaction.
- Reusing an idempotency key with the same payload returns the original operation; using it with a different payload is rejected.
- Financial writes use SQLite `BEGIN IMMEDIATE`, which serializes competing writers. SQLite does not provide `SELECT ... FOR UPDATE` row locks.
- Database triggers prevent ordinary UPDATE/DELETE statements against transactions and ledger entries. This is an application-level safeguard, not protection against a database administrator who can alter the database file or schema.
- This is an educational simulation, not production-ready banking software. Production systems need stronger operational security, authorization controls, monitoring, reconciliation, backup/recovery, and external payment-provider integration.

## Project structure
```text
wallet_app/
  database.py
  result.py
  money.py
  security.py
  console.py
  repositories/
  services/
main.py
tests/
```

## Idempotency note
The console generates a fresh key for each new user-initiated operation. A networked API should create the key once when the user starts an operation and reuse that same key for every retry. Never generate a new key for a retry.
