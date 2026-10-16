"""各数据源的同步函数与轮询间隔（秒）。"""

from app.sources import approval, attendance, calendar, mail

SYNCERS = {
    "mail": (mail.sync, 120),
    "calendar": (calendar.sync, 300),
    "approval": (approval.sync, 300),
    "attendance": (attendance.sync, 300),
}
