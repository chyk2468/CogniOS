"""Password and security-answer hashing (Argon2id)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_secret(value: str) -> str:
    return _hasher.hash(value)


def verify_secret(stored_hash: str, value: str) -> bool:
    try:
        _hasher.verify(stored_hash, value)
        if _hasher.check_needs_rehash(stored_hash):
            pass  # caller may rehash on next successful login
        return True
    except VerifyMismatchError:
        return False


def normalize_pet_answer(answer: str) -> str:
    return answer.strip().lower()


def hash_pet_answer(answer: str) -> str:
    return hash_secret(normalize_pet_answer(answer))


def verify_pet_answer(stored_hash: str, answer: str) -> bool:
    return verify_secret(stored_hash, normalize_pet_answer(answer))
