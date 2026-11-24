class UserRepository:
    def get_by_id(self, conn, user_id):
        return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

    def get_by_login(self, conn, identifier):
        return conn.execute(
            "SELECT * FROM users WHERE email=? COLLATE NOCASE OR phone=?",
            (identifier, identifier)
        ).fetchone()

    def create(self, conn, name, email, phone, password_hash, role="customer"):
        cur = conn.execute(
            """INSERT INTO users(name,email,phone,password_hash,role)
               VALUES(?,?,?,?,?)""",
            (name.strip(), email.strip().lower(), phone.strip(), password_hash, role)
        )
        return cur.lastrowid

    def list_customers(self, conn):
        return conn.execute(
            "SELECT user_id,name,email,phone,status,created_at FROM users "
            "WHERE role='customer' ORDER BY user_id"
        ).fetchall()

    def search_customers(self, conn, term):
        pattern = f"%{term}%"
        return conn.execute(
            """SELECT user_id,name,email,phone,status FROM users
               WHERE role='customer' AND (name LIKE ? OR email LIKE ? OR phone LIKE ?)
               ORDER BY user_id""", (pattern, pattern, pattern)
        ).fetchall()

    def set_status(self, conn, user_id, status):
        return conn.execute(
            "UPDATE users SET status=? WHERE user_id=? AND role='customer'",
            (status, user_id)
        ).rowcount

    def update_profile(self, conn, user_id, name, email, phone):
        return conn.execute(
            "UPDATE users SET name=?,email=?,phone=? WHERE user_id=? AND role='customer'",
            (name.strip(), email.strip().lower(), phone.strip(), user_id)
        ).rowcount

    def update_password(self, conn, user_id, password_hash):
        return conn.execute(
            "UPDATE users SET password_hash=? WHERE user_id=?",
            (password_hash, user_id)
        ).rowcount
