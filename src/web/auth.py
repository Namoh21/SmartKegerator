from __future__ import annotations

import base64
import hashlib
import hmac
import os


def hash_password(password: str) -> str:
    """Return a salted PBKDF2-HMAC-SHA256 hash, base64-encoded."""
    salt = os.urandom(16)
    key  = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 390_000)
    return base64.b64encode(salt + key).decode()


def verify_password(password: str, stored: str) -> bool:
    """Constant-time comparison of a plaintext password against a stored hash."""
    try:
        raw  = base64.b64decode(stored.encode())
        salt, key = raw[:16], raw[16:]
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 390_000)
        return hmac.compare_digest(key, check)
    except Exception:
        return False


def credential_fingerprint(password_hash: str) -> str:
    """Short non-reversible fingerprint of a stored password hash.

    Embedded in web sessions and API tokens so that changing an admin's
    password (or deleting the admin) invalidates all previously issued
    sessions and tokens for that account.
    """
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]
