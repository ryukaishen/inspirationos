"""Argon2id password hashing (M9). No plaintext password is ever logged or
stored — only the hash, via `users.password_hash`."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Fails closed: a mismatch, and a malformed/foreign hash, both mean "no"."""
    try:
        return _hasher.verify(password_hash, password)
    except Argon2Error:
        return False
