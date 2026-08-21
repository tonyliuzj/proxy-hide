from __future__ import annotations

import base64
import os

import pytest

from app.config import Settings
from app.security import (
    EncryptionError,
    KeyRing,
    digest_endpoint_secret,
    endpoint_hmac_key_bytes,
    hash_password,
    verify_endpoint_secret,
    verify_password,
)


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


def test_keyring_encrypts_with_aad_and_supports_rotation() -> None:
    old, new = _key(), _key()
    first = KeyRing.from_settings(Settings(environment="test", encryption_keys=f"old:{old}"))
    encrypted = first.encrypt_text("secret", associated_data=b"route:1")
    rotated = KeyRing.from_settings(
        Settings(environment="test", encryption_keys=f"new:{new},old:{old}")
    )
    assert rotated.decrypt_text(encrypted, associated_data=b"route:1") == "secret"
    with pytest.raises(EncryptionError):
        rotated.decrypt_text(encrypted, associated_data=b"route:2")
    assert b"secret" not in encrypted


def test_password_hash_is_argon2_and_verifies() -> None:
    value = hash_password("a sufficiently long password")
    assert value.startswith("$argon2id$")
    assert verify_password(value, "a sufficiently long password")
    assert not verify_password(value, "incorrect password")


def test_endpoint_digest_uses_shared_decoded_key() -> None:
    raw = os.urandom(32)
    settings = Settings(environment="test", endpoint_hmac_key=base64.b64encode(raw).decode())
    assert endpoint_hmac_key_bytes(settings) == raw
    digest = digest_endpoint_secret("credential", settings)
    assert verify_endpoint_secret(digest, "credential", settings)
    assert not verify_endpoint_secret(digest, "other", settings)


def test_production_rejects_raw_endpoint_pepper() -> None:
    settings = Settings(
        environment="production",
        encryption_keys=_key(),
        endpoint_hmac_key="not-base64!",
        session_secret="a secure independent session secret",
    )
    with pytest.raises(ValueError):
        endpoint_hmac_key_bytes(settings)
