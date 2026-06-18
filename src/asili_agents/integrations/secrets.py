"""Encryption for per-seller channel access tokens at rest.

Each seller connects their own Instagram / WhatsApp account, yielding a
per-seller access token. Those tokens are encrypted with AES-256-GCM before they
touch MongoDB and decrypted only at send time. The master key comes from the
``TOKEN_ENCRYPTION_KEY`` env var (base64, 32 bytes). Tokens are never logged.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class TokenVaultError(RuntimeError):
    """Raised when the vault is misconfigured or a value can't be decrypted."""


class TokenVault:
    """AES-256-GCM encrypt/decrypt for short secrets (channel tokens).

    Ciphertext is serialized as ``base64(nonce(12) || ciphertext+tag)`` so a
    single opaque string can be stored on the ChannelConnection document.
    """

    def __init__(self, master_key_b64: str) -> None:
        try:
            key = base64.b64decode(master_key_b64)
        except Exception as exc:  # noqa: BLE001 — surface a clear config error
            raise TokenVaultError("TOKEN_ENCRYPTION_KEY is not valid base64") from exc
        if len(key) != 32:
            raise TokenVaultError("TOKEN_ENCRYPTION_KEY must decode to exactly 32 bytes")
        self._aes = AESGCM(key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a token; returns an opaque base64 blob. Never log the input."""
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, blob: str) -> str:
        """Decrypt a blob produced by :meth:`encrypt`. Raises on tamper/bad key."""
        try:
            raw = base64.b64decode(blob)
            nonce, ct = raw[:12], raw[12:]
            return self._aes.decrypt(nonce, ct, None).decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise TokenVaultError("could not decrypt token (tampered or wrong key)") from exc

    @staticmethod
    def generate_key_b64() -> str:
        """Generate a fresh 32-byte key, base64-encoded (for ops/setup, not runtime)."""
        return base64.b64encode(os.urandom(32)).decode("ascii")
