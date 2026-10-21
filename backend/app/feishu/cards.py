"""飞书交互卡片（JSON 2.0）。按钮点击通过 card.action.trigger 回调回来。

卡片正文是飞书的富文本（markdown）组件：* _ ~ < > [ ] 等字符有语法含义，按官方文档要转成 &#编号; 才能原样显示。
所以放进卡片的业务内容（邮件主题和正文、审批表单、人名、群消息……）一律先 esc()：
否则 PT_JNT_A 会变成斜体、“<5 天”会被当成标签吞掉，邮件里写的 [点击确认](http://…) 还会在 Relay 的卡片上变成可点的链接。
Relay 自己或模型写的说明文字用 safe_md()：保留加粗、颜色，但只有飞书和 Relay 自己的链接能点。
"""

import json
import re
from urllib.parse import urlparse

# 卡片 JSON 上限 30 KB（官方限制），留一点余量
CARD_LIMIT = 28_000

_ESCAPES = {"<": "&#60;", ">": "&#62;", "*": "&#42;", "_": "&#95;", "~": "&sim;", "[": "&#91;", "]": "&#93;",
            "`": "&#96;", "#": "&#35;", "|": "&#124;", "\\": "&#92;"}
_ESCAPE = re.compile("|".join(re.escape(c) for c in _ESCAPES) + r"|&(?=#?\w+;)")
_TAG = re.compile(r"</?font(?:\s+color=['\"]?[\w#(),. ]+['\"]?)?>|<br>")
_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
SAFE_HOSTS = ("feishu.cn", "larksuite.com", "larkoffice.com", "feishu.net")


def esc(text: object) -> str:
    """业务内容原样显示：把有 markdown 含义的字符转成 HTML 实体（& 只在会被当成实体时才转）。"""
    return _ESCAPE.sub(lambda m: _ESCAPES.get(m.group(0), "&#38;"), str(text or ""))


def _safe_host(url: str, extra: tuple[str, ...]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in SAFE_HOSTS + extra)


def safe_md(text: str, extra_hosts: tuple[str, ...] = ()) -> str:
    """Relay/模型写的说明：保留 **加粗**、<font color> 和指向飞书或 Relay 的链接；其他标签原样显示，别的链接不可点。"""
    keep: list[str] = []

    def hold(value: str) -> str:
        keep.append(value)
        return f"\0{len(keep) - 1}\0"

    text = re.sub(r"```.*?```|`[^`\n]+`", lambda m: hold(m.group(0)), text or "", flags=re.S)  # 代码里的字符原样保留
    text = _TAG.sub(lambda m: hold(m.group(0)), text)
    text = _LINK.sub(lambda m: hold(m.group(0)) if _safe_host(m.group(2), extra_hosts) else f"{m.group(1)}（{m.group(2)}）", text)
    text = text.replace("<", "&#60;").replace(">", "&#62;").replace("[", "&#91;")
    return re.sub(r"\0(\d+)\0", lambda m: keep[int(m.group(1))], text)


def plain(text: str) -> str:
    """卡片发不出去时退回纯文本：去掉标签和 markdown 记号，还原转义。"""
    import html

    text = re.sub(r"</?font[^>]*>", "", text or "")
    text = _LINK.sub(lambda m: f"{m.group(1)} {m.group(2)}", text)
    text = text.replace("**", "").replace("~~", "")
    return html.unescape(text.replace("&sim;", "~"))


def size(card: dict) -> int:
    return len(json.dumps(card, ensure_ascii=False).encode())


def _button(text: str, *, value: dict | None = None, url: str | None = None, style: str = "default") -> dict:
    behavior = {"type": "callback", "value": value} if value else {"type": "open_url", "default_url": url}
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": style,
        "behaviors": [behavior],
    }


def callback(text: str, action: str, style: str = "default", **params) -> dict:
    return _button(text, value={"relay": action, **params}, style=style)


def link(text: str, url: str, style: str = "default") -> dict:
    return _button(text, url=url, style=style)


def markdown(text: str) -> dict:
    return {"tag": "markdown", "content": text}


def button_row(buttons: list[dict]) -> dict:
    return {
        "tag": "column_set",
        "flex_mode": "flow",
        "horizontal_spacing": "8px",
        "columns": [{"tag": "column", "width": "auto", "elements": [button]} for button in buttons],
    }


def divider() -> dict:
    return {"tag": "hr"}


def card(
    title: str, text: str, buttons: list[dict] | None = None, template: str = "blue",
    elements: list[dict] | None = None,
) -> dict:
    """elements 给出时按它排版（每一项下面跟自己的按钮）；否则是一段文字加一排按钮。"""
    if elements is None:
        elements = [markdown(text)] + ([button_row(buttons)] if buttons else [])
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {"title": {"tag": "plain_text", "content": title[:100]}, "template": template},
        "body": {"elements": elements},
    }
