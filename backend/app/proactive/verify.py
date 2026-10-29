"""写入后核对：执行成功不等于写对了。写完按对象读回来对一遍，结果记在操作上（payload.verified）。

    ok=True   读回来和要写的一致
    ok=False  读回来不一致（例如表格单元格的值不对、记录里缺字段、消息不存在）：告诉用户，长期任务不能拿它当证据
    ok=None   这次没能核对（没有读回接口、读的时候出错）：不当作失败，但会如实写明“未核对”

参考：“给出运行结果作为证据，而不是说做完了”（Claude Code 团队的 code review 实践）。
"""

import logging
from datetime import UTC, datetime

from app.feishu.client import FeishuClient
from app.models import PendingAction, User

logger = logging.getLogger("relay.verify")


def _norm(value) -> str:
    text = "" if value is None else str(value)
    return text.strip().replace("\r\n", "\n")


def _field_text(value) -> str:
    """多维表格读回来的字段可能是文本、数字、选项列表、人员对象……统一成可比较的文字。"""
    if isinstance(value, list):
        return "、".join(_field_text(v) for v in value)
    if isinstance(value, dict):
        for key in ("text", "name", "value", "link"):
            if key in value:
                return _norm(value[key])
        raise ValueError("暂不支持比较此字段类型")
    return _norm(value)


async def check(feishu: FeishuClient, user: User, action: PendingAction) -> dict | None:
    p = action.payload or {}
    if action.kind == "cloud_write" and p.get("operation") == "fill_sheet_cells":
        from app.sources import sheets

        now = await sheets.read_cells(feishu, user, p["spreadsheet_token"], p["sheet_id"], [c["cell"] for c in p["cells"]])
        wrong = [f"{c['cell']} 是“{_norm(now.get(c['cell']))[:40]}”" for c in p["cells"] if _norm(now.get(c["cell"])) != _norm(c["after"])]
        return {"ok": not wrong, "detail": ("读回 " + "、".join(c["cell"] for c in p["cells"]) + " 与填写的一致") if not wrong
                else "读回不一致：" + "；".join(wrong)}
    if action.kind == "cloud_write":
        return await _cloud(feishu, user, p.get("operation"), p.get("arguments") or {}, p.get("response") or {})
    if action.kind == "base_record":
        if not p.get("record_id"):
            return {"ok": False, "detail": "飞书没有返回记录编号"}
        data = await feishu.user_api(user, "GET", f"/bitable/v1/apps/{p['app_token']}/tables/{p['table_id']}/records/{p['record_id']}")
        fields = (data.get("record") or {}).get("fields") or {}
        wrong = [name for name, value in (p.get("fields") or {}).items()
                 if _field_text(fields.get(name)) != _field_text(value)]
        return {"ok": not wrong, "detail": f"读回记录 {p['record_id']}，字段值一致" if not wrong else "读回记录字段值不一致：" + "、".join(wrong)}
    if action.kind == "send_chat":
        message_id = p.get("message_id")
        if not message_id:
            return {"ok": False, "detail": "飞书没有返回消息编号，消息可能没有发出"}
        path = f"/im/v1/messages/{message_id}"
        data = await (feishu.user_api(user, "GET", path) if p.get("as_user") else feishu.tenant_api("GET", path))
        items = data.get("items") or []
        ok = bool(items) and not items[0].get("deleted")
        return {"ok": ok, "detail": f"消息 {message_id} 已在会话里" if ok else f"读不到消息 {message_id}（可能被撤回或删除）"}
    if action.kind == "create_task":
        guid = (p.get("task") or {}).get("guid")
        if not guid:
            return {"ok": False, "detail": "飞书没有返回任务编号"}
        task = (await feishu.user_api(user, "GET", f"/task/v2/tasks/{guid}")).get("task") or {}
        ok = _norm(task.get("summary")) == _norm(p.get("subject"))
        return {"ok": ok, "detail": f"读回任务 {guid}" + ("，标题一致" if ok else f"，标题是“{task.get('summary')}”")}
    if action.kind == "create_event":
        event = p.get("event") or {}
        return {"ok": None, "detail": "飞书返回了日程编号，但尚未独立回读"} if event.get("event_id") or event.get("id") else {"ok": False, "detail": "飞书没有返回日程编号"}
    return None  # 发邮件、回复邀请、审批等：飞书接口返回成功即已生效，暂无单独的读回核对


async def record(feishu: FeishuClient, user: User, action: PendingAction) -> dict | None:
    """核对并记在操作上；核对本身出错时记为“未核对”，不影响操作已经完成这件事。"""
    try:
        outcome = await check(feishu, user, action)
    except Exception as exc:  # noqa: BLE001
        logger.warning("核对操作 #%s 失败：%s", action.id, exc)
        outcome = {"ok": None, "detail": f"没能核对（{str(exc)[:120]}）"}
    if outcome is not None:
        action.payload = {**(action.payload or {}), "verified": {**outcome, "at": datetime.now(UTC).isoformat()}}
    return outcome


def _compact(text) -> str:
    return "".join(_norm(text).split())


async def _doc_text(feishu: FeishuClient, user: User, document_id: str) -> str:
    data = await feishu.user_api(user, "GET", f"/docx/v1/documents/{document_id}/raw_content")
    return data.get("content") or ""


async def _cloud(feishu: FeishuClient, user: User, operation: str | None, args: dict, response: dict) -> dict | None:
    """云文档、表格、多维表格的写入：读回来对一遍，产出物（新建的文档/表格）确认真的存在、能打开。"""
    if operation in ("append_doc_text", "replace_doc_block_text"):
        content = await _doc_text(feishu, user, args["document_id"])
        expected = _compact(args.get("text"))
        ok = bool(expected) and expected[:200] in _compact(content)
        return {"ok": ok, "detail": "读回文档，写入的内容已在文档里" if ok else "读回文档，没有找到写入的内容"}
    if operation == "create_doc":
        doc_id = ((response or {}).get("document") or {}).get("document_id")
        if not doc_id:
            return {"ok": False, "detail": "飞书没有返回文档编号"}
        doc = (await feishu.user_api(user, "GET", f"/docx/v1/documents/{doc_id}")).get("document") or {}
        ok = _norm(doc.get("title")) == _norm(args.get("title"))
        return {"ok": ok, "detail": f"读回文档 {doc_id}" + ("，标题一致" if ok else f"，标题是“{doc.get('title')}”")}
    if operation == "write_sheet_range":
        data = await feishu.user_api(user, "GET", f"/sheets/v2/spreadsheets/{args['spreadsheet_token']}/values/{args['range']}",
                                     params={"valueRenderOption": "ToString"})
        got = (data.get("valueRange") or {}).get("values") or []
        wrong = []
        for r, row in enumerate(args.get("values") or []):
            for c, want in enumerate(row):
                if isinstance(want, dict):
                    continue  # 公式：读回的是计算结果，不逐字比较
                have = got[r][c] if r < len(got) and c < len(got[r]) else None
                if _norm(have) != _norm(want):
                    wrong.append(f"第 {r + 1} 行第 {c + 1} 列是“{_norm(have)[:30]}”")
        return {"ok": not wrong, "detail": f"读回 {args['range']} 与写入的一致" if not wrong else "读回不一致：" + "；".join(wrong[:5])}
    if operation == "create_sheet":
        token = ((response or {}).get("spreadsheet") or {}).get("spreadsheet_token")
        if not token:
            return {"ok": False, "detail": "飞书没有返回表格编号"}
        sheet = (await feishu.user_api(user, "GET", f"/sheets/v3/spreadsheets/{token}")).get("spreadsheet") or {}
        return {"ok": bool(sheet), "detail": f"读回表格 {token}" + (f"《{sheet.get('title')}》" if sheet.get("title") else "")}
    if operation == "create_base":
        token = ((response or {}).get("app") or {}).get("app_token")
        if not token:
            return {"ok": False, "detail": "飞书没有返回多维表格编号"}
        app = (await feishu.user_api(user, "GET", f"/bitable/v1/apps/{token}")).get("app") or {}
        return {"ok": bool(app), "detail": f"读回多维表格 {token}"}
    if operation in ("create_base_record", "update_base_record"):
        record_id = ((response or {}).get("record") or {}).get("record_id") or args.get("record_id")
        if not record_id:
            return {"ok": False, "detail": "飞书没有返回记录编号"}
        data = await feishu.user_api(user, "GET", f"/bitable/v1/apps/{args['app_token']}/tables/{args['table_id']}/records/{record_id}")
        fields = (data.get("record") or {}).get("fields") or {}
        wrong = [name for name, value in (args.get("fields") or {}).items() if _field_text(fields.get(name)) != _field_text(value)]
        return {"ok": not wrong, "detail": f"读回记录 {record_id}，字段值一致" if not wrong else "读回记录字段值不一致：" + "、".join(wrong)}
    return None
