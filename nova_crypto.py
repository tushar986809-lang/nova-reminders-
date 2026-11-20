"""Shared by NOVA (laptop) and the cloud script. Encrypts reminder text so the
public GitHub repo never shows what your reminders say. Needs NOVA_SECRET (any passphrase)."""
import base64
import hashlib
import os

from cryptography.fernet import Fernet


def _fernet():
    secret = os.getenv("NOVA_SECRET", "")
    if not secret:
        raise RuntimeError("NOVA_SECRET set nahi hai")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt(text):
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token):
    return _fernet().decrypt(token.encode()).decode()
