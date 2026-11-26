# Electronic Wallet (Python + SQLite)

A robust, production-grade electronic wallet and core banking ledger system built in Python and SQLite. This system implements strict double-entry bookkeeping, immutable audit trails, idempotent financial operations, and state-machine-driven transaction workflows.
Designed with enterprise-level financial integrity in mind, it handles everything from peer-to-peer transfers and policy enforcement to automated reconciliation and CSV statement generation.

## Key Features

# Core Banking & Accounting

Double-Entry Bookkeeping: Every transaction posts balanced journal_lines alongside the wallet ledger_entries (sub-ledger).
Immutable Ledger: SQLite BEFORE UPDATE/DELETE triggers strictly forbid the modification or deletion of posted financial records, audit logs, and state events.
Minor Units Precision: All monetary values are stored and calculated in integer minor units (piastres) using Python's Decimal to completely eliminate floating-point rounding errors.
Automated Reconciliation: Built-in engine to verify that the wallet sub-ledger perfectly matches the general journal control accounts and that all journal entries are strictly balanced.
Trial Balance: Admin tool to generate a real-time trial balance across all accounting codes.

# Transactions & Transfers

Deposits & Withdrawals: Atomic posting of funds with strict policy validation.
Peer-to-Peer (P2P) Transfers: Secure wallet-to-wallet transfers with automatic fee calculation.
Configurable Fee Engine: Supports both basis points (BPS) and fixed minor-unit fees for transfers.
Transaction Reversals: Admin-only reversal engine that creates offsetting ledger/journal entries, enforces recipient fund availability, and updates workflow states.

# Security & Risk Management

Policy Engine: Enforces configurable business rules, including maximum single-transaction limits, daily transfer limits, and daily withdrawal limits.
Idempotency & Replay Protection: Every financial operation requires an idempotency key and request fingerprint, preventing duplicate charges or conflicting retries.
Role-Based Access Control (RBAC): Strict separation of customer and admin roles, enforced via Principal context and authorization guards.
Secure Authentication: Passwords are hashed using PBKDF2-SHA256 with 310,000 iterations and salt.
Input Validation: Strict normalization for Emails and Egyptian Phone Numbers (E.164 format).

# State Machine & Workflows

Transaction Intents: Supports asynchronous, multi-step transaction lifecycles (pending → processing → completed/failed) for external payment gateway integrations.
Workflow Guards: Database-level triggers enforce valid state transitions, preventing illegal state jumps.

# Reporting & Observability

Wallet Statements: Generate detailed customer statements with opening/closing balances, running balances, and categorized totals (deposits, withdrawals, incoming/outgoing transfers, fees).
CSV Exports: Export customer statements and admin transaction reports to CSV.
Structured Logging: JSON-formatted logging with correlation_id tracking across the entire lifecycle of a request.
Comprehensive Audit Trail: Every state change, admin action, and profile update is immutably logged with actor IDs, old/new values, and reasons.

## Architecture & Design Patterns

The project is structured using clean, layered architecture principles:
Database Layer (database.py): Manages SQLite connections, schema initialization, and enforces the Unit of Work pattern by passing the conn object through the stack to ensure atomic transactions.
Repository Layer (_\_repository.py): Handles raw SQL queries and data mapping, completely isolated from business logic.
Service Layer (_\_service.py): Orchestrates business rules, calls repositories, and manages transaction boundaries.
Result Pattern (result.py): Services return a standardized Result object (Result.ok / Result.fail), ensuring consistent error handling and data propagation without relying on exceptions for control flow.
Security Context (security_context.py): Uses a Principal dataclass to pass authenticated user context securely through the service layer.

## Database Schema Highlights

The SQLite schema is heavily constrained to guarantee financial integrity:
transactions: Immutable record of financial events.
ledger_entries: Wallet sub-ledger (tracks actual wallet balances).
journal_lines: General ledger (tracks double-entry accounting codes like wallet_liability, fee_revenue, cash).
transaction_workflows & transaction_intents: State machines for async processing.
transaction_policies: Dynamic configuration for limits and fees.
audit_logs & reconciliation_runs: Immutable compliance and integrity tracking.

## Getting Started

Prerequisites
Python 3.8+
Required packages: email_validator, phonenumbers

# Installation

```bash
pip install email_validator phonenumbers
```

## Run

From this directory:

```bash
python main.py
```

First-Time Setup
On the first run, the system will detect the absence of an administrator and prompt you to bootstrap the initial Admin Account. Afterward, you can register customers via the CLI. The SQLite database is created as `wallet.db`.

## Run tests

```bash
python -m unittest discover -s tests -v
```

## Important design notes

- `wallets` deliberately has no mutable balance column. The balance is `SUM(ledger_entries.amount_minor)`.
- Amounts are stored as integer piastres (100 piastres = 1 EGP).
- Reusing an idempotency key with the same payload returns the original operation; using it with a different payload is rejected.
- Financial writes use SQLite `BEGIN IMMEDIATE`, which serializes competing writers. SQLite does not provide `SELECT ... FOR UPDATE` row locks.
- Database triggers prevent ordinary UPDATE/DELETE statements. This is an application-level safeguard, not protection against a database administrator who can alter the database file or schema.

## Project structure

```text
wallet_app/
├── main.py                 # Entry point & CLI bootstrapping
├── console.py              # CLI Menus (Customer & Admin)
├── database.py             # SQLite connection, schema, and triggers
├── money.py                # Decimal/Minor units conversion utilities
├── result.py               # Standardized Result pattern
├── observability.py        # JSON logging & correlation IDs
├── security.py             # PBKDF2 password hashing
├── security_context.py     # Principal & Authorization guards
├── validation.py           # Email & Phone normalization
├── repositories/           # Data Access Layer
│   ├── user_repository.py
│   ├── wallet_repository.py
│   ├── transaction_repository.py
│   └── ledger_repository.py
└── services/               # Business Logic Layer
    ├── auth_service.py
    ├── wallet_service.py
    ├── transfer_service.py
    ├── accounting_service.py
    ├── policy_service.py
    ├── reversal_service.py
    ├── reconciliation_service.py
    ├── state_machine_service.py
    ├── statement_service.py
    ├── notification_service.py
    ├── audit_service.py
    ├── admin_service.py
    └── common.py           # Idempotency & fingerprinting
```

## Design Notes

Currency: The system is currently hardcoded for EGP (Egyptian Pound), where 1 EGP = 100 minor units (piastres).
Concurrency: SQLite BEGIN IMMEDIATE is used to serialize writers and prevent race conditions during balance checks and ledger postings.
Immutability: If you need to correct a posted transaction, you must use the ReversalService to post an offsetting transaction. Direct database edits are blocked by triggers.

## Idempotency note

The console generates a fresh key for each new user-initiated operation. A networked API should create the key once when the user starts an operation and reuse that same key for every retry. Never generate a new key for a retry.
