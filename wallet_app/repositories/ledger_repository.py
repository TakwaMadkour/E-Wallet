class LedgerRepository:
    def add(self, conn, transaction_id, wallet_id, amount_minor):
        conn.execute(
            """INSERT INTO ledger_entries(transaction_id,wallet_id,amount_minor)
               VALUES(?,?,?)""",
            (transaction_id, wallet_id, amount_minor)
        )

    def history(self, conn, wallet_id, limit=100):
        return conn.execute(
            """SELECT le.entry_id,le.transaction_id,le.amount_minor,le.created_at,
                      t.transaction_type,t.description
               FROM ledger_entries le
               JOIN transactions t ON t.transaction_id=le.transaction_id
               WHERE le.wallet_id=?
               ORDER BY le.entry_id DESC LIMIT ?""", (wallet_id, limit)
        ).fetchall()

    def all_entries(self, conn, limit=200):
        return conn.execute(
            """SELECT le.entry_id,le.transaction_id,le.wallet_id,le.amount_minor,
                      le.created_at,t.transaction_type,t.description
               FROM ledger_entries le JOIN transactions t
               ON t.transaction_id=le.transaction_id
               ORDER BY le.entry_id DESC LIMIT ?""", (limit,)
        ).fetchall()
