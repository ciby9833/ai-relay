"""连接器清单：每个外部系统（以及 Relay 自身、Mac 客户端）有哪些数据源、事件、工具，各自的输入输出、副作用和授权。

这是唯一的权威清单：
- 测试保证代码里注册的每个工具、每个数据源都在这里有条目（反过来也一样）；
- docs/CONNECTORS.md 由它生成（python -m app.connectors.catalog），测试保证文档和清单一致；
- 工具执行时按这里的副作用等级检查（见 app/agent/tools/base.py）。

副作用等级：
- read     只读，不改任何东西
- prepare  只准备一个待确认操作（卡片），本人确认后才执行
- write    执行已经准备好、本人确认过的操作（只有 confirm_action）
- create   新建一份东西（生成文件、存进云空间 / 本机），只新建、不覆盖，做完回读核对
- state    改助理自己的状态（记忆、提醒规则、定时任务、长期任务、事项），不对外
"""

from dataclasses import dataclass, field

EFFECTS = ("read", "prepare", "write", "create", "state")


@dataclass(frozen=True)
class Source:
    """后台同步的数据源：产出 Signal。"""

    name: str
    connector: str
    capability: str
    how: str  # 同步方式
    kinds: tuple[str, ...]  # 产出的 Signal.kind
    auth: str  # 用谁的身份读
    providers: tuple[str, ...] = ("feishu",)  # 可以由哪些接入提供（标准邮箱 / 日历订阅也能提供邮件 / 日历）
    note: str = ""


@dataclass(frozen=True)
class Event:
    """外部系统推来的事件。"""

    name: str
    connector: str
    entry: str  # 从哪里进来
    check: str  # 怎么校验来源
    dedupe: str  # 去重键
    lands: str  # 落到哪里


@dataclass(frozen=True)
class ToolContract:
    name: str
    connector: str  # feishu | relay | mac
    capability: str  # 属于哪类能力（mail / calendar / approval / ...）
    effect: str  # 见 EFFECTS
    errors: tuple[str, ...] = field(default_factory=tuple)  # 可能出现的错误码（除通用的 invalid_input / internal 外）
    usage: str = ""  # 使用约定（前置条件、和别的工具怎么配合），会附在工具说明后面给模型，也写进文档


SOURCES = [
    Source("mail", "feishu", "mail", "轮询 2 分钟：收件箱最近 20 封 + 已发送最近 20 封", ("mail", "mail_sent"), "他本人（用户令牌）",
           ("feishu", "imap"), "接了标准邮箱就用标准邮箱"),
    Source("calendar", "feishu", "calendar", "轮询 5 分钟：未来 3 天的日程和待回复邀请", ("meeting", "invitation"), "他本人（用户令牌）",
           ("feishu", "ics"), "日历订阅（ICS）只读，不产生待回复邀请"),
    Source("approval", "feishu", "approval", "轮询 5 分钟：待我审批、我发起的进展", ("approval_pending", "approval_update"), "他本人（用户令牌）"),
    Source("attendance", "feishu", "attendance", "轮询 5 分钟：今天缺卡", ("attendance_missing",), "应用（需要员工号）"),
    Source("task", "feishu", "task", "轮询 5 分钟：派给他的飞书任务", ("task",), "他本人（用户令牌，task:task:read）"),
    Source("private_chat", "feishu", "im", "轮询 5 分钟：他和常联系同事的私聊（本人开启后）", ("私聊消息，只归本人",),
           "他本人（以用户身份读私聊）", note="默认关闭"),
]

EVENTS = [
    Event("群消息", "feishu", "长连接（默认工作区）/ /api/feishu/events/{工作区}", "verification token + 加密；只认工作区绑定的飞书企业",
          "event_id", "群消息存档（按工作区）；@他 → mention 信号；@机器人 → 对话"),
    Event("机器人私聊", "feishu", "同上", "同上", "event_id", "他的首页对话"),
    Event("卡片按钮", "feishu", "同上", "同上；只在本工作区找点按钮的人", "按钮所在卡片 + 操作", "执行对应操作，原地更新卡片"),
    Event("业务系统事件", "business", "/api/inbound/{key}", "HMAC-SHA256 签名（X-Relay-Timestamp + X-Relay-Signature）", "integration + event_id", "收件人的待处理（biz_event）"),
]

_T = ToolContract
TOOLS = [
    # 飞书：邮件
    _T("search_mail", "feishu", "mail", "read", ("not_connected", "needs_reauth", "limit")),
    _T("list_mail_folder", "feishu", "mail", "read", ("not_connected", "needs_reauth")),
    _T("read_mail", "feishu", "mail", "read", ("not_found", "needs_reauth")),
    _T("read_mail_attachment", "feishu", "mail", "read", ("not_found", "unsupported")),
    _T("draft_mail_reply", "feishu", "mail", "prepare", ("not_found",), "用原邮件的语言写。"),
    _T("draft_mail_forward", "feishu", "mail", "prepare", ("not_found",), "附言用收件人的语言写。"),
    _T("revise_draft", "relay", "actions", "prepare", ("not_found", "conflict")),
    # 飞书：日历与会议
    _T("list_calendar_events", "feishu", "calendar", "read", ("not_connected", "needs_reauth")),
    _T("respond_to_invitation", "feishu", "calendar", "prepare", ("not_found", "unsupported")),
    _T("find_meeting_times", "feishu", "calendar", "read", ("needs_reauth",)),
    _T("prepare_meeting", "feishu", "calendar", "prepare", ()),
    _T("get_meeting_responses", "feishu", "calendar", "read", ("not_found", "unsupported")),
    _T("prepare_reschedule", "feishu", "calendar", "prepare", ("not_found", "unsupported")),
    _T("prepare_cancel_meeting", "feishu", "calendar", "prepare", ("not_found", "unsupported")),
    _T("prepare_add_attendees", "feishu", "calendar", "prepare", ("not_found", "unsupported")),
    # 飞书：审批
    _T("list_pending_approvals", "feishu", "approval", "read", ("needs_reauth",)),
    _T("get_approval_detail", "feishu", "approval", "read", ("not_found",)),
    _T("decide_approval", "feishu", "approval", "prepare", ("not_found", "conflict")),
    _T("query_my_approvals", "feishu", "approval", "read", ("needs_reauth",)),
    _T("read_my_approval", "feishu", "approval", "read", ("not_found",)),
    # 飞书：考勤
    _T("attendance_today", "feishu", "attendance", "read", ("app_scope",)),
    # 飞书：消息、群、同事
    _T("find_person", "feishu", "contact", "read", ()),
    _T("find_chats", "feishu", "im", "read", ("limit",)),
    _T("read_chat_messages", "feishu", "im", "read", ("no_access", "not_found")),
    _T("prepare_chat_message", "feishu", "im", "prepare", (), "用你们往来时用的语言写；看不出来时用英文或问他。"),
    # 飞书：通讯录与组织架构
    _T("search_departments", "feishu", "contact", "read", ("app_scope",), "实时查通讯录，不要从邮件里推测。"),
    _T("list_department_members", "feishu", "contact", "read", ("app_scope",)),
    _T("person_profile", "feishu", "contact", "read", ("not_found",), "实时查通讯录，不要从邮件里推测职位和上级。"),
    # 飞书：任务
    _T("prepare_task", "feishu", "task", "prepare", ()),
    # 飞书：云文档、表格、多维表格、云空间
    _T("search_docs", "feishu", "docs", "read", ("needs_reauth", "limit"), "返回的只是片段，不能拼起来当原文；有链接时直接用 read_feishu_doc。"),
    _T("read_feishu_doc", "feishu", "docs", "read", ("no_access", "not_found", "unsupported")),
    _T("list_sheet_tabs", "feishu", "sheets", "read", ("app_scope", "no_access", "not_found")),
    _T("read_sheet_range", "feishu", "sheets", "read", ("app_scope", "no_access", "not_found")),
    _T("prepare_fill_sheet_cells", "feishu", "sheets", "prepare", ("app_scope", "no_access", "not_found"), "先用 read_sheet_range 读表头和相关行。"),
    _T("list_base_fields", "feishu", "base", "read", ("app_scope", "no_access", "not_found")),
    _T("prepare_add_base_record", "feishu", "base", "prepare", ("app_scope", "no_access")),
    _T("list_base_tables", "feishu", "base", "read", ("app_scope", "no_access", "not_found")),
    _T("list_base_records", "feishu", "base", "read", ("app_scope", "no_access", "not_found")),
    _T("list_drive_files", "feishu", "drive", "read", ("app_scope", "no_access", "not_found")),
    _T("list_wiki_spaces", "feishu", "wiki", "read", ("app_scope",)),
    _T("list_wiki_nodes", "feishu", "wiki", "read", ("app_scope", "no_access", "not_found")),
    _T("prepare_create_doc", "feishu", "docs", "prepare", ("app_scope", "no_access")),
    _T("prepare_append_doc_text", "feishu", "docs", "prepare", ("app_scope", "no_access", "not_found"), "先读原文确认目标位置。"),
    _T("save_file_to_drive", "feishu", "drive", "create", ("not_found", "app_scope", "no_access")),
    # Relay：生成文件
    _T("create_excel_file", "relay", "files", "create", (), "先把真实数据查到再生成，sources 写清来源；核对只证明文件写对了，不证明数据对，回复里分开说。"),
    _T("create_ppt_file", "relay", "files", "create", (), "先把真实数据查到再生成，sources 写清来源；核对只证明文件写对了，不证明数据对，回复里分开说。"),
    _T("create_word_file", "relay", "files", "create", (), "先把真实数据查到再生成，sources 写清来源；核对只证明文件写对了，不证明数据对，回复里分开说。"),
    # Relay：确认执行（唯一的 write）
    _T("confirm_action", "relay", "actions", "write", ("not_found", "conflict", "needs_reauth", "app_scope", "no_access")),
    # Relay：待处理事项
    _T("list_followups", "relay", "followups", "read", ()),
    _T("open_case", "relay", "followups", "read", ("not_found",)),
    _T("close_followup", "relay", "followups", "state", ("not_found",), "对方要的东西还没交付（例如要他填表、交材料），只是发了消息说明情况时不要关闭。"),
    # Relay：记忆、提醒规则、定时任务
    _T("remember", "relay", "memory", "state", ("invalid_input",), "只记以后还用得上的（岗位、负责的项目和客户、偏好、重要决定）；提醒偏好用 set_notify_rule；密码、密钥、证件号码不记（会被拒绝）。"),
    _T("forget", "relay", "memory", "state", ("not_found",)),
    _T("search_memory", "relay", "memory", "read", ()),
    _T("set_notify_rule", "relay", "attention", "state", ()),
    _T("list_notify_rules", "relay", "attention", "read", (), "他问“为什么这件事没马上告诉我”时看这里和事项上的提醒档位。"),
    _T("delete_notify_rule", "relay", "attention", "state", ("not_found",)),
    _T("create_scheduled_task", "relay", "tasks", "state", (), "创建后告诉他下一次执行的时间。"),
    _T("list_scheduled_tasks", "relay", "tasks", "read", ()),
    _T("delete_scheduled_task", "relay", "tasks", "state", ("not_found",)),
    # Relay：长期任务
    _T("start_mission", "relay", "missions", "state", ()),
    _T("edit_mission_criteria", "relay", "missions", "state", ("not_found",)),
    _T("list_missions", "relay", "missions", "read", ()),
    _T("answer_mission", "relay", "missions", "state", ("not_found",)),
    _T("cancel_mission", "relay", "missions", "state", ("not_found",)),
    _T("update_plan", "relay", "missions", "state", ()),
    _T("save_notes", "relay", "missions", "state", ()),
    _T("report_progress", "relay", "missions", "state", ()),
    _T("ask_user", "relay", "missions", "state", ()),
    _T("wait_until", "relay", "missions", "state", ()),
    _T("wait_for_reply", "relay", "missions", "state", ()),
    _T("check_criterion", "relay", "missions", "state", ("conflict",)),
    _T("complete_mission", "relay", "missions", "state", ("conflict",)),
    # Relay：和同事的协作委托
    _T("list_collaborations", "relay", "collab", "read", ()),
    _T("get_collaboration", "relay", "collab", "read", ("not_found",)),
    _T("request_colleague", "relay", "collab", "prepare", ("not_found",)),
    _T("respond_collaboration", "relay", "collab", "prepare", ("conflict", "not_found")),
    # Mac 客户端：授权文件夹
    _T("local_folders", "mac", "local_files", "read", ()),
    _T("list_local_files", "mac", "local_files", "read", ("offline", "not_connected", "no_access")),
    _T("read_local_file", "mac", "local_files", "read", ("offline", "not_connected", "no_access", "not_found", "unsupported")),
    _T("save_file_to_mac", "mac", "local_files", "create", ("offline", "not_connected", "no_access", "not_found")),
    _T("open_local_project", "mac", "local_files", "read", ("offline", "not_connected", "no_access")),
    _T("compare_local_tables", "mac", "local_skills", "create", ("offline", "not_connected", "no_access", "not_found", "unsupported"),
       "两张表都要先确认关键列（例如先 read_local_file 看表头）；结果只给数量和示例，完整差异在生成的文件里。"),
    _T("summarize_local_table", "mac", "local_skills", "create", ("offline", "not_connected", "no_access", "not_found", "unsupported"),
       "先 read_local_file 看表头确认列名。"),
]

CONTRACTS = {t.name: t for t in TOOLS}
# 同一轮里最多查几次的查找类工具（超过返回 limit，停下来问他资料在哪）
SEARCH_LIMIT = 3
SEARCH_TOOLS = ("search_mail", "search_docs", "find_chats")

CONNECTORS = {
    "feishu": "飞书（工作区管理员接入应用；成员登录时授权）",
    "relay": "Relay 自身（不对外的能力：生成文件、待处理事项、记忆、提醒、定时任务、长期任务、协作委托）",
    "mac": "Mac 客户端（成员授权的本机文件夹）",
    "business": "业务系统（工作区管理员登记，事件推入）",
}
EFFECT_TEXT = {"read": "只读", "prepare": "准备，本人确认后执行", "write": "执行已确认的操作", "create": "新建（不覆盖，回读核对）",
               "state": "改助理自己的状态"}


def render_markdown() -> str:
    """生成 docs/CONNECTORS.md。"""
    from app.agent.tools.base import TOOLS as REGISTERED
    from app.connectors.errors import ERRORS

    out = ["# 连接器清单", "",
           "> 由 `backend/app/connectors/catalog.py` 生成（`python -m app.connectors.catalog`），不要手改。",
           "> 测试保证代码里的每个工具、数据源都在清单里，且本文件与清单一致。", "",
           "## 连接器", "", "| 连接器 | 说明 |", "|---|---|"]
    out += [f"| `{k}` | {v} |" for k, v in CONNECTORS.items()]
    out += ["", "## 数据源（后台同步，产出 Signal）", "", "| 数据源 | 同步方式 | 产出 | 身份 | 可由谁提供 | 说明 |", "|---|---|---|---|---|---|"]
    out += [f"| `{s.name}` | {s.how} | {', '.join(s.kinds)} | {s.auth} | {', '.join(s.providers)} | {s.note} |" for s in SOURCES]
    out += ["", "## 事件（外部推入）", "", "| 事件 | 入口 | 校验 | 去重 | 落到 |", "|---|---|---|---|---|"]
    out += [f"| {e.name} | {e.entry} | {e.check} | {e.dedupe} | {e.lands} |" for e in EVENTS]
    out += ["", "## 工具", "", "副作用等级：" + "；".join(f"`{k}` {v}" for k, v in EFFECT_TEXT.items()) + "。", ""]
    for connector in CONNECTORS:
        rows = [t for t in TOOLS if t.connector == connector]
        if not rows:
            continue
        out += [f"### {connector}", "", "| 工具 | 能力 | 副作用 | 可能的错误 | 说明 |", "|---|---|---|---|---|"]
        for t in sorted(rows, key=lambda t: (t.capability, t.name)):
            desc = REGISTERED[t.name].description.split("。")[0].replace("|", "/") if t.name in REGISTERED else ""
            usage = f"。约定：{t.usage}" if t.usage else ""
            out.append(f"| `{t.name}` | {t.capability} | {t.effect} | {', '.join(t.errors) or '—'} | {desc}{usage} |")
        out.append("")
    out += ["## 错误码", "", "| 错误码 | 原因 | 怎么处理 |", "|---|---|---|"]
    out += [f"| `{e.code}` | {e.meaning} | {e.who} |" for e in ERRORS.values()]
    out += ["", f"查找类工具（{'、'.join(SEARCH_TOOLS)}）每轮对话最多调用 {SEARCH_LIMIT} 次，之后返回 `limit`。", ""]
    return "\n".join(out)


if __name__ == "__main__":
    import os
    import pathlib

    import app.agent.tools  # noqa: F401  注册全部工具

    docs = os.getenv("RELAY_DOCS") or pathlib.Path(__file__).resolve().parents[3] / "docs"
    target = pathlib.Path(docs) / "CONNECTORS.md"
    target.write_text(render_markdown(), encoding="utf-8")
    print(f"已写入 {target}")
