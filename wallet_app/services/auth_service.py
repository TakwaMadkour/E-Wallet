import sqlite3
from wallet_app.result import Result
from wallet_app.security import hash_password, verify_password
from wallet_app.repositories.user_repository import UserRepository
from wallet_app.repositories.wallet_repository import WalletRepository
from wallet_app.services.audit_service import AuditService
from wallet_app.observability import log_event, new_correlation_id
from wallet_app.validation import normalize_email, normalize_phone

class AuthService:
    def __init__(self, db):
        self.db = db
        self.users = UserRepository()
        self.wallets = WalletRepository()

    
    def register(self, name, email, phone, password):
        if not all(
            isinstance(x, str) and x.strip()
            for x in (name, email, phone, password)
        ):
            return Result.fail(
                "INVALID_INPUT",
                "All registration fields are required."
            )

        try:
            email = normalize_email(email)
        except ValueError as exc:
            return Result.fail("INVALID_EMAIL", str(exc))

        try:
            phone = normalize_phone(phone)
        except ValueError as exc:
            return Result.fail("INVALID_PHONE", str(exc))

        name = name.strip()

        try:
            password_hash = hash_password(password)
        except ValueError as exc:
            return Result.fail("INVALID_PASSWORD", str(exc))

        conn = self.db.transaction()
        try:
            user_id = self.users.create(
                conn, name, email, phone, password_hash
            )

            wallet_id = self.wallets.create(conn, user_id)

            conn.commit()

            return Result.ok(
                "REGISTERED",
                "Customer and wallet created.",
                {"user_id": user_id, "wallet_id": wallet_id}
            )

        except sqlite3.IntegrityError:
            conn.rollback()
            return Result.fail(
                "DUPLICATE_USER",
                "Email or phone number is already registered."
            )

        except Exception:
            conn.rollback()
            return Result.fail("DATABASE_ERROR", "Registration failed.")

        finally:
            conn.close()


    def login(self, identifier, password):
        with self.db.connect() as conn:
            user = self.users.get_by_login(conn, identifier.strip())
            if not user or not verify_password(password, user["password_hash"]):
                new_correlation_id(); log_event("authentication_failed", operation="login", result_code="INVALID_CREDENTIALS")
                return Result.fail("INVALID_CREDENTIALS", "Incorrect login details.")
            if user["status"] != "active":
                return Result.fail("ACCOUNT_INACTIVE", "This account is inactive.")
            wallet = self.wallets.get_by_user(conn, user["user_id"])
            new_correlation_id(); log_event("authentication_succeeded", user_id=user["user_id"], operation="login", result_code="LOGIN_SUCCESS")
            return Result.ok("LOGIN_SUCCESS", "Login successful.",
                             {"user_id": user["user_id"], "name": user["name"],
                              "role": user["role"],
                              "wallet_id": wallet["wallet_id"] if wallet else None})

    
    def update_profile(self, principal, current_password, name, email, phone):
        if principal is None or principal.role != "customer":
            return Result.fail("FORBIDDEN", "Customer authentication required.")

        user_id = principal.user_id

        if not all(
        isinstance(x, str) and x.strip()
            for x in (name, email, phone)
        ):
            return Result.fail("INVALID_INPUT", "All profile fields are required.")

        try:
            email = normalize_email(email)
        except ValueError as exc:
            return Result.fail("INVALID_EMAIL", str(exc))

        try:
            phone = normalize_phone(phone)
        except ValueError as exc:
            return Result.fail("INVALID_PHONE", str(exc))

        name = name.strip()
        conn = self.db.transaction()
        try:
            # Retrieve the customer and verify the current password
            user = self.users.get_by_id(conn, user_id)

            if not user or not verify_password(current_password, user["password_hash"]):
                conn.rollback()
                return Result.fail("INVALID_CREDENTIALS", "Current password is incorrect.")

            # Preserve old profile information for auditing
            old_values = {
                "name": user["name"],
                "email": user["email"],
                "phone": user["phone"]
            }

            # Update the profile
            changed = self.users.update_profile(conn, user_id, name, email, phone)

            if not changed:
                conn.rollback()
                return Result.fail("USER_NOT_FOUND", "Customer not found.")

            new_values = {
                "name": name.strip(),
                "email": email.strip().lower(),
                "phone": phone.strip()
            }

            # Record the profile update
            AuditService.record(
                conn,
                user_id,
                "PROFILE_UPDATED",
                "user",
                user_id,
                old_value=str(old_values),
                new_value=str(new_values)
            )

            conn.commit()
            return Result.ok("PROFILE_UPDATED", "Profile updated.")

        except sqlite3.IntegrityError:
            conn.rollback()
            return Result.fail("DUPLICATE_USER", "Email or phone number is already in use.")

        except Exception:
            conn.rollback()
            return Result.fail("DATABASE_ERROR", "Profile update failed.")

        finally:
            conn.close()


    def change_password(self, principal, current_password, new_password):
        if principal is None:
            return Result.fail("FORBIDDEN", "Authentication required.")
        user_id = principal.user_id
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
            AuditService.record(conn, user_id, "PASSWORD_CHANGED", "user", user_id)
            conn.commit()
            return Result.ok("PASSWORD_CHANGED", "Password changed.")
        finally:
            conn.close()
