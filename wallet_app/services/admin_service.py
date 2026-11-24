from wallet_app.result import Result
from wallet_app.repositories.user_repository import UserRepository
from wallet_app.repositories.transaction_repository import TransactionRepository
from wallet_app.repositories.ledger_repository import LedgerRepository

class AdminService:
    def __init__(self, db):
        self.db = db
        self.users = UserRepository()
        self.transactions = TransactionRepository()
        self.ledger = LedgerRepository()

    def list_customers(self):
        with self.db.connect() as conn:
            return Result.ok("CUSTOMERS_FOUND", "Customers retrieved.",
                             [dict(r) for r in self.users.list_customers(conn)])

    def search_customers(self, term):
        with self.db.connect() as conn:
            return Result.ok("CUSTOMERS_FOUND", "Search completed.",
                             [dict(r) for r in self.users.search_customers(conn, term)])

    def set_customer_status(self, user_id, active):
        conn = self.db.transaction()
        try:
            count = self.users.set_status(conn, user_id, "active" if active else "inactive")
            if not count:
                conn.rollback()
                return Result.fail("CUSTOMER_NOT_FOUND", "Customer not found.")
            conn.commit()
            return Result.ok("STATUS_UPDATED", "Customer status updated.")
        finally:
            conn.close()

    def all_transactions(self, limit=200):
        with self.db.connect() as conn:
            return Result.ok("TRANSACTIONS_FOUND", "Transactions retrieved.",
                             [dict(r) for r in self.transactions.list_all(conn)])

    def all_ledger_entries(self, limit=200):
        with self.db.connect() as conn:
            return Result.ok("LEDGER_FOUND", "Ledger entries retrieved.",
                             [dict(r) for r in self.ledger.all_entries(conn, limit)])
