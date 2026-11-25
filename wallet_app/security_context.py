from dataclasses import dataclass

@dataclass(frozen=True)
class Principal:
    user_id: int
    role: str

    @classmethod
    def from_session(cls, session):
        if not session or "user_id" not in session or "role" not in session:
            raise ValueError("A valid authenticated session is required.")
        return cls(int(session["user_id"]), str(session["role"]))


def authorize_wallet(conn, wallet_id, principal, allow_admin=False):
    if principal is None:
        return False
    row = conn.execute("SELECT user_id FROM wallets WHERE wallet_id=?", (wallet_id,)).fetchone()
    if row is None:
        return False
    if principal.role == "admin" and allow_admin:
        return True
    return principal.role == "customer" and int(row["user_id"]) == int(principal.user_id)


def require_admin(principal):
    return principal is not None and principal.role == "admin"
