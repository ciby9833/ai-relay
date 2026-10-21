"""各数据源的同步函数与轮询间隔（秒）。"""

from app.sources import approval, attendance, calendar, mail, p2p, tasks

SYNCERS = {
    "mail": (mail.sync, 120),
    "calendar": (calendar.sync, 300),
    "approval": (approval.sync, 300),
    "attendance": (attendance.sync, 300),
    # 私聊感知：默认关闭，用户在设置里开启才运行（需要“以用户身份读取单聊消息”的授权）
    "private_chat": (p2p.sync, 300),
    "task": (tasks.sync, 300),
}

# 需要用户单独授权的数据源（任一即可）：没授权时跳过并在设置页说明，不反复提醒他重新登录
REQUIRED_SCOPES = {
    "private_chat": ("im:message.p2p_msg:get_as_user",),
    "task": tasks.SCOPES,
}

# 不同数据源“这个人根本没有开通”的报错：跳过，隔一段时间再试（开通后自动恢复）。
# 飞书没开邮箱时返回 code=4013，子错误码 15180001 只出现在 msg 里（“[15180001] user not found”）
UNAVAILABLE = {"mail": ("15180001",)}


def unavailable(source: str, exc) -> bool:
    markers = UNAVAILABLE.get(source, ())
    return any(marker == str(exc.code) or f"[{marker}]" in str(exc) for marker in markers)
