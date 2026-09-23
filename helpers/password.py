"""Password hashing for the account-link takeover password.

Only argon2 hashes are stored -- never the password itself. Argon2id is the current
recommendation and ``argon2-cffi`` ships a verifier that reports whether a stored hash
needs rehashing when the cost parameters move.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a password against a stored hash.

    Any failure -- wrong password, truncated or foreign hash -- is reported as ``False``:
    the caller is unauthenticated and must not learn which part did not match.
    """
    if not password or not password_hash:
        return False
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False
    except Exception:  # noqa: BLE001 - argon2 raises on malformed input
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:  # noqa: BLE001
        return True
