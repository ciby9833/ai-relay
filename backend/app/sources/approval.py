"""本人待办、已办、发起与抄送审批；批准/驳回由用户点击确认后执行。"""

import json
import re
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.feishu.client import FeishuClient, FeishuError
from app.models import Signal, SourceState, User
from app.sources.base import add_signal, existing_ids

TOPIC_TODO = "1"
TOPICS = {"pending": "1", "done": "2", "initiated": "3", "cc_unread": "17", "cc_read": "18"}
PROCESS_LABELS = {"Running": "审批中", "Approved": "已通过", "Rejected": "已驳回", "Canceled": "已撤回", "Deleted": "已删除", "PENDING": "审批中", "APPROVED": "已通过", "REJECTED": "已驳回", "CANCELED": "已撤回", "DELETED": "已删除"}
PROCESS_LABELS.update({"0": "无流程状态", "1": "审批中", "2": "已通过", "3": "已驳回", "4": "已撤回"})
RUNNING = {"1", "Running", "PENDING"}
SENT_BACK = {"3", "4", "Rejected", "Canceled", "REJECTED", "CANCELED"}  # 驳回、撤回：要发起人处理
FIELD_LIMIT = 12
# 说明文字一类的控件本来就没有值，不算“待填写”
STATIC_WIDGETS = {"text", "description", "explain"}
# 当前节点名字里出现这些词，通常意味着审批人要分配、指派或补充内容，必须在飞书原生审批里处理
# （“部门负责人审批”这类普通节点不算）
INPUT_NODE = re.compile(r"分配|指派|指定处理|处理人|填写|补充|执行人|assign", re.I)


async def pending_tasks(feishu: FeishuClient, user: User) -> list[dict]:
    return await query_tasks(feishu, user, "pending")


async def query_tasks(feishu: FeishuClient, user: User, category: str) -> list[dict]:
    """官方 tasks/query：1 待办、2 已办、3 我发起、17/18 未读/已读抄送。完整分页后才返回。"""
    if category == "cc":
        rows = [{**r, "relay_cc_read": read} for read, key in ((False, "cc_unread"), (True, "cc_read"))
                for r in await query_tasks(feishu, user, key)]
        unique = {}
        for row in rows:
            unique.setdefault(row.get("task_id") or row.get("process_code"), row)
        return list(unique.values())
    if category not in TOPICS:
        raise FeishuError("未知审批分类")
    params = {"topic": TOPICS[category], "user_id": user.feishu_open_id, "user_id_type": "open_id", "page_size": 200}
    rows, seen = [], set()
    for _ in range(100):
        data = await feishu.tenant_api("GET", "/approval/v4/tasks/query", params=params)
        rows.extend(data.get("tasks") or [])
        token = data.get("page_token")
        if not token and not data.get("has_more"):
            return rows
        if not token or token in seen:
            raise FeishuError("审批分页响应不完整，保留已有跟进状态，下次重试")
        seen.add(token)
        params = {**params, "page_token": token}
    raise FeishuError("审批超过本轮分页上限，保留已有跟进状态")


def _value(value) -> str:
    """把表单控件的值压成一行文字（金额、日期、明细表等都可能是嵌套结构）。"""
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (list, dict)):
                return _value(parsed)
        except ValueError:
            pass
        return value.strip()
    if isinstance(value, list):
        if value and isinstance(value[0], list):  # 明细表：每行一组控件
            return f"{len(value)} 行明细"
        parts = [_value(v.get("value") if isinstance(v, dict) and "value" in v else v) for v in value]
        return "、".join(p for p in parts if p)[:200]
    if isinstance(value, dict):
        for key in ("text", "name", "value", "start", "amount"):
            if key in value:
                return _value(value[key])
        return json.dumps(value, ensure_ascii=False)[:200]
    return str(value)


# 考勤类“组合控件”（请假、补卡、出差、外出、加班、换班）：控件没有名字，值是一个对象，要拆成几行
GROUP_LABELS = {
    "leavegroup": "请假", "leavegroupv2": "请假", "remedygroup": "补卡", "remedygroupv2": "补卡",
    "tripgroup": "出差", "outgroup": "外出", "workgroup": "加班", "shiftgroup": "换班", "shiftgroupv2": "换班",
}
UNITS = {"DAY": "天", "HALF_DAY": "个半天", "HOUR": "小时"}


def _local(value: str, offset_minutes: int | None) -> datetime | None:
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return moment.astimezone(timezone(timedelta(minutes=-offset_minutes))) if offset_minutes is not None else moment


def leave_range(widget: dict) -> tuple[datetime, datetime] | None:
    """请假控件的起止时间（按天请假时，结束时间是最后一天的次日零点）。"""
    value = widget.get("value")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if (widget.get("type") or "").lower() not in ("leavegroup", "leavegroupv2") or not isinstance(value, dict):
        return None
    start, end = _local(value.get("start"), value.get("timezoneOffset")), _local(value.get("end"), value.get("timezoneOffset"))
    return (start, end) if start and end else None


def _when(value: str, offset_minutes: int | None, date_only: bool, inclusive_end: bool = False) -> str:
    """表单里的时间带着发起人填写时的时区；按表单给的 timezoneOffset（JS 写法，UTC+7 为 -420）换回当地时间。"""
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return str(value)
    if offset_minutes is not None:
        moment = moment.astimezone(timezone(timedelta(minutes=-offset_minutes)))
    if inclusive_end and date_only and (moment.hour, moment.minute) == (0, 0):
        moment -= timedelta(days=1)  # 按天请假：结束时间是次日零点，显示成最后一天
    weekday = "一二三四五六日"[moment.weekday()]
    return f"{moment:%m-%d} 周{weekday}" if date_only else f"{moment:%m-%d} 周{weekday} {moment:%H:%M}"


def group_fields(widget: dict) -> list[dict]:
    kind = (widget.get("type") or "").lower()
    value = widget.get("value")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if kind not in GROUP_LABELS or not isinstance(value, dict):
        return []
    label = GROUP_LABELS[kind]
    offset = value.get("timezoneOffset")
    date_only = value.get("unit") == "DAY"
    fields = []
    if value.get("name"):
        fields.append({"name": f"{label}类型", "value": str(value["name"])})
    if value.get("start") and value.get("end"):
        fields.append({"name": "时间", "value": f"{_when(value['start'], offset, date_only)} 至 {_when(value['end'], offset, date_only, inclusive_end=True)}"})
    for key, name in (("remedyTime", "补卡时间"), ("shiftTime", "换班时间"), ("returnTime", "还班时间")):
        if value.get(key):
            fields.append({"name": name, "value": _when(value[key], offset, False)})
    if value.get("interval"):
        fields.append({"name": "时长", "value": f"{value['interval']} {UNITS.get(value.get('unit'), value.get('unit') or '')}".strip()})
    if isinstance(value.get("schedule"), list) and value["schedule"]:
        fields.append({"name": "行程", "value": f"{len(value['schedule'])} 段"})
    if value.get("reason"):
        fields.append({"name": "事由", "value": str(value["reason"])[:300]})
    return fields


async def instance_detail(feishu: FeishuClient, instance_code: str, open_id: str | None = None) -> dict:
    data = await feishu.tenant_api(
        "GET", f"/approval/v4/instances/{instance_code}", params={"locale": "zh-CN", "user_id_type": "open_id"},
    )
    try:
        form = json.loads(data.get("form") or "[]")
    except ValueError:
        form = []
    fields, empty, leave = [], [], None
    for widget in form:
        leave = leave or leave_range(widget)
        grouped = group_fields(widget)
        if grouped:
            fields.extend(grouped)
            continue
        text = _value(widget.get("value"))
        if widget.get("name") and text:
            fields.append({"name": widget["name"], "value": text[:300]})
        elif widget.get("name") and (widget.get("type") or "").lower() not in STATIC_WIDGETS:
            empty.append(widget["name"])
    comments = [c.get("comment") for c in data.get("comment_list") or [] if c.get("comment")]
    started = data.get("start_time")
    # 当前轮到这个人审批的节点
    node = next(
        (t.get("node_name") for t in data.get("task_list") or []
         if t.get("status") == "PENDING" and (open_id is None or t.get("open_id") == open_id)),
        None,
    )
    hints = empty[:]
    if node and INPUT_NODE.search(node) and not hints:
        hints.append(f"当前节点「{node}」")
    return {
        "status": data.get("status"),
        "approval_name": data.get("approval_name"),
        "serial_number": data.get("serial_number"),
        "started_at": datetime.fromtimestamp(int(started) / 1000, UTC).isoformat() if started else None,
        "fields": fields[:FIELD_LIMIT],
        # 请假起止（ISO），用来看同一时间段团队里还有谁请假
        "leave": [leave[0].isoformat(), leave[1].isoformat()] if leave else None,
        "fields_total": len(fields),
        "fields_truncated": len(fields) > FIELD_LIMIT,
        "comments": comments[:5],
        "comments_total": len(comments),
        "node": node,
        # 需要审批人自己填写/分配：只能在飞书原生审批里处理，Relay 不提供直接批准
        "needs_input": bool(empty) or bool(node and INPUT_NODE.search(node)),
        "input_hint": "、".join(hints[:4]) or None,
    }


def needs_input(detail: dict | None) -> bool:
    """拿不到明细时保守处理：当作需要在飞书里处理。"""
    return detail is None or detail.get("needs_input", True)


def detail_text(detail: dict | None) -> str:
    if not detail:
        return ""
    return "\n".join(f"{f['name']}：{f['value']}" for f in detail.get("fields") or [])


async def sync(session: AsyncSession, feishu: FeishuClient, user: User, state: SourceState) -> int:
    tasks = await pending_tasks(feishu, user)
    known = await existing_ids(session, user, "approval", [t.get("task_id") for t in tasks if t.get("task_id")])
    created = 0
    current = []
    for task in tasks:
        task_id = task.get("task_id")
        if not task_id:
            continue
        current.append(task_id)
        if task_id in known:
            continue
        detail = None
        if task.get("process_code"):
            try:
                detail = await instance_detail(feishu, task["process_code"], user.feishu_open_id)
            except FeishuError:
                detail = None  # 缺权限时仍然提醒，只是没有明细
        initiators = "、".join(task.get("initiator_names") or [])
        urls = task.get("urls") or {}
        created += await add_signal(
            session, user, "approval", task_id,
            kind="approval_pending",
            title=task.get("title") or task.get("definition_name") or "审批",
            body="\n".join(p for p in [f"发起人：{initiators}" if initiators else "", detail_text(detail)] if p) or None,
            url=urls.get("pc") or urls.get("mobile"),
            payload={**task, "detail": detail},
            occurred_at=datetime.fromisoformat(detail["started_at"]) if detail and detail.get("started_at") else None,
            status="notify", importance="normal",
        )
    # 早先同步、明细缺失或还没判断过“是否需要补填”的单子补拉
    missing = (await session.execute(
        select(Signal).where(Signal.user_id == user.id, Signal.source == "approval",
                             Signal.external_id.in_(current or [""]),
                             Signal.payload["detail"]["needs_input"].astext.is_(None))
        .limit(5)
    )).scalars().all()
    for signal in missing:
        try:
            detail = await instance_detail(feishu, signal.payload["process_code"], user.feishu_open_id)
        except (FeishuError, KeyError):
            continue
        initiators = "、".join(signal.payload.get("initiator_names") or [])
        signal.payload = {**signal.payload, "detail": detail}
        signal.body = "\n".join(p for p in [f"发起人：{initiators}" if initiators else "", detail_text(detail)] if p) or None

    # 已经处理掉的审批标记完成
    await session.execute(
        update(Signal)
        .where(
            Signal.user_id == user.id, Signal.source == "approval",
            Signal.kind == "approval_pending",
            Signal.status.in_(["new", "notify", "notified", "digest", "digested", "tracked"]),
            Signal.external_id.not_in(current or [""]),
        )
        .values(status="done")
    )
    created += await sync_updates(session, feishu, user, state)
    return created


# 涉及个人的人事类审批：就算抄送给了他，也不进简报（简报会推到飞书，可能被旁人看到或转发）
PERSONAL = (
    "leave", "cuti", "izin", "sakit", "请假", "休假", "resign", "pengunduran", "离职", "辞职",
    "clock-in", "补卡", "考勤", "absen", "salary", "gaji", "payroll", "薪", "工资", "tunjangan", "补贴", "allowance",
    "bonus", "奖金", "medical", "体检", "医疗", "kesehatan", "lembur", "加班", "overtime", "mutasi", "调岗", "promosi", "晋升",
)


def is_personal(payload: dict) -> bool:
    name = f"{payload.get('definition_name') or ''} {payload.get('title') or ''}".lower()
    return any(word in name for word in PERSONAL)


def _update_status(category: str, process_status: str, initialized: bool) -> str:
    """抄送只是知会：不建事项、不推送，只留作简报素材和查询。
    我发起的：审批中静默放进“等别人”；有结果（通过/驳回/撤回）时告诉他；首次同步的历史结果只建档。"""
    if category == "cc":
        # 首次同步拿到的是历史抄送（可能是几年前的），只建档；之后新来的才进简报素材
        return "ignored" if initialized else "done"
    if process_status in RUNNING:
        return "digest"
    return "notify" if initialized else "done"


async def sync_updates(session: AsyncSession, feishu: FeishuClient, user: User, state: SourceState) -> int:
    """我发起的进入跟进（审批中等别人、驳回撤回等你、通过只告知）；抄送只建档供简报和查询。不改飞书的已读状态。"""
    created = 0
    initialized = (state.cursor or {}).get("approval_updates_initialized", False)
    for category in ("initiated", "cc"):
        rows = await query_tasks(feishu, user, category)
        seen = set()
        for task in rows:
            code = task.get("process_code") or task.get("process_external_id")
            if not code or code in seen:
                continue
            seen.add(code)
            external_id = f"{category}:{code}"
            signal = (await session.execute(select(Signal).where(
                Signal.user_id == user.id, Signal.source == "approval", Signal.external_id == external_id,
            ))).scalar_one_or_none()
            process_status = str(task.get("process_status", "unknown"))
            label = PROCESS_LABELS.get(process_status, process_status)
            title = task.get("title") or task.get("definition_name") or "审批"
            prefix = "我发起的审批" if category == "initiated" else "抄送我的审批"
            payload = {**task, "category": category, "process_status": process_status}
            urls = task.get("urls") or {}
            if signal is None:
                created += await add_signal(session, user, "approval", external_id,
                    kind="approval_update", title=f"{prefix}：{title}（{label}）",
                    body=f"当前结果：{label}", payload=payload, url=urls.get("pc") or urls.get("mobile"),
                    occurred_at=datetime.now(UTC), status=_update_status(category, process_status, initialized),
                    importance="normal")
            elif signal.payload.get("process_status") != process_status:
                old = signal.payload.get("process_status")
                signal.title = f"{prefix}：{title}（{label}）"
                signal.body = f"审批状态从「{PROCESS_LABELS.get(old, old)}」变为「{label}」"
                signal.payload = payload
                signal.status = _update_status(category, process_status, True)
                signal.occurred_at = datetime.now(UTC)
                created += 1
            elif signal.payload != payload:
                signal.payload = payload
    state.cursor = {**(state.cursor or {}), "approval_updates_initialized": True}
    return created


async def decide(feishu: FeishuClient, user: User, task: dict, approve: bool, comment: str = "") -> None:
    """以用户身份批准或驳回（应用身份调用，user_id 指定审批人本人）。"""
    await feishu.tenant_api(
        "POST", f"/approval/v4/tasks/{'approve' if approve else 'reject'}",
        params={"user_id_type": "open_id"},
        json={
            "approval_code": task["definition_code"],
            "instance_code": task["process_code"],
            "user_id": user.feishu_open_id,
            "task_id": task["task_id"],
            "comment": comment,
        },
    )
