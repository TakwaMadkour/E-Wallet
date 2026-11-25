from wallet_app.result import Result
from wallet_app.money import to_minor_units
from wallet_app.repositories.user_repository import UserRepository
from wallet_app.repositories.wallet_repository import WalletRepository
from wallet_app.repositories.ledger_repository import LedgerRepository
from wallet_app.repositories.transaction_repository import TransactionRepository
from wallet_app.services.common import request_fingerprint, replay_or_conflict, row_dict
from wallet_app.security_context import authorize_wallet, Principal, require_admin
from wallet_app.services.accounting_service import AccountingService
from wallet_app.services.notification_service import NotificationService
from wallet_app.services.policy_service import PolicyService
from wallet_app.services.audit_service import AuditService
from wallet_app.observability import log_event, new_correlation_id


class WalletService:
    def __init__(self, db):
        self.db = db
        self.users = UserRepository()
        self.wallets = WalletRepository()
        self.ledger = LedgerRepository()
        self.transactions = TransactionRepository()

    def create_wallet(self, user_id, principal=None):
        if not require_admin(principal):
            return Result.fail("FORBIDDEN", "Administrator access required.")
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
            import logging
            logging.getLogger("ewallet").exception(
                "financial operation failed")
            conn.rollback()
            return Result.fail("DATABASE_ERROR", "Could not create wallet.")
        finally:
            conn.close()

    def get_wallet(self, wallet_id, principal=None):
        conn = self.db.connect()
        try:
            wallet = self.wallets.get(conn, wallet_id)

            if not wallet:
                return Result.fail("WALLET_NOT_FOUND", "Wallet does not exist.")
            if not authorize_wallet(conn, wallet_id, principal, allow_admin=True):
                return Result.fail("FORBIDDEN", "You are not authorized to access this wallet.")

            data = row_dict(wallet)
            data["balance_minor"] = self.wallets.balance(conn, wallet_id)

            return Result.ok("WALLET_FOUND", "Wallet retrieved.", data)
        finally:
            conn.close()

    def get_balance(self, wallet_id, principal=None):
        result = self.get_wallet(wallet_id, principal)
        if not result.success:
            return result
        return Result.ok("BALANCE_FOUND", "Balance retrieved.",
                         {"wallet_id": wallet_id,
                          "balance_minor": result.data["balance_minor"]})

    def deposit(self, wallet_id, amount, idempotency_key, principal=None):
        return self._post_single(wallet_id, amount, idempotency_key, "deposit", principal)

    def withdraw(self, wallet_id, amount, idempotency_key, principal=None):
        return self._post_single(wallet_id, amount, idempotency_key, "withdrawal", principal)

    def _post_single(self, wallet_id, amount, key, kind, principal=None):
        if not key or not str(key).strip():
            return Result.fail("IDEMPOTENCY_KEY_REQUIRED", "An idempotency key is required.")
        try:
            minor = to_minor_units(amount)
        except ValueError as exc:
            return Result.fail("INVALID_AMOUNT", str(exc))

        fingerprint = request_fingerprint(kind, [wallet_id], minor)
        new_correlation_id()
        conn = self.db.transaction()
        try:
            wallet = self.wallets.get(conn, wallet_id)
            if not wallet:
                conn.rollback()
                return Result.fail("WALLET_NOT_FOUND", "Wallet does not exist.")
            if not authorize_wallet(conn, wallet_id, principal):
                conn.rollback()
                return Result.fail("FORBIDDEN", "You are not authorized to operate this wallet.")
            if wallet["owner_status"] != "active":
                conn.rollback()
                return Result.fail("ACCOUNT_INACTIVE", "This account is inactive.")
            replay = replay_or_conflict(
                self.transactions, conn, key, fingerprint)
            if replay:
                conn.commit()
                if replay["conflict"]:
                    return Result.fail("IDEMPOTENCY_CONFLICT", "This key was already used for a different request.")
                return Result.ok("REPLAYED", "Previously completed request returned.", self._transaction_result(conn, replay["transaction"], wallet_id))

            policy_error = PolicyService.validate(conn, kind, minor, wallet_id)
            if policy_error:
                conn.rollback()
                return Result.fail(*policy_error)
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
            if kind == "deposit":
                AccountingService.post(conn, tx_id, [{"account_code": "cash", "debit": minor}, {
                                       "account_code": "wallet_liability", "account_id": wallet_id, "credit": minor}])
            else:
                AccountingService.post(conn, tx_id, [{"account_code": "wallet_liability", "account_id": wallet_id, "debit": minor}, {
                                       "account_code": "cash", "credit": minor}])
            # NotificationService.enqueue(conn, wallet["user_id"], kind.upper(), kind.title()+" completed", f"Your {kind} of {minor} minor units was completed.", tx_id)
            amount_egp = minor / 100

            message = f"Your {kind} of EGP {amount_egp:,.2f} was completed."

            NotificationService.enqueue(
                conn,
                wallet["user_id"],
                kind.upper(),
                kind.title() + " completed",
                message,
                tx_id
            )
            AuditService.record(conn, getattr(principal, "user_id", None), kind.upper(
            )+"_POSTED", "transaction", tx_id, new_value=str(minor))
            balance_after = self.wallets.balance(conn, wallet_id)
            conn.commit()
            log_event("financial_operation_completed", transaction_id=tx_id,
                      wallet_id=wallet_id, operation=kind, result_code="TRANSACTION_COMPLETED")
            return Result.ok("TRANSACTION_COMPLETED", f"{kind.title()} completed.",
                             {"transaction_id": tx_id, "wallet_id": wallet_id,
                              "amount_minor": minor, "balance_minor": balance_after})
        except Exception:
            import logging
            logging.getLogger("ewallet").exception(
                "financial operation failed")
            conn.rollback()
            return Result.fail("DATABASE_ERROR", "Financial operation failed; no changes were committed.")
        finally:
            conn.close()

    def _transaction_result(self, conn, tx, wallet_id):
        return {"transaction_id": tx["transaction_id"], "wallet_id": wallet_id,
                "amount_minor": tx["amount_minor"],
                "balance_minor": self.wallets.balance(conn, wallet_id)}

    def history(self, wallet_id, limit=100, principal=None):
        conn = self.db.connect()
        try:
            if not self.wallets.get(conn, wallet_id):
                return Result.fail("WALLET_NOT_FOUND", "Wallet does not exist.")
            if not authorize_wallet(conn, wallet_id, principal, allow_admin=True):
                return Result.fail("FORBIDDEN", "You are not authorized to view this history.")
            limit = max(1, min(int(limit), 500))
            rows = self.ledger.history(conn, wallet_id, limit)

            return Result.ok(
                "HISTORY_FOUND",
                "Ledger history retrieved.",
                [dict(row) for row in rows]
            )

        finally:
            conn.close()
