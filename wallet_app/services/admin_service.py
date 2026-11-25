from wallet_app.result import Result
from wallet_app.repositories.user_repository import UserRepository
from wallet_app.repositories.transaction_repository import TransactionRepository
from wallet_app.repositories.ledger_repository import LedgerRepository
from wallet_app.security_context import require_admin
from wallet_app.services.audit_service import AuditService
from wallet_app.services.notification_service import NotificationService

class AdminService:
    def __init__(self, db):
        self.db=db; self.users=UserRepository(); self.transactions=TransactionRepository(); self.ledger=LedgerRepository()
    def _allowed(self,principal): return require_admin(principal)
    def list_customers(self,principal=None):
        if not self._allowed(principal): return Result.fail("FORBIDDEN","Administrator access required.")
        with self.db.connect() as conn: return Result.ok("CUSTOMERS_FOUND","Customers retrieved.",[dict(r) for r in self.users.list_customers(conn)])
    def search_customers(self,term,principal=None):
        if not self._allowed(principal): return Result.fail("FORBIDDEN","Administrator access required.")
        with self.db.connect() as conn: return Result.ok("CUSTOMERS_FOUND","Search completed.",[dict(r) for r in self.users.search_customers(conn,term)])
    def set_customer_status(self,user_id,active,principal=None,reason="Administrative status change"):
        if not self._allowed(principal): return Result.fail("FORBIDDEN","Administrator access required.")
        conn=self.db.transaction()
        try:
            old=conn.execute("SELECT status FROM users WHERE user_id=? AND role='customer'",(user_id,)).fetchone()
            count=self.users.set_status(conn,user_id,"active" if active else "inactive")
            if not count: conn.rollback(); return Result.fail("CUSTOMER_NOT_FOUND","Customer not found.")
            NotificationService.enqueue(conn,user_id,"ACCOUNT_STATUS_CHANGED","Account status updated",f"Your account is now {'active' if active else 'inactive'}.")
            AuditService.record(conn,principal.user_id,"CUSTOMER_STATUS_CHANGED","user",user_id,old["status"] if old else None,"active" if active else "inactive",reason)
            conn.commit(); return Result.ok("STATUS_UPDATED","Customer status updated.")
        finally: conn.close()
    def all_transactions(self,limit=200,principal=None):
        if not self._allowed(principal): return Result.fail("FORBIDDEN","Administrator access required.")
        with self.db.connect() as conn: return Result.ok("TRANSACTIONS_FOUND","Transactions retrieved.",[dict(r) for r in self.transactions.list_all(conn,max(1,min(int(limit),1000)))])
    def all_ledger_entries(self,limit=200,principal=None):
        if not self._allowed(principal): return Result.fail("FORBIDDEN","Administrator access required.")
        with self.db.connect() as conn: return Result.ok("LEDGER_FOUND","Ledger entries retrieved.",[dict(r) for r in self.ledger.all_entries(conn,max(1,min(int(limit),1000)))])
