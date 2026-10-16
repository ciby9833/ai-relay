"""以用户本人身份使用飞书消息：找他所在的群、读群里最近的消息、以他的名义发消息。"""

import json
from datetime import UTC, datetime, timedelta

from app.feishu.client import FeishuClient, FeishuError, rich_text
from app.models import User


def _flatten(msg_type: str, content: str) -> str:
    try:
        body = json.loads(content or "{}")
    except ValueError:
        return content or ""
    if msg_type == "text":
        return body.get("text", "")
    if msg_type == "post":  # 富文本：拼出所有文字
        parts = []
        post = body.get("content") or next(iter(body.values()), {}).get("content", []) if isinstance(body, dict) else []
        for line in post or []:
            parts.append("".join(seg.get("text", "") for seg in line if isinstance(seg, dict)))
        title = body.get("title") or ""
        return "\n".join(p for p in [title, *parts] if p)
    return {"image": "[图片]", "file": "[文件]", "audio": "[语音]", "media": "[视频]", "sticker": "[表情]",
            "interactive": "[卡片]", "share_chat": "[群名片]", "share_user": "[个人名片]"}.get(msg_type, f"[{msg_type}]")


async def search_chats(feishu: FeishuClient, user: User, query: str, limit: int = 10) -> list[dict]:
    """以用户身份搜他所在的群（需要用户身份的群信息权限）；没有这项权限时退回到机器人所在的群里按名字找。"""
    try:
        data = await feishu.user_api(user, "GET", "/im/v1/chats/search", params={"query": query, "page_size": limit})
        items = data.get("items") or []
    except FeishuError as exc:
        if "user identity" not in str(exc):
            raise
        data = await feishu.tenant_api("GET", "/im/v1/chats", params={"page_size": 100})
        items = [c for c in data.get("items") or [] if query.lower() in (c.get("name") or "").lower()][:limit]
    return [{"chat_id": c["chat_id"], "name": c.get("name") or "（未命名群）", "description": c.get("description")}
            for c in items]


async def recent_messages(feishu: FeishuClient, user: User, chat_id: str, hours: int = 24, limit: int = 50) -> list[dict]:
    start = int((datetime.now(UTC) - timedelta(hours=hours)).timestamp())
    data = await feishu.user_api(user, "GET", "/im/v1/messages", params={
        "container_id_type": "chat", "container_id": chat_id, "start_time": str(start),
        "sort_type": "ByCreateTimeDesc", "page_size": limit,
    })
    messages = []
    for item in data.get("items") or []:
        if item.get("deleted"):
            continue
        text = _flatten(item.get("msg_type", ""), (item.get("body") or {}).get("content", ""))
        for mention in item.get("mentions") or []:
            text = text.replace(mention.get("key", "\0"), f"@{mention.get('name') or '某人'}")
        messages.append({
            "sender": (item.get("sender") or {}).get("id"), "sender_type": (item.get("sender") or {}).get("sender_type"),
            "text": text, "at": datetime.fromtimestamp(int(item.get("create_time", "0")) / 1000, UTC),
        })
    return messages[::-1]


async def send_as_user(feishu: FeishuClient, user: User, receive_id: str, receive_id_type: str, text: str) -> None:
    await feishu.user_api(user, "POST", "/im/v1/messages", params={"receive_id_type": receive_id_type}, json={
        "receive_id": receive_id, **rich_text(text),
    })
