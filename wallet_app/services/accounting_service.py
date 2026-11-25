from wallet_app.result import Result

class AccountingService:
    """Posts balanced double-entry journal lines alongside the wallet sub-ledger."""
    def __init__(self, db): self.db = db

    @staticmethod
    def post(conn, transaction_id, lines):
        if not lines or sum(int(x.get("debit",0)) for x in lines) != sum(int(x.get("credit",0)) for x in lines):
            raise ValueError("Journal entry is not balanced.")
        for line in lines:
            debit, credit = int(line.get("debit",0)), int(line.get("credit",0))
            if debit < 0 or credit < 0 or (debit == 0) == (credit == 0):
                raise ValueError("Each journal line must contain either a positive debit or credit.")
            conn.execute("INSERT INTO journal_lines(transaction_id,account_code,account_id,debit_minor,credit_minor) VALUES(?,?,?,?,?)",
                         (transaction_id,line["account_code"],line.get("account_id"),debit,credit))

    def trial_balance(self,principal=None):
        from wallet_app.security_context import require_admin
        if not require_admin(principal): return Result.fail("FORBIDDEN","Administrator access required.")
        with self.db.connect() as conn:
            rows=conn.execute("SELECT account_code,SUM(debit_minor) debit_minor,SUM(credit_minor) credit_minor FROM journal_lines GROUP BY account_code ORDER BY account_code").fetchall()
            data=[dict(r) for r in rows]
            return Result.ok("TRIAL_BALANCE", "Trial balance retrieved.", {"accounts":data,
                "total_debits":sum(r["debit_minor"] for r in data),"total_credits":sum(r["credit_minor"] for r in data)})
