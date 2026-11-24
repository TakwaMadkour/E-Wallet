class WalletRepository:
    def create(self, conn, user_id):
        cur = conn.execute("INSERT INTO wallets(user_id) VALUES(?)", (user_id,))
        return cur.lastrowid

    def get(self, conn, wallet_id):
        return conn.execute(
            """SELECT w.*,u.name AS owner_name,u.status AS owner_status,u.user_id
               FROM wallets w JOIN users u ON u.user_id=w.user_id
               WHERE w.wallet_id=?""", (wallet_id,)
        ).fetchone()

    def get_by_user(self, conn, user_id):
        return conn.execute(
            "SELECT * FROM wallets WHERE user_id=?", (user_id,)
        ).fetchone()

    def balance(self, conn, wallet_id):
        row = conn.execute(
            "SELECT COALESCE(SUM(amount_minor),0) AS balance "
            "FROM ledger_entries WHERE wallet_id=?", (wallet_id,)
        ).fetchone()
        return int(row["balance"])
