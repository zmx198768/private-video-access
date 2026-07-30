import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    material = settings.ACCESS_CODE_ENCRYPTION_KEY or settings.SECRET_KEY
    digest = hashlib.sha256(
        b"private-video-access-code:v1:" + material.encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_access_code(code):
    return _fernet().encrypt(code.encode("utf-8")).decode("ascii")


def decrypt_access_code(ciphertext):
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, TypeError, UnicodeError, ValueError):
        return None
