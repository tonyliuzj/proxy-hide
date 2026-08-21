from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import Settings, get_settings


class EncryptionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class KeyRing:
    primary_key_id: str
    keys: dict[str, bytes]

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> KeyRing:
        settings = settings or get_settings()
        configured = settings.encryption_keys.strip()
        if not configured:
            if settings.environment == "production":
                raise EncryptionError("encryption keys are required in production")
            return cls("dev", {"dev": hashlib.sha256(b"proxy-hide-development-key").digest()})
        values: dict[str, bytes] = {}
        for index, item in enumerate(configured.split(",")):
            item = item.strip()
            if not item:
                continue
            if ":" in item:
                key_id, encoded = item.split(":", 1)
            else:
                key_id, encoded = f"key-{index + 1}", item
            try:
                key = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise EncryptionError(f"key {key_id!r} is not valid base64") from exc
            if len(key) != 32:
                raise EncryptionError(f"key {key_id!r} must decode to exactly 32 bytes")
            if not key_id or "\0" in key_id or len(key_id) > 64:
                raise EncryptionError("key IDs must be 1-64 characters without NUL")
            values[key_id] = key
        if not values:
            raise EncryptionError("at least one encryption key is required")
        return cls(next(iter(values)), values)

    def encrypt(self, plaintext: bytes, *, associated_data: bytes = b"") -> bytes:
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self.keys[self.primary_key_id]).encrypt(
            nonce, plaintext, associated_data
        )
        return b"PH1\0" + self.primary_key_id.encode() + b"\0" + nonce + ciphertext

    def decrypt(self, payload: bytes, *, associated_data: bytes = b"") -> bytes:
        if not payload.startswith(b"PH1\0"):
            raise EncryptionError("encrypted value has an unsupported format")
        try:
            key_id_raw, encrypted = payload[4:].split(b"\0", 1)
            key_id = key_id_raw.decode("ascii")
        except (ValueError, UnicodeDecodeError) as exc:
            raise EncryptionError("encrypted value is malformed") from exc
        key = self.keys.get(key_id)
        if key is None:
            raise EncryptionError(f"encryption key {key_id!r} is unavailable")
        if len(encrypted) < 28:
            raise EncryptionError("encrypted value is truncated")
        try:
            return AESGCM(key).decrypt(encrypted[:12], encrypted[12:], associated_data)
        except Exception as exc:
            raise EncryptionError("encrypted value failed authentication") from exc

    def encrypt_text(self, value: str, *, associated_data: bytes = b"") -> bytes:
        return self.encrypt(value.encode(), associated_data=associated_data)

    def decrypt_text(self, value: bytes, *, associated_data: bytes = b"") -> str:
        try:
            return self.decrypt(value, associated_data=associated_data).decode()
        except UnicodeDecodeError as exc:
            raise EncryptionError("encrypted value is not UTF-8") from exc

    def encrypt_json(self, value: Any, *, associated_data: bytes = b"") -> bytes:
        return self.encrypt(
            json.dumps(value, separators=(",", ":"), sort_keys=True).encode(),
            associated_data=associated_data,
        )

    def decrypt_json(self, value: bytes, *, associated_data: bytes = b"") -> Any:
        return json.loads(self.decrypt_text(value, associated_data=associated_data))


_password_hasher = PasswordHasher(time_cost=3, memory_cost=65_536, parallelism=2)


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    if len(password.encode()) > 1024:
        raise ValueError("password is too long")
    return _password_hasher.hash(password)


def verify_password(password_hash: str, candidate: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, candidate)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def generate_endpoint_secret() -> str:
    return secrets.token_urlsafe(32)


def endpoint_hmac_key_bytes(settings: Settings | None = None) -> bytes:
    settings = settings or get_settings()
    configured = settings.endpoint_hmac_key.strip()
    try:
        decoded = base64.b64decode(configured, validate=True)
    except ValueError:
        decoded = b""
    if len(decoded) >= 32:
        return decoded
    if settings.environment == "production":
        raise ValueError("the endpoint HMAC key must be base64-encoded and at least 32 bytes")
    return configured.encode()


def digest_endpoint_secret(secret: str, settings: Settings | None = None) -> str:
    return hmac.new(endpoint_hmac_key_bytes(settings), secret.encode(), hashlib.sha256).hexdigest()


def verify_endpoint_secret(
    expected_digest: str, candidate: str, settings: Settings | None = None
) -> bool:
    return hmac.compare_digest(expected_digest, digest_endpoint_secret(candidate, settings))


def digest_proxy_identity(identity_hash: str, settings: Settings | None = None) -> str:
    return hmac.new(
        endpoint_hmac_key_bytes(settings),
        f"proxy-route:{identity_hash}".encode(),
        hashlib.sha256,
    ).hexdigest()


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)
