"""后台模型调用（“判断”）清单：每一处叫什么、属于哪类、输入输出是什么、对错从哪里来。

改进这些判断不靠往提示词里加规则，而是：每次调用都记下输入输出（app/judgements/record.py）→
用真实反馈自动标出对错（app/judgements/labels.py）→ 按提示词版本看准确率 → 改动后用回放（app/judgements/replay.py）对比。

类型：
- decide   做一个判断（要不要告诉他、办完没有、这封回信是什么状态）
- extract  从材料里提取（群聊里谁让谁做什么、会议纪要里的行动项、从记忆里整理提醒规则）
- write    写一段给人看的文字（简报、会前准备、回复草稿、提醒的说法）
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Judgement:
    name: str
    kind: str  # decide | extract | write
    where: str  # 代码位置（函数）
    subject: str  # 判断的对象（记录里的 subject 前缀）
    input: str  # 输入是什么
    output: str  # 输出是什么
    truth: str  # 对错从哪里来；“待接”表示还没有自动标注，只记录供回放


JUDGEMENTS = {j.name: j for j in [
    Judgement("mail_triage", "decide", "proactive/engine.py triage", "signal",
              "一封新邮件（发件人、收件人、他在收件人还是抄送、正文、同一线程之前的往来）+ 他的长期记忆",
              "classify_mail：重要程度、要不要马上说、要不要回复、行动类型（reply / review / fyi）、要求、为什么和他有关、时间",
              "这封信变成的事项上，他在卡片上的反馈（处理了 = 对；不归我 / 不值得 / 重复 = 错）；没有反馈的不计"),
    Judgement("reply_draft", "write", "proactive/actions.py write_reply", "signal",
              "原邮件 + 线程往来 + 相关会议 / 文档 / 群聊背景", "回复正文、回复全部还是只回发件人、原因",
              "这份草稿后来怎样：原样发出 = 对；改过再发 = 部分对；取消 = 错"),
    Judgement("mission_completion_check", "decide", "missions/criteria.py check", "mission",
              "长期任务的原话、验收清单、每条的证据", "通过 / 退回，以及原因", "自动：结束后 7 天内他重开了几乎一样的任务 = 错；7 天没有重做 = 对"),
    Judgement("rule_proposal", "extract", "proactive/attention.py propose_from_memories", "user",
              "他的长期记忆里关于提醒的说法", "候选提醒规则（条件 + 档位 + 依据原话）", "他在设置里启用 = 对；不用 = 错"),
    Judgement("chat_extract", "extract", "proactive/chats.py _process", "chat",
              "一段群聊 / 私聊的新消息 + 之前的上下文 + 这段会话里还没结的事", "新的待办（谁让谁做什么、时间）和未结事项的进展",
              "待接：这段会话产生的事项上的反馈"),
    Judgement("chat_extract_retry", "extract", "proactive/chats.py _process（第二遍）", "chat",
              "同上（第一遍结果不合格时重试）", "同上", "待接"),
    Judgement("mail_progress", "decide", "proactive/items.py judge_progress", "item",
              "在等对方的一件事 + 对方的新来信", "这封信是不是对这件事的回应、事情办完了没有", "待接：他之后是否重新打开这件事"),
    Judgement("reply_state", "decide", "proactive/items.py judge_reply", "item",
              "对方来信 + 他的回复", "办完 / 在等对方 / 还要他做", "待接：他之后是否重新打开这件事"),
    Judgement("meeting_actions", "extract", "proactive/meetings.py collect_minutes", "meeting",
              "会议纪要正文", "行动项（谁、做什么、什么时候）", "待接：行动项变成的事项上的反馈"),
    Judgement("meeting_prep", "write", "proactive/meetings.py prepare", "meeting",
              "会议信息 + 和这个会确实相关的材料", "会前简报", "待接：他对会前简报的反馈"),
    Judgement("attachment_digest", "write", "proactive/meetings.py _attachments", "signal",
              "会议相关邮件的一个长附件", "附件要点（轻量模型）", "待接"),
    Judgement("morning_brief", "write", "proactive/engine.py morning_brief", "user",
              "今天的事项、日程、风险、在等别人的事", "早上的简报", "待接"),
    Judgement("team_digest", "write", "proactive/engine.py _team_digest", "user",
              "团队相关的邮件", "团队动态摘要", "待接"),
    Judgement("approval_summary", "write", "proactive/items.py summarize_approval", "signal",
              "一张审批的表单内容", "一句话摘要", "待接"),
    Judgement("followup_draft", "write", "proactive/items.py due_reminders", "item",
              "对方太久没回的一件事 + 往来", "跟进邮件草稿", "待接：草稿后来原样发出 / 改过 / 取消"),
    Judgement("notice_text", "write", "proactive/items.py announce", "user",
              "这次要告诉他的事实列表", "提醒的说法（只能用给出的事实）", "待接"),
]}

KINDS = ("decide", "extract", "write")
RETENTION_DAYS = 30
