"""各数据源的同步函数与轮询间隔（秒）。"""

from app.sources import approval, attendance, calendar, mail, p2p

SYNCERS = {
    "mail": (mail.sync, 120),
    "calendar": (calendar.sync, 300),
    "approval": (approval.sync, 300),
    "attendance": (attendance.sync, 300),
    # 私聊感知：默认关闭，用户在设置里开启才运行（需要“以用户身份读取单聊消息”的授权）
    "private_chat": (p2p.sync, 300),
}

# 不同数据源“这个人根本没有开通”的报错：跳过，隔一段时间再试（开通后自动恢复）
UNAVAILABLE = {"mail": {15180001}}
