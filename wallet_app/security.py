import hashlib
import hmac
import secrets

_ITERATIONS = 310_000


def hash_password(password: str) -> str:
    if not isinstance(password, str):
        raise ValueError("Password must be text.")

    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters.")

    if len(password) > 128:
        raise ValueError("Password cannot exceed 128 characters.")

    common_passwords = {
        "12345678",
        "123456789",
        "password",
        "password123",
        "qwerty123",
        "admin123456"
    }

    if password.lower() in common_passwords:
        raise ValueError(
            "This password is too common. Choose a stronger password.")

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt,
        _ITERATIONS
    )

    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError, AttributeError):
        return False
