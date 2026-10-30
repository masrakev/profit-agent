"""Envelope encryption of platform access tokens (AES-256-GCM, ADR 0021).

Each token gets its own random data key, which encrypts it; the master key (environment, never
in the database) encrypts the data key. Both encryptions bind the store and the provider as
associated data, so a ciphertext copied to another store or provider does not decrypt. The
key id names the master key, so it can be rotated: data keys are re-wrapped, tokens stay.
"""

import base64
import binascii
import os
from dataclasses import dataclass
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12


class CryptoError(ValueError):
    pass


@dataclass(frozen=True)
class MasterKey:
    key_id: str
    key: bytes

    @classmethod
    def from_base64(cls, key_id: str, encoded: str) -> "MasterKey":
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            key = base64.b64decode(padded, altchars=b"-_", validate=True)
        except (binascii.Error, ValueError) as exc:
            raise CryptoError("the token encryption key is not base64url") from exc
        if len(key) != 32:
            raise CryptoError("the token encryption key must be 32 bytes")
        return cls(key_id, key)

    @staticmethod
    def generate() -> str:
        """A new key, base64url (for TOKEN_ENCRYPTION_KEY)."""
        return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode()


@dataclass(frozen=True)
class Sealed:
    key_id: str
    wrapped_key: bytes
    key_nonce: bytes
    ciphertext: bytes
    nonce: bytes


def _aad(store_id: UUID, provider: str, part: str) -> bytes:
    return f"{store_id}:{provider}:{part}".encode()


def seal(master: MasterKey, store_id: UUID, provider: str, secret: str) -> Sealed:
    data_key = AESGCM.generate_key(bit_length=256)
    nonce, key_nonce = os.urandom(NONCE_BYTES), os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(data_key).encrypt(nonce, secret.encode(), _aad(store_id, provider, "token"))
    wrapped = AESGCM(master.key).encrypt(
        key_nonce, data_key, _aad(store_id, provider, f"key:{master.key_id}")
    )
    return Sealed(master.key_id, wrapped, key_nonce, ciphertext, nonce)


def open_sealed(master: MasterKey, store_id: UUID, provider: str, sealed: Sealed) -> str:
    if sealed.key_id != master.key_id:
        raise CryptoError(f"sealed with key {sealed.key_id!r}, not {master.key_id!r}")
    try:
        data_key = AESGCM(master.key).decrypt(
            sealed.key_nonce, sealed.wrapped_key, _aad(store_id, provider, f"key:{sealed.key_id}")
        )
        plain = AESGCM(data_key).decrypt(
            sealed.nonce, sealed.ciphertext, _aad(store_id, provider, "token")
        )
    except InvalidTag as exc:
        raise CryptoError("the token does not decrypt (wrong key, store or provider)") from exc
    return plain.decode()


def rewrap(old: MasterKey, new: MasterKey, store_id: UUID, provider: str, sealed: Sealed) -> Sealed:
    """The same token under the new master key (key rotation), its data key unchanged."""
    if sealed.key_id != old.key_id:
        raise CryptoError(f"sealed with key {sealed.key_id!r}, not {old.key_id!r}")
    data_key = AESGCM(old.key).decrypt(
        sealed.key_nonce, sealed.wrapped_key, _aad(store_id, provider, f"key:{old.key_id}")
    )
    key_nonce = os.urandom(NONCE_BYTES)
    wrapped = AESGCM(new.key).encrypt(
        key_nonce, data_key, _aad(store_id, provider, f"key:{new.key_id}")
    )
    return Sealed(new.key_id, wrapped, key_nonce, sealed.ciphertext, sealed.nonce)
