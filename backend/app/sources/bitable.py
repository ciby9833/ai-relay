"""飞书多维表格：按字段名新增一条记录（例如每天提交工作餐、登记一条需求）。

模型只给“字段名 → 想填的值”（选项名、人名、日期文字），这里按字段类型换成飞书要的格式，
并校验选项是否存在、哪些字段由系统自动生成（创建人、创建时间）不能填。所有写入以用户本人身份执行。
"""

import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from app.feishu.client import FeishuClient, FeishuError
from app.models import User

TOKEN = re.compile(r"^[A-Za-z0-9_-]{5,128}$")

TEXT, NUMBER, SINGLE, MULTI, DATE, CHECKBOX, PERSON, PHONE, URL = 1, 2, 3, 4, 5, 7, 11, 13, 15
CREATED_TIME, CREATED_BY = 1001, 1003
# 系统生成或这里不支持填写的类型
READONLY = {17: "附件", 18: "单向关联", 19: "查找引用", 20: "公式", 21: "双向关联", 1001: "创建时间", 1002: "修改时间",
            1003: "创建人", 1004: "修改人", 1005: "自动编号"}


class BaseError(Exception):
    pass


def parse_target(base: str, table_id: str | None = None) -> tuple[str, str | None]:
    """多维表格链接或 app_token → (app_token, table_id)；链接里的 ?table= 作为默认数据表。"""
    base = base.strip()
    if base.startswith("http"):
        parsed = urlparse(base)
        match = re.fullmatch(r"/base/([A-Za-z0-9_-]+)/?", parsed.path)
        if not match:
            raise BaseError("这不是多维表格链接（/base/…）；知识库里的多维表格先用 read_feishu_doc 取到 app_token")
        table_id = table_id or (parse_qs(parsed.query).get("table") or [None])[0]
        base = match.group(1)
    if not TOKEN.match(base) or (table_id and not TOKEN.match(table_id)):
        raise BaseError("app_token 或 table_id 格式不对")
    return base, table_id


def explain(exc: FeishuError, *, writing: bool = False) -> str:
    message = str(exc)
    if exc.code == 99991679 or "required privileges" in message:
        return "Relay 应用还没有开通多维表格的" + ("编辑" if writing else "读取") + "权限（bitable:app），需要管理员开通并发布后重新登录"
    if exc.code in (1254302, 1254303, 91403, 403) or "permission" in message.lower() or "Forbidden" in message:
        return "你对这张多维表格没有" + ("编辑" if writing else "查看") + "权限，需要找表格所有者开通"
    return message


async def table_of(feishu: FeishuClient, user: User, app_token: str, table_id: str | None) -> dict:
    tables = (await feishu.user_api(user, "GET", f"/bitable/v1/apps/{app_token}/tables", params={"page_size": 100})).get("items") or []
    if not tables:
        raise BaseError("这个多维表格里没有数据表")
    if table_id is None:
        if len(tables) > 1:
            raise BaseError("有多张数据表，请指定 table_id：" + "、".join(f"{t['name']}（{t['table_id']}）" for t in tables))
        return tables[0]
    for table in tables:
        if table["table_id"] == table_id:
            return table
    raise BaseError(f"没有找到数据表 {table_id}")


async def fields_of(feishu: FeishuClient, user: User, app_token: str, table_id: str) -> list[dict]:
    data = await feishu.user_api(user, "GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields", params={"page_size": 100})
    return data.get("items") or []


def describe_fields(fields: list[dict]) -> str:
    """给模型看的字段清单：类型和可选项。"""
    lines = []
    for f in fields:
        kind = f["type"]
        if kind in READONLY:
            lines.append(f"- {f['field_name']}：{READONLY[kind]}（系统生成或不支持填写，不用填）")
            continue
        options = [o["name"] for o in (f.get("property") or {}).get("options") or []]
        label = {TEXT: "文字", NUMBER: "数字", SINGLE: "单选", MULTI: "多选", DATE: "日期", CHECKBOX: "勾选",
                 PERSON: "人员", PHONE: "电话", URL: "链接"}.get(kind, f"类型 {kind}")
        lines.append(f"- {f['field_name']}：{label}" + (f"，可选：{'、'.join(options)}" if options else ""))
    return "\n".join(lines)


def _option(value: str, options: list[str], field: str) -> str:
    text = str(value).strip()
    if text in options:
        return text
    loose = [o for o in options if text.lower() in o.lower() or o.lower() in text.lower()]
    if len(loose) == 1:
        return loose[0]
    hint = "、".join(options[:30])
    raise BaseError(f"「{field}」没有“{text}”这个选项" + (f"，匹配到多个：{'、'.join(loose)}" if loose else "") + f"。可选：{hint}")


async def convert(feishu: FeishuClient, user: User, fields: list[dict], values: dict, session=None) -> tuple[dict, dict]:
    """字段名 → 值 换成飞书的格式。返回 (要写入的 fields, 给用户看的 字段→文字)。"""
    by_name = {f["field_name"]: f for f in fields}
    out, shown = {}, {}
    for name, value in values.items():
        field = by_name.get(name)
        if field is None:
            raise BaseError(f"没有「{name}」这个字段。字段有：{'、'.join(by_name)}")
        kind = field["type"]
        if kind in READONLY:
            raise BaseError(f"「{name}」是{READONLY[kind]}，由系统生成，不能填写")
        if value in (None, ""):
            continue
        options = [o["name"] for o in (field.get("property") or {}).get("options") or []]
        if kind == SINGLE:
            out[name] = _option(value, options, name)
            shown[name] = out[name]
        elif kind == MULTI:
            items = value if isinstance(value, list) else re.split(r"[、,，]", str(value))
            out[name] = [_option(v, options, name) for v in items if str(v).strip()]
            shown[name] = "、".join(out[name])
        elif kind == NUMBER:
            try:
                out[name] = float(value)
            except (TypeError, ValueError):
                raise BaseError(f"「{name}」要填数字") from None
            shown[name] = str(value)
        elif kind == CHECKBOX:
            out[name] = value if isinstance(value, bool) else str(value).strip().lower() in ("是", "true", "yes", "1", "√", "勾选")
            shown[name] = "是" if out[name] else "否"
        elif kind == DATE:
            try:
                moment = datetime.fromisoformat(str(value))
            except ValueError:
                raise BaseError(f"「{name}」的日期要用 ISO 格式，例如 2026-10-20 或 2026-10-20T14:00") from None
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=ZoneInfo(user.timezone))
            out[name] = int(moment.timestamp() * 1000)
            shown[name] = f"{moment:%Y-%m-%d %H:%M}"
        elif kind == PERSON:
            names = value if isinstance(value, list) else re.split(r"[、,，]", str(value))
            people_ids, labels = [], []
            for who in [n.strip() for n in names if str(n).strip()]:
                if who in ("我", "me", "自己", user.name):
                    people_ids.append({"id": user.feishu_open_id})
                    labels.append(user.name)
                    continue
                from app.sources import people

                try:
                    found = await people.find(session, feishu, who, limit=1, user=user) if session is not None else []
                except people.Ambiguous as exc:
                    raise BaseError(f"「{name}」：有多个同名的人（{'、'.join(c['name'] for c in exc.candidates)}），请说明是哪一位") from None
                if not found:
                    raise BaseError(f"「{name}」：找不到 {who}")
                people_ids.append({"id": found[0]["open_id"]})
                labels.append(found[0]["name"])
            out[name] = people_ids
            shown[name] = "、".join(labels)
        elif kind == URL:
            out[name] = {"text": str(value), "link": str(value)}
            shown[name] = str(value)
        else:
            out[name] = str(value)
            shown[name] = str(value)
    if not out:
        raise BaseError("没有要填写的内容")
    return out, shown


async def my_latest(feishu: FeishuClient, user: User, app_token: str, table_id: str, fields: list[dict]) -> dict | None:
    """他本人在这张表里最近一次提交的记录（表里有“创建人”字段时才查得到），用来避免重复提交。"""
    creator = next((f["field_name"] for f in fields if f["type"] == CREATED_BY), None)
    created = next((f["field_name"] for f in fields if f["type"] == CREATED_TIME), None)
    if not creator:
        return None
    body = {"filter": {"conjunction": "and", "conditions": [{"field_name": creator, "operator": "is", "value": [user.feishu_open_id]}]},
            "automatic_fields": True}
    if created:
        body["sort"] = [{"field_name": created, "desc": True}]
    try:
        data = await feishu.user_api(user, "POST", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/search",
                                     params={"page_size": 1}, json=body)
    except FeishuError:
        return None
    items = data.get("items") or []
    return items[0] if items else None


async def add_record(feishu: FeishuClient, user: User, app_token: str, table_id: str, fields: dict, client_token: str) -> dict:
    data = await feishu.user_api(user, "POST", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
                                 params={"client_token": client_token}, json={"fields": fields})
    return data.get("record") or {}


async def delete_record(feishu: FeishuClient, user: User, app_token: str, table_id: str, record_id: str) -> None:
    await feishu.user_api(user, "DELETE", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}")
