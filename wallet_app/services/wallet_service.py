from wallet_app.result import Result
from wallet_app.money import to_minor_units
from wallet_app.repositories.user_repository import UserRepository
from wallet_app.repositories.wallet_repository import WalletRepository
from wallet_app.repositories.ledger_repository import LedgerRepository
from wallet_app.repositories.transaction_repository import TransactionRepository
from wallet_app.services.common import request_fingerprint, replay_or_conflict, row_dict

class WalletService:
    def __init__(self, db):
        self.db = db
        self.users = UserRepository()
        self.wallets = WalletRepository()
        self.ledger = LedgerRepository()
        self.transactions = TransactionRepository()

    def create_wallet(self, user_id):
        conn = self.db.transaction()
        try:
            user = self.users.get_by_id(conn, user_id)
            if not user or user["role"] != "customer":
                conn.rollback()
                return Result.fail("USER_NOT_FOUND", "Customer does not exist.")
            existing = self.wallets.get_by_user(conn, user_id)
            if existing:
                conn.rollback()
                return Result.fail("WALLET_EXISTS", "Customer already has a wallet.")
            wallet_id = self.wallets.create(conn, user_id)
            conn.commit()
            return Result.ok("WALLET_CREATED", "Wallet created.", {"wallet_id": wallet_id})
        except Exception:
            conn.rollback()
            return Result.fail("DATABASE_ERROR", "Could not create wallet.")
        finally:
            conn.close()

    def get_wallet(self, wallet_id):
        with self.db.connect() as conn:
            wallet = self.wallets.get(conn, wallet_id)
            if not wallet:
                return Result.fail("WALLET_NOT_FOUND", "Wallet does not exist.")
            data = row_dict(wallet)
            data["balance_minor"] = self.wallets.balance(conn, wallet_id)
            return Result.ok("WALLET_FOUND", "Wallet retrieved.", data)

    def get_balance(self, wallet_id):
        result = self.get_wallet(wallet_id)
        if not result.success:
            return result
        return Result.ok("BALANCE_FOUND", "Balance retrieved.",
                         {"wallet_id": wallet_id,
                          "balance_minor": result.data["balance_minor"]})

    def deposit(self, wallet_id, amount, idempotency_key):
        return self._post_single(wallet_id, amount, idempotency_key, "deposit")

    def withdraw(self, wallet_id, amount, idempotency_key):
        return self._post_single(wallet_id, amount, idempotency_key, "withdrawal")

    def _post_single(self, wallet_id, amount, key, kind):
        if not key or not str(key).strip():
            return Result.fail("IDEMPOTENCY_KEY_REQUIRED", "An idempotency key is required.")
        try:
            minor = to_minor_units(amount)
        except ValueError as exc:
            return Result.fail("INVALID_AMOUNT", str(exc))

        fingerprint = request_fingerprint(kind, [wallet_id], minor)
        conn = self.db.transaction()
        try:
            replay = replay_or_conflict(self.transactions, conn, key, fingerprint)
            if replay:
                conn.commit()
                if replay["conflict"]:
                    return Result.fail("IDEMPOTENCY_CONFLICT",
                                       "This key was already used for a different request.")
                return Result.ok("REPLAYED", "Previously completed request returned.",
                                 self._transaction_result(conn, replay["transaction"], wallet_id))

            wallet = self.wallets.get(conn, wallet_id)
            if not wallet:
                conn.rollback()
                return Result.fail("WALLET_NOT_FOUND", "Wallet does not exist.")
            if wallet["owner_status"] != "active":
                conn.rollback()
                return Result.fail("ACCOUNT_INACTIVE", "This account is inactive.")

            if kind == "withdrawal":
                balance = self.wallets.balance(conn, wallet_id)
                if balance < minor:
                    conn.rollback()
                    return Result.fail("INSUFFICIENT_FUNDS", "Insufficient wallet balance.",
                                       {"balance_minor": balance})

            tx_id = self.transactions.create(
                conn, key, fingerprint, kind, minor, f"{kind.title()} via console"
            )
            signed_amount = minor if kind == "deposit" else -minor
            self.ledger.add(conn, tx_id, wallet_id, signed_amount)
            balance_after = self.wallets.balance(conn, wallet_id)
            conn.commit()
            return Result.ok("TRANSACTION_COMPLETED", f"{kind.title()} completed.",
                             {"transaction_id": tx_id, "wallet_id": wallet_id,
                              "amount_minor": minor, "balance_minor": balance_after})
        except Exception:
            conn.rollback()
            return Result.fail("DATABASE_ERROR", "Financial operation failed; no changes were committed.")
        finally:
            conn.close()

    def _transaction_result(self, conn, tx, wallet_id):
        return {"transaction_id": tx["transaction_id"], "wallet_id": wallet_id,
                "amount_minor": tx["amount_minor"],
                "balance_minor": self.wallets.balance(conn, wallet_id)}

    def history(self, wallet_id, limit=100):
        with self.db.connect() as conn:
            if not self.wallets.get(conn, wallet_id):
                return Result.fail("WALLET_NOT_FOUND", "Wallet does not exist.")
            rows = self.ledger.history(conn, wallet_id, limit)
            return Result.ok("HISTORY_FOUND", "Ledger history retrieved.",
                             [dict(row) for row in rows])
