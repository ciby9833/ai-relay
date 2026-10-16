"""按用户习惯的语言交互。

- 用户的语言：设置里可以手动指定；没指定时，从他发给 Relay 的消息里自动识别并记住（中文 / English / Bahasa Indonesia）。
- Relay 主动说的话（提醒、简报、摘要）和卡片上的按钮、标题都用这个语言。
- 替他写给别人的内容（邮件回复、飞书消息）不看他的语言，看对方：回邮件用原邮件的语言，发消息用和对方往来时用的语言。
"""

import re
from contextvars import ContextVar

LANGUAGES = {"zh": "简体中文", "en": "English", "id": "Bahasa Indonesia"}
DEFAULT = "zh"

_CJK = re.compile(r"[一-鿿]")
_WORD = re.compile(r"[a-zA-Z]+")
_ID_WORDS = {
    "yang", "dan", "tidak", "untuk", "saya", "ini", "itu", "dengan", "ada", "bisa", "sudah", "apa", "tolong",
    "kita", "kami", "akan", "dari", "ke", "di", "juga", "belum", "mohon", "terima", "kasih", "bapak", "ibu",
    "sudah", "harus", "karena", "jika", "atau", "kapan", "bagaimana", "siapa", "minta", "buat", "cek", "lagi",
}
_EN_WORDS = {
    "the", "and", "is", "are", "to", "of", "for", "with", "this", "that", "please", "what", "can", "you", "my",
    "me", "i", "we", "it", "on", "in", "do", "have", "be", "will", "would", "should", "need", "how", "who", "when",
}


def detect(text: str) -> str | None:
    """猜一段文字的语言；太短或拿不准时返回 None。"""
    text = re.sub(r"https?://\S+|<[^>]+>|`[^`]*`", " ", text or "")
    cjk = len(_CJK.findall(text))
    words = [w.lower() for w in _WORD.findall(text)]
    if cjk >= 2 and cjk >= len(words):
        return "zh"
    if len(words) < 3:
        return None
    id_hits = sum(w in _ID_WORDS for w in words)
    en_hits = sum(w in _EN_WORDS for w in words)
    if id_hits >= 2 and id_hits > en_hits:
        return "id"
    if en_hits >= 2 and en_hits >= id_hits:
        return "en"
    return None


def user_language(settings: dict) -> str:
    chosen = settings.get("language") or "auto"
    if chosen in LANGUAGES:
        return chosen
    return settings.get("detected_language") or DEFAULT


def learn(row_data: dict, text: str) -> dict | None:
    """从用户这句话更新识别到的语言；没变化返回 None。"""
    found = detect(text)
    if found and row_data.get("detected_language") != found:
        return {**row_data, "detected_language": found}
    return None


def instruction(lang: str) -> str:
    """给生成用户可见内容的提示词加的一句语言要求。"""
    return f"用 {LANGUAGES.get(lang, LANGUAGES[DEFAULT])} 写。"


_STRINGS = {
    "confirm": {"zh": "确认", "en": "Confirm", "id": "Konfirmasi"},
    "confirm_send": {"zh": "确认发送", "en": "Send", "id": "Kirim"},
    "confirm_run": {"zh": "确认执行", "en": "Confirm", "id": "Konfirmasi"},
    "cancel": {"zh": "取消", "en": "Cancel", "id": "Batal"},
    "not_needed": {"zh": "不用了", "en": "Not needed", "id": "Tidak perlu"},
    "done": {"zh": "我已处理", "en": "Done", "id": "Sudah ditangani"},
    "approve": {"zh": "批准", "en": "Approve", "id": "Setujui"},
    "reject": {"zh": "驳回", "en": "Reject", "id": "Tolak"},
    "draft_reply": {"zh": "起草回复", "en": "Draft reply", "id": "Buat draf balasan"},
    "mute": {"zh": "这类不用提醒", "en": "Don't remind me of these", "id": "Jangan ingatkan yang seperti ini"},
    "pending_confirm": {"zh": "✍️ 待确认：{x}", "en": "✍️ Needs your OK: {x}", "id": "✍️ Perlu konfirmasi: {x}"},
    "things_to_know": {"zh": "Relay｜{n} 件事需要你知道", "en": "Relay | {n} things you should know", "id": "Relay | {n} hal yang perlu Anda ketahui"},
    "update": {"zh": "Relay｜有新进展", "en": "Relay | Update", "id": "Relay | Ada perkembangan"},
}


def t(lang: str, key: str, **kwargs) -> str:
    entry = _STRINGS[key]
    return entry.get(lang, entry[DEFAULT]).format(**kwargs)


# 渲染卡片时的界面语言：在 push.render / 卡片回调入口按用户设置好，下层的按钮、标题直接取用
current: ContextVar[str] = ContextVar("relay_ui_language", default=DEFAULT)


def ui(key: str, **kwargs) -> str:
    return t(current.get(), key, **kwargs)
