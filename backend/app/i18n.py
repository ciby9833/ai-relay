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
    "done": {"zh": "已处理", "en": "Done", "id": "Sudah ditangani"},
    "no_follow": {"zh": "不用跟了", "en": "Stop tracking", "id": "Tidak perlu dipantau"},
    "why_no_follow": {"zh": "为什么不用跟了？", "en": "Why stop tracking?", "id": "Kenapa tidak perlu dipantau?"},
    "prep_none": {"zh": "没有找到这次会的议程、纪要或相关资料。可以问组织者要议程，或者在会议页面让 Relay 帮你再找。",
                  "en": "No agenda, minutes or related material found for this meeting. You could ask the organizer for an agenda, or ask Relay to look again from the Meetings page.",
                  "id": "Tidak ditemukan agenda, notulen, atau materi terkait rapat ini. Anda bisa meminta agenda ke penyelenggara, atau minta Relay mencari lagi dari halaman Rapat."},
    "moved_to_latest": {"zh": "已在最新的提醒里更新", "en": "Updated in the latest reminder", "id": "Diperbarui di pengingat terbaru"},
    "back": {"zh": "返回", "en": "Back", "id": "Kembali"},
    "fb_handled_before": {"zh": "提醒前就处理了", "en": "Already handled before", "id": "Sudah ditangani sebelumnya"},
    "fb_not_mine": {"zh": "不归我管", "en": "Not mine", "id": "Bukan urusan saya"},
    "fb_not_worth": {"zh": "不值得提醒", "en": "Not worth a reminder", "id": "Tidak perlu diingatkan"},
    "fb_quieter": {"zh": "这类以后少提醒", "en": "Fewer like this", "id": "Kurangi yang seperti ini"},
    "fb_duplicate": {"zh": "重复了", "en": "Duplicate", "id": "Duplikat"},
    "approve": {"zh": "批准", "en": "Approve", "id": "Setujui"},
    "reject": {"zh": "驳回", "en": "Reject", "id": "Tolak"},
    "draft_reply": {"zh": "起草回复", "en": "Draft reply", "id": "Buat draf balasan"},
    "mute": {"zh": "这类不用提醒", "en": "Don't remind me of these", "id": "Jangan ingatkan yang seperti ini"},
    "pending_confirm": {"zh": "✍️ 待确认：{x}", "en": "✍️ Needs your OK: {x}", "id": "✍️ Perlu konfirmasi: {x}"},
    "things_to_know": {"zh": "Relay｜{n} 件事需要你知道", "en": "Relay | {n} things you should know", "id": "Relay | {n} hal yang perlu Anda ketahui"},
    "confirm_and_grant": {"zh": "确认，以后直接办", "en": "Confirm & always do this", "id": "Konfirmasi & lakukan otomatis"},
    "undo": {"zh": "撤销", "en": "Undo", "id": "Batalkan"},
    "undone": {"zh": "已撤销", "en": "Undone", "id": "Dibatalkan"},
    "auto_done": {"zh": "已按你的授权自动办理", "en": "Done automatically as you authorized", "id": "Dikerjakan otomatis sesuai izin Anda"},
    "update": {"zh": "Relay｜有新进展", "en": "Relay | Update", "id": "Relay | Ada perkembangan"},
    "digest": {"zh": "Relay 汇总｜{n} 件不急的事", "en": "Relay digest | {n} things, nothing urgent", "id": "Ringkasan Relay | {n} hal, tidak mendesak"},
    "also_pending": {"zh": "不急的，顺便看一眼", "en": "Not urgent, while you're here", "id": "Tidak mendesak, sekalian"},
    "quieter": {"zh": "少提醒这类", "en": "Fewer like this", "id": "Kurangi yang seperti ini"},
    "level_now": {"zh": "立刻告诉我", "en": "Tell me right away", "id": "Beri tahu segera"},
    "level_batch": {"zh": "攒着一起说", "en": "Bundle into digests", "id": "Kumpulkan di ringkasan"},
    "level_brief": {"zh": "只放进早上简报", "en": "Morning brief only", "id": "Hanya di ringkasan pagi"},
    "level_mute": {"zh": "不提醒，只在看板里跟踪", "en": "Don't notify, just track on the board", "id": "Jangan beri tahu, cukup lacak di papan"},
    "more_on_web": {"zh": "内容太多，还有 {n} 项在网页看板里", "en": "Too much to show here — {n} more on the web board", "id": "Terlalu banyak — {n} lagi di papan web"},
    "final_fallback": {"zh": "这次查了 {n} 次还没找到能确定回答你的信息。你能告诉我大概在哪个群、哪封邮件或哪份文档里吗？我直接去那里看。",
                       "en": "I checked {n} times and still couldn't find enough to answer this reliably. Could you tell me which chat, email or document it's in? I'll look there directly.",
                       "id": "Saya sudah mencari {n} kali tapi belum menemukan informasi yang cukup untuk menjawab dengan pasti. Bisa beri tahu di grup, email, atau dokumen mana? Saya akan langsung cek di sana."},
    "rule_accept": {"zh": "启用", "en": "Turn on", "id": "Aktifkan"},
    "rule_reject": {"zh": "不用", "en": "No thanks", "id": "Tidak perlu"},
    "rule_enabled": {"zh": "已启用", "en": "On", "id": "Aktif"},
    "rule_ignored": {"zh": "不用了", "en": "Dismissed", "id": "Diabaikan"},
    "rule_evidence": {"zh": "依据：以前你说过", "en": "Based on what you said before:", "id": "Berdasarkan yang pernah Anda katakan:"},
    "rule_set": {"zh": "好的，以后{what}：{level}。可以在网页“提醒设置”里随时改。", "en": "Got it — from now on {what}: {level}. You can change this anytime in Settings on the web.", "id": "Baik — mulai sekarang {what}: {level}. Bisa diubah kapan saja di Pengaturan web."},
}


def t(lang: str, key: str, **kwargs) -> str:
    entry = _STRINGS[key]
    return entry.get(lang, entry[DEFAULT]).format(**kwargs)


# 渲染卡片时的界面语言：在 push.render / 卡片回调入口按用户设置好，下层的按钮、标题直接取用
current: ContextVar[str] = ContextVar("relay_ui_language", default=DEFAULT)


def ui(key: str, **kwargs) -> str:
    return t(current.get(), key, **kwargs)
