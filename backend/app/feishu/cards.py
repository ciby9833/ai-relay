"""飞书交互卡片（JSON 2.0）。按钮点击通过长连接的 card.action.trigger 回调回来。"""


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
