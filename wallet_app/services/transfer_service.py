from wallet_app.result import Result
from wallet_app.money import to_minor_units
from wallet_app.repositories.wallet_repository import WalletRepository
from wallet_app.repositories.ledger_repository import LedgerRepository
from wallet_app.repositories.transaction_repository import TransactionRepository
from wallet_app.services.common import request_fingerprint, replay_or_conflict

class TransferService:
    def __init__(self, db):
        self.db = db
        self.wallets = WalletRepository()
        self.ledger = LedgerRepository()
        self.transactions = TransactionRepository()

    def transfer(self, sender_wallet_id, receiver_wallet_id, amount, idempotency_key):
        if not idempotency_key or not str(idempotency_key).strip():
            return Result.fail("IDEMPOTENCY_KEY_REQUIRED", "An idempotency key is required.")
        try:
            minor = to_minor_units(amount)
        except ValueError as exc:
            return Result.fail("INVALID_AMOUNT", str(exc))
        if sender_wallet_id == receiver_wallet_id:
            return Result.fail("SAME_WALLET", "You cannot transfer to your own wallet.")

        fingerprint = request_fingerprint(
            "transfer", [sender_wallet_id, receiver_wallet_id], minor
        )
        conn = self.db.transaction()
        try:
            replay = replay_or_conflict(self.transactions, conn, idempotency_key, fingerprint)
            if replay:
                conn.commit()
                if replay["conflict"]:
                    return Result.fail("IDEMPOTENCY_CONFLICT",
                                       "This key was already used for a different request.")
                return Result.ok("REPLAYED", "Previously completed transfer returned.",
                                 {"transaction_id": replay["transaction"]["transaction_id"]})

            # BEGIN IMMEDIATE serializes SQLite writers before these balance checks.
            sender = self.wallets.get(conn, sender_wallet_id)
            receiver = self.wallets.get(conn, receiver_wallet_id)
            if not sender or not receiver:
                conn.rollback()
                return Result.fail("WALLET_NOT_FOUND", "Sender or receiver wallet does not exist.")
            if sender["owner_status"] != "active" or receiver["owner_status"] != "active":
                conn.rollback()
                return Result.fail("ACCOUNT_INACTIVE", "Both accounts must be active.")
            sender_balance = self.wallets.balance(conn, sender_wallet_id)
            if sender_balance < minor:
                conn.rollback()
                return Result.fail("INSUFFICIENT_FUNDS", "Insufficient wallet balance.",
                                   {"balance_minor": sender_balance})

            tx_id = self.transactions.create(
                conn, idempotency_key, fingerprint, "transfer", minor,
                f"Transfer from wallet {sender_wallet_id} to {receiver_wallet_id}"
            )
            self.ledger.add(conn, tx_id, sender_wallet_id, -minor)
            self.ledger.add(conn, tx_id, receiver_wallet_id, minor)
            sender_after = self.wallets.balance(conn, sender_wallet_id)
            receiver_after = self.wallets.balance(conn, receiver_wallet_id)
            conn.commit()
            return Result.ok("TRANSFER_COMPLETED", "Transfer completed.",
                             {"transaction_id": tx_id, "amount_minor": minor,
                              "sender_balance_minor": sender_after,
                              "receiver_balance_minor": receiver_after})
        except Exception:
            conn.rollback()
            return Result.fail("DATABASE_ERROR", "Transfer failed; no changes were committed.")
        finally:
            conn.close()
