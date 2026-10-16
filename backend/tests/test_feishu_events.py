import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.feishu.events import decrypt_event, extract_text


def _encrypt(encrypt_key: str, payload: dict) -> str:
    key = hashlib.sha256(encrypt_key.encode()).digest()
    iv = os.urandom(16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(json.dumps(payload).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return base64.b64encode(iv + encryptor.update(padded) + encryptor.finalize()).decode()


def test_decrypt_event_roundtrip():
    payload = {"type": "url_verification", "challenge": "abc", "token": "t"}
    assert decrypt_event("my-key", _encrypt("my-key", payload)) == payload


def test_extract_text_strips_mentions():
    message = {"message_type": "text", "content": json.dumps({"text": "@_user_1 明天提醒我开会"})}
    assert extract_text(message) == "明天提醒我开会"


def test_extract_text_rejects_non_text():
    assert extract_text({"message_type": "image", "content": "{}"}) is None
