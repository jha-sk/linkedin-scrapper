"""
Symmetric encryption for stored LinkedIn session cookies.

A `li_at` cookie is a full account credential. It is never written to the
database in the clear and never returned by the API — reads give a masked
preview only. The key comes from PHANTOM_SECRET_KEY; if that is unset a key
file is generated under the data directory with 0600 permissions, so a default
install is still encrypted at rest rather than silently plaintext.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

_KEY_FILE = settings.data_dir / ".secret_key"


def _load_key() -> bytes:
    if settings.secret_key:
        digest = hashlib.sha256(settings.secret_key.encode()).digest()
        return base64.urlsafe_b64encode(digest)
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes().strip()
    key = Fernet.generate_key()
    _KEY_FILE.write_bytes(key)
    os.chmod(_KEY_FILE, 0o600)
    return key


_fernet = Fernet(_load_key())


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet.decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("stored secret could not be decrypted with the current key") from exc


def mask(plaintext: str, keep: int = 4) -> str:
    """A preview safe to show in the UI: length plus the last few characters."""
    if not plaintext:
        return ""
    if len(plaintext) <= keep:
        return "•" * len(plaintext)
    return f"{'•' * 8}{plaintext[-keep:]} ({len(plaintext)} chars)"
