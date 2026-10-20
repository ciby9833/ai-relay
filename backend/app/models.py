import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

EMBEDDING_DIM = 1536


class BlogPost(Base):
    __tablename__ = "blog_posts"

    slug: Mapped[str] = mapped_column(String(160), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(32))
    published_at: Mapped[date | None] = mapped_column(Date)
    draft: Mapped[bool] = mapped_column(Boolean)
    cover: Mapped[str | None] = mapped_column(Text)
    bundle_hash: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BlogAsset(Base):
    __tablename__ = "blog_assets"

    post_slug: Mapped[str] = mapped_column(
        ForeignKey("blog_posts.slug", ondelete="CASCADE"), primary_key=True
    )
    path: Mapped[str] = mapped_column(Text, primary_key=True)
    content_type: Mapped[str] = mapped_column(String(128))
    sha256: Mapped[str] = mapped_column(String(64))
    # HTML is stored as bytes too: importing and serving never reformat the original.
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    feishu_open_id: Mapped[str] = mapped_column(String(64), unique=True)
    feishu_union_id: Mapped[str | None] = mapped_column(String(64))
    feishu_user_id: Mapped[str | None] = mapped_column(String(64))
    tenant_key: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(64))
    # 飞书用户 token 用 SECRET_KEY 派生的密钥加密后存储，助手以用户身份读文档时使用
    feishu_access_token_enc: Mapped[str | None] = mapped_column(Text)
    feishu_refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    feishu_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 用户这次授权给 Relay 的权限（空格分隔）；应用新开通了权限时据此提醒他重新授权
    feishu_scopes: Mapped[str | None] = mapped_column(Text)
    # 管理员：可以管理业务系统接入。第一位用飞书登录的用户自动成为管理员
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(16))  # home | web | feishu | task | mission
    # feishu: chat_id；task: 定时任务 id
    external_id: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    # 自增 id 同时充当会话内的顺序
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    # 与模型供应商无关的内容块列表：text / tool_use / tool_result
    content: Mapped[list] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # profile | episodic
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    prompt: Mapped[str] = mapped_column(Text)
    cron: Mapped[str | None] = mapped_column(String(64))  # 为空表示一次性任务
    timezone: Mapped[str] = mapped_column(String(64))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # 用户授权这个任务直接办的事：[{"kind", "scope", "label", "granted_at"}]，scope 限定到具体对象（哪张表、哪个会话）
    grants: Mapped[list] = mapped_column(JSONB, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeishuEvent(Base):
    """飞书事件去重：同一 event_id 只处理一次。"""

    __tablename__ = "feishu_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


DEFAULT_SETTINGS = {
    "proactive": True,
    "sources": {
        "calendar": True,
        "mail": True,
        "approval": True,
        "attendance": True,
        "message": True,
        "private_chat": False,  # 私聊感知：读他和常联系同事的私聊来识别待办，必须他自己开启
    },
    "quiet_start": "21:00",  # 免打扰开始（用户时区）
    "quiet_end": "08:00",
    "brief_enabled": False,  # 是否每个工作日自动发早间简报（默认实时为主，简报按需）
    "brief_time": "08:30",  # 每日简报时间
    "meeting_brief_minutes": 15,  # 会前多久发会议准备
    "max_interrupts_per_hour": 6,
    "language": "auto",  # auto = 按他发给 Relay 的消息自动识别；也可指定 zh / en / id
}


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    last_brief_date: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD


class SourceState(Base):
    """每个用户每个数据源的同步状态。"""

    __tablename__ = "source_states"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    cursor: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class Signal(Base):
    """从数据源采集到的一件事：一封邮件、一个会议、一条待审批……"""

    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "external_id", name="uq_signals_user_source_ext"),
        Index("ix_signals_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(32))  # calendar | mail | approval | attendance | message
    kind: Mapped[str] = mapped_column(String(32))  # meeting | invitation | mail | approval_pending | ...
    external_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # new → 待判断；notify → 待推送；notified / digest / ignored / done
    status: Mapped[str] = mapped_column(String(16), server_default="new")
    importance: Mapped[str | None] = mapped_column(String(16))  # urgent | normal | low
    summary: Mapped[str | None] = mapped_column(Text)  # 判断后的一句话摘要
    reason: Mapped[str | None] = mapped_column(Text)
    needs_reply: Mapped[bool] = mapped_column(Boolean, server_default="false")
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PendingAction(Base):
    """准备好、等用户确认后才执行的操作（发邮件、回复会议邀请）。"""

    __tablename__ = "pending_actions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # send_mail | calendar_rsvp
    summary: Mapped[str] = mapped_column(Text)  # 给用户看的说明
    payload: Mapped[dict] = mapped_column(JSONB)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id", ondelete="SET NULL"))
    # 由长期任务发起的操作：用户确认/取消后，这个任务会被唤醒继续
    mission_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    # 定时任务里准备的操作：确认时可以顺带授权“这个任务以后直接办”
    scheduled_task_id: Mapped[int | None] = mapped_column(ForeignKey("scheduled_tasks.id", ondelete="SET NULL"))
    auto: Mapped[bool] = mapped_column(Boolean, server_default="false")  # 按用户的授权自动执行的（没有逐次确认）
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 用户撤销了这次操作
    status: Mapped[str] = mapped_column(String(16), server_default="pending")  # pending | done | cancelled | failed
    result: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FollowUp(Base):
    """一件正在跟进的事。由信号归并而来（同一封邮件线程、同一人同一天的一批需求、一个邀请……），
    记录球在谁那、下一步是什么，并由 Relay 推进到关闭。"""

    __tablename__ = "follow_ups"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_follow_ups_user_key"),
        Index("ix_follow_ups_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # 归并键：mail-thread:<thread_id>、batch:<发件人>:<日期>、invite:<event_id>、approval:<task_id>……
    key: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))  # reply | review | invitation | approval | attendance | mention | request | waiting
    owner: Mapped[str] = mapped_column(String(16))  # me（等你）| others（等别人）
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    next_step: Mapped[str | None] = mapped_column(Text)  # 下一步要做什么
    recommendation: Mapped[str | None] = mapped_column(Text)  # Relay 的建议
    waiting_on: Mapped[str | None] = mapped_column(String(255))  # 等谁
    url: Mapped[str | None] = mapped_column(Text)
    signal_ids: Mapped[list] = mapped_column(JSONB, server_default="[]")
    action_id: Mapped[int | None] = mapped_column(ForeignKey("pending_actions.id", ondelete="SET NULL"))
    importance: Mapped[str] = mapped_column(String(16), server_default="normal")  # urgent | normal
    status: Mapped[str] = mapped_column(String(16), server_default="open")  # open | done | dismissed
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remind_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    nudges: Mapped[int] = mapped_column(Integer, server_default="0")
    # 已经在主线里告诉过用户的时间；免打扰时段新建的事项先不说，之后补上
    announced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(Text)  # 怎么结束的
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FeishuCard(Base):
    """发到飞书的卡片及其内容来源。用户点了按钮后据此重新渲染，原地更新成最新状态；
    用户引用这张卡片回复时，也据此知道他说的是哪几件事。"""

    __tablename__ = "feishu_cards"

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    sections: Mapped[list] = mapped_column(JSONB)  # [[分组标题, [卡片数据...]], ...]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatMessage(Base):
    """机器人所在群里的消息（需要“获取群组中所有消息”权限）。不推送给任何人，
    只用来理解要处理的事：从中提取谁让谁做什么，以及起草回复时作为背景。保留 14 天。"""

    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_chat_created", "chat_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(128), unique=True)
    chat_id: Mapped[str] = mapped_column(String(128))
    chat_name: Mapped[str | None] = mapped_column(String(255))
    sender_open_id: Mapped[str] = mapped_column(String(64))
    sender_name: Mapped[str | None] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list] = mapped_column(JSONB, server_default="[]")  # [{"open_id", "name"}]
    processed: Mapped[bool] = mapped_column(Boolean, server_default="false")  # 是否已提取过待办
    # 私聊消息属于读取它的那位用户（以他的身份读到的），只用于他自己的事项，永远不给别人当背景；群消息为空
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Mission(Base):
    """长期任务：用户交给 Relay 的一个目标（“盯着报价直到客户确认”“约齐人开会”），
    在后台分多次执行：每次醒来看情况、推进一步，然后等时间或等事件再醒。

    对外的敏感操作仍然先准备、等用户确认；用户可以针对这个任务预先授权某几类操作（grants），
    授权过的那类操作才会自动执行。"""

    __tablename__ = "missions"
    __table_args__ = (Index("ix_missions_status_next", "status", "next_run_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    goal: Mapped[str] = mapped_column(Text)
    # 用户交代这件事时的原话（逐字保存）：判断“办成没有”以原话为准，不以 Relay 改写的 goal 为准
    instruction: Mapped[str | None] = mapped_column(Text)
    # 原话里提到的截止/复查时间；没提时为空，催人节奏按默认规则（下一个工作日上午）
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # active（等时间）| waiting（等事件）| asking（等用户回答）| done | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    plan: Mapped[list] = mapped_column(JSONB, server_default="[]")  # [{"step", "status": todo|doing|done}]
    notes: Mapped[str | None] = mapped_column(Text)  # 跨轮次的工作笔记
    grants: Mapped[list] = mapped_column(JSONB, server_default="[]")  # 用户预先授权自动执行的操作类型
    wait_for: Mapped[dict | None] = mapped_column(JSONB)  # 等待的事件
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    question: Mapped[str | None] = mapped_column(Text)  # 等用户回答的问题
    result: Mapped[str | None] = mapped_column(Text)
    runs: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MissionLog(Base):
    """长期任务的时间线：每次醒来做了什么、汇报了什么。"""

    __tablename__ = "mission_logs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # wake | step | report | ask | action | done
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Person(Base):
    """同事名册：在私聊、群聊里出现过的人（发言人、被@的人）、通讯录查到的人。
    用来把“Andrew（陈春华）”这样的名字对应到飞书身份，以便发消息、建任务、约会。"""

    __tablename__ = "people"

    open_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    source: Mapped[str] = mapped_column(String(32))  # mention | sender | contact | user
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Integration(Base):
    """接入 Relay 的业务系统（TMS、WMS、CRM……）。业务系统用专属地址和密钥把事件推给 Relay。"""

    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)  # 出现在推送地址里
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    secret_enc: Mapped[str] = mapped_column(Text)  # 签名密钥（加密存储）
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntegrationEvent(Base):
    """业务系统推来的每一条事件（用于去重和排查）。"""

    __tablename__ = "integration_events"
    __table_args__ = (UniqueConstraint("integration_id", "event_id", name="uq_integration_event"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))  # delivered | partial | unmatched | resolved
    detail: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserDecision(Base):
    """用户怎么处理每件事（批了/拒了/接受/确认发送/标记已处理/去飞书看原文……）。

    用来回答两个问题：Relay 有没有帮他省时间（处理时还要不要打开原文），
    以及哪一类事他总是同样处理——之后可以提议“这类以后我直接办”（必须他授权）。
    """

    __tablename__ = "user_decisions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    subject: Mapped[str] = mapped_column(String(32))  # 事情的种类：approval | invitation | reply | send_mail | send_chat | …
    category: Mapped[str | None] = mapped_column(String(255))  # 同一类的依据：审批类型、组织者、收件人、发件人……
    decision: Mapped[str] = mapped_column(String(32))  # approve | reject | accept | decline | confirm | cancel | edit | done | dismiss | mute | open_original
    via: Mapped[str] = mapped_column(String(16))  # web | feishu_card | chat | auto
    item_id: Mapped[int | None] = mapped_column(BigInteger)
    action_id: Mapped[int | None] = mapped_column(BigInteger)
    seconds_to_decide: Mapped[int | None] = mapped_column(Integer)  # 从事情出现到他处理用了多久
    detail: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
