import os
from functools import lru_cache

from cryptography.fernet import Fernet


@lru_cache(maxsize=1)
def _get_cipher() -> Fernet:
    key = os.getenv("CREDENTIAL_MASTER_KEY")

    if not key:
        raise RuntimeError(
            "CREDENTIAL_MASTER_KEY is not configured."
        )

    return Fernet(key.encode("utf-8"))


def encrypt_secret(value: str) -> bytes:
    return _get_cipher().encrypt(
        value.encode("utf-8")
    )


def decrypt_secret(value: bytes) -> str:
    return _get_cipher().decrypt(
        value
    ).decode("utf-8")
