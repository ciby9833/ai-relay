"""飞书事件回调的解密与解析。"""

import base64
import hashlib
import json
import re

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_MENTION = re.compile(r"@_(?:user_\d+|all)\s*")


def decrypt_event(encrypt_key: str, encrypted: str) -> dict:
    """AES-256-CBC，密钥为 sha256(encrypt_key)，密文前 16 字节是 IV。"""
    key = hashlib.sha256(encrypt_key.encode()).digest()
    raw = base64.b64decode(encrypted)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(raw[:16])).decryptor()
    padded = decryptor.update(raw[16:]) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return json.loads(unpadder.update(padded) + unpadder.finalize())


def extract_text(message: dict) -> str | None:
    """从 im.message.receive_v1 的 message 里取出纯文本；非文本消息返回 None。"""
    if message.get("message_type") != "text":
        return None
    try:
        text = json.loads(message.get("content") or "{}").get("text", "")
    except ValueError:
        return None
    return _MENTION.sub("", text).strip()


def text_with_names(message: dict, drop_open_ids: set[str] | None = None) -> str | None:
    """文本消息里的 @_user_1 换成被@的人名，供模型理解“谁让谁做什么”；drop_open_ids 里的（例如机器人自己）直接去掉。"""
    if message.get("message_type") != "text":
        return None
    try:
        text = json.loads(message.get("content") or "{}").get("text", "")
    except ValueError:
        return None
    for mention in message.get("mentions") or []:
        if not mention.get("key"):
            continue
        if (mention.get("id") or {}).get("open_id") in (drop_open_ids or set()):
            text = text.replace(mention["key"], "")
        else:
            text = text.replace(mention["key"], f"@{mention.get('name') or '某人'}")
    return _MENTION.sub("", text).strip()


def mentioned_people(message: dict) -> list[tuple[str | None, str | None, str]]:
    return [((m.get("id") or {}).get("open_id"), m.get("name"), "mention") for m in message.get("mentions") or []]
