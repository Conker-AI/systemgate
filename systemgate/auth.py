from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

PBKDF2_ROUNDS = 200_000


def hash_key(key: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", key.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"{base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


# Stored hash -> SHA-256 of the key that matched it. PBKDF2 is slow on purpose, and paying it on
# every request let any caller that reaches the port burn CPU with wrong keys. Once a key has
# matched, a fast constant-time compare decides; a changed key file is a new entry.
_matched: dict[str, bytes] = {}


def verify_key(key: str | None, encoded: str) -> bool:
    if not key or not encoded:
        return False
    fast = hashlib.sha256(key.encode("utf-8")).digest()
    if encoded in _matched:
        return hmac.compare_digest(fast, _matched[encoded])
    try:
        salt_b64, digest_b64 = encoded.split("$", 1)
        salt = base64.b64decode(salt_b64.encode())
        expected = base64.b64decode(digest_b64.encode())
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", key.encode("utf-8"), salt, PBKDF2_ROUNDS)
    if not hmac.compare_digest(actual, expected):
        return False
    if len(_matched) >= 8:
        _matched.clear()
    _matched[encoded] = fast
    return True

