"""AES-256-GCM encryption for Coder GitHub OAuth tokens.

Tokens are encrypted at rest and the secret never leaves the server.
Key material is taken from CODER_ENCRYPTION_KEY, falling back to WEBUI_SECRET_KEY.
"""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from open_webui.env import WEBUI_SECRET_KEY

NONCE_LENGTH = 12


def _get_key() -> bytes:
    secret = os.getenv('CODER_ENCRYPTION_KEY', '') or WEBUI_SECRET_KEY
    if not secret:
        raise RuntimeError('CODER_ENCRYPTION_KEY / WEBUI_SECRET_KEY is required for Coder token encryption')
    return hashlib.sha256(secret.encode()).digest()


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret string; returns base64(nonce || ciphertext)."""
    aesgcm = AESGCM(_get_key())
    nonce = os.urandom(NONCE_LENGTH)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt_secret(token: str) -> str:
    """Decrypt a value produced by encrypt_secret."""
    raw = base64.b64decode(token)
    nonce, ciphertext = raw[:NONCE_LENGTH], raw[NONCE_LENGTH:]
    aesgcm = AESGCM(_get_key())
    return aesgcm.decrypt(nonce, ciphertext, None).decode()
