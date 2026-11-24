class TransactionRepository:
    def get_by_key(self, conn, key):
        return conn.execute(
            "SELECT * FROM transactions WHERE idempotency_key=?", (key,)
        ).fetchone()

    def create(self, conn, key, request_hash, kind, amount_minor, description=None,
               reversal_of=None):
        cur = conn.execute(
            """INSERT INTO transactions
               (idempotency_key,request_hash,transaction_type,amount_minor,status,
                description,reversal_of_transaction_id)
               VALUES(?,?,?,?, 'completed',?,?)""",
            (key, request_hash, kind, amount_minor, description, reversal_of)
        )
        return cur.lastrowid

    def get(self, conn, transaction_id):
        return conn.execute(
            "SELECT * FROM transactions WHERE transaction_id=?", (transaction_id,)
        ).fetchone()

    def list_all(self, conn, limit=200):
        return conn.execute(
            "SELECT * FROM transactions ORDER BY transaction_id DESC LIMIT ?",
            (limit,)
        ).fetchall()
