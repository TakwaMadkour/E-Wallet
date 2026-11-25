from wallet_app.result import Result
from wallet_app.money import to_minor_units
from wallet_app.repositories.wallet_repository import WalletRepository
from wallet_app.repositories.ledger_repository import LedgerRepository
from wallet_app.repositories.transaction_repository import TransactionRepository
from wallet_app.services.common import request_fingerprint, replay_or_conflict
from wallet_app.security_context import authorize_wallet
from wallet_app.services.accounting_service import AccountingService
from wallet_app.services.notification_service import NotificationService
from wallet_app.services.policy_service import PolicyService
from wallet_app.services.audit_service import AuditService
from wallet_app.observability import log_event, new_correlation_id

class TransferService:
    def __init__(self, db):
        self.db = db
        self.wallets = WalletRepository()
        self.ledger = LedgerRepository()
        self.transactions = TransactionRepository()

    def transfer(self, sender_wallet_id, receiver_wallet_id, amount, idempotency_key, principal=None):
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
        new_correlation_id()
        conn = self.db.transaction()
        try:
            # BEGIN IMMEDIATE serializes SQLite writers before these balance checks.
            sender = self.wallets.get(conn, sender_wallet_id)
            receiver = self.wallets.get(conn, receiver_wallet_id)
            if not sender or not receiver:
                conn.rollback()
                return Result.fail("WALLET_NOT_FOUND", "Sender or receiver wallet does not exist.")
            if not authorize_wallet(conn, sender_wallet_id, principal):
                conn.rollback(); return Result.fail("FORBIDDEN", "You are not authorized to transfer from this wallet.")
            if sender["owner_status"] != "active" or receiver["owner_status"] != "active":
                conn.rollback()
                return Result.fail("ACCOUNT_INACTIVE", "Both accounts must be active.")
            replay = replay_or_conflict(self.transactions, conn, idempotency_key, fingerprint)
            if replay:
                conn.commit()
                if replay["conflict"]: return Result.fail("IDEMPOTENCY_CONFLICT", "This key was already used for a different request.")
                return Result.ok("REPLAYED", "Previously completed transfer returned.", {"transaction_id": replay["transaction"]["transaction_id"]})
            policy_error=PolicyService.validate(conn,"transfer",minor,sender_wallet_id)
            if policy_error: conn.rollback(); return Result.fail(*policy_error)
            fee=PolicyService.transfer_fee(conn,minor)
            if fee < 0 or minor + fee > 9_000_000_000_000_000_000:
                conn.rollback(); return Result.fail("INVALID_FEE_POLICY", "Configured fee exceeds the supported monetary range.")
            total=minor+fee
            sender_balance = self.wallets.balance(conn, sender_wallet_id)
            if sender_balance < total:
                conn.rollback()
                return Result.fail("INSUFFICIENT_FUNDS", "Insufficient wallet balance.",
                                   {"balance_minor": sender_balance, "required_minor": total})

            tx_id = self.transactions.create(
                conn, idempotency_key, fingerprint, "transfer", minor,
                f"Transfer from wallet {sender_wallet_id} to {receiver_wallet_id}"
            )
            self.ledger.add(conn, tx_id, sender_wallet_id, -total)
            self.ledger.add(conn, tx_id, receiver_wallet_id, minor)
            journal=[{"account_code":"wallet_liability","account_id":sender_wallet_id,"debit":minor},{"account_code":"wallet_liability","account_id":receiver_wallet_id,"credit":minor}]
            if fee:
                journal.extend([{"account_code":"wallet_liability","account_id":sender_wallet_id,"debit":fee},{"account_code":"fee_revenue","account_id":sender_wallet_id,"credit":fee}])
            AccountingService.post(conn,tx_id,journal)
            NotificationService.enqueue(conn,sender["user_id"],"TRANSFER_SENT","Transfer sent",f"You sent {minor} minor units; fee {fee}.",tx_id)
            NotificationService.enqueue(conn,receiver["user_id"],"TRANSFER_RECEIVED","Money received",f"You received {minor} minor units.",tx_id)
            AuditService.record(conn,getattr(principal,"user_id",None),"TRANSFER_POSTED","transaction",tx_id,new_value=str(minor),reason=f"fee_minor={fee}")
            sender_after = self.wallets.balance(conn, sender_wallet_id)
            receiver_after = self.wallets.balance(conn, receiver_wallet_id)
            conn.commit()
            log_event("transfer_completed", transaction_id=tx_id, wallet_id=sender_wallet_id, operation="transfer", result_code="TRANSFER_COMPLETED")
            return Result.ok("TRANSFER_COMPLETED", "Transfer completed.",
                             {"transaction_id": tx_id, "amount_minor": minor, "fee_minor": fee,
                              "sender_balance_minor": sender_after,
                              "receiver_balance_minor": receiver_after})
        except Exception:
            import logging; logging.getLogger("ewallet").exception("financial operation failed")
            conn.rollback()
            return Result.fail("DATABASE_ERROR", "Transfer failed; no changes were committed.")
        finally:
            conn.close()
