import sqlite3
from wallet_app.result import Result
from wallet_app.security import hash_password, verify_password
from wallet_app.repositories.user_repository import UserRepository
from wallet_app.repositories.wallet_repository import WalletRepository

class AuthService:
    def __init__(self, db):
        self.db = db
        self.users = UserRepository()
        self.wallets = WalletRepository()

    def register(self, name, email, phone, password):
        if not all(str(x).strip() for x in (name, email, phone, password)):
            return Result.fail("INVALID_INPUT", "All registration fields are required.")
        if "@" not in email:
            return Result.fail("INVALID_EMAIL", "Enter a valid email address.")
        try:
            password_hash = hash_password(password)
        except ValueError as exc:
            return Result.fail("INVALID_PASSWORD", str(exc))
        conn = self.db.transaction()
        try:
            user_id = self.users.create(conn, name, email, phone, password_hash)
            wallet_id = self.wallets.create(conn, user_id)
            conn.commit()
            return Result.ok("REGISTERED", "Customer and wallet created.",
                             {"user_id": user_id, "wallet_id": wallet_id})
        except sqlite3.IntegrityError:
            conn.rollback()
            return Result.fail("DUPLICATE_USER", "Email or phone number is already registered.")
        except Exception:
            conn.rollback()
            return Result.fail("DATABASE_ERROR", "Registration failed.")
        finally:
            conn.close()

    def login(self, identifier, password):
        with self.db.connect() as conn:
            user = self.users.get_by_login(conn, identifier.strip())
            if not user or not verify_password(password, user["password_hash"]):
                return Result.fail("INVALID_CREDENTIALS", "Incorrect login details.")
            if user["status"] != "active":
                return Result.fail("ACCOUNT_INACTIVE", "This account is inactive.")
            wallet = self.wallets.get_by_user(conn, user["user_id"])
            return Result.ok("LOGIN_SUCCESS", "Login successful.",
                             {"user_id": user["user_id"], "name": user["name"],
                              "role": user["role"],
                              "wallet_id": wallet["wallet_id"] if wallet else None})

    def update_profile(self, user_id, name, email, phone):
        if not all(str(x).strip() for x in (name, email, phone)) or "@" not in email:
            return Result.fail("INVALID_INPUT", "Enter a valid name, email and phone.")
        conn = self.db.transaction()
        try:
            changed = self.users.update_profile(conn, user_id, name, email, phone)
            if not changed:
                conn.rollback()
                return Result.fail("USER_NOT_FOUND", "Customer not found.")
            conn.commit()
            return Result.ok("PROFILE_UPDATED", "Profile updated.")
        except sqlite3.IntegrityError:
            conn.rollback()
            return Result.fail("DUPLICATE_USER", "Email or phone number is already in use.")
        finally:
            conn.close()

    def change_password(self, user_id, current_password, new_password):
        try:
            new_hash = hash_password(new_password)
        except ValueError as exc:
            return Result.fail("INVALID_PASSWORD", str(exc))
        conn = self.db.transaction()
        try:
            user = self.users.get_by_id(conn, user_id)
            if not user or not verify_password(current_password, user["password_hash"]):
                conn.rollback()
                return Result.fail("INVALID_CREDENTIALS", "Current password is incorrect.")
            self.users.update_password(conn, user_id, new_hash)
            conn.commit()
            return Result.ok("PASSWORD_CHANGED", "Password changed.")
        finally:
            conn.close()
