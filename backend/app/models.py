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
DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


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


class Tenant(Base):
    """一家公司 / 一个工作区（类似 Slack 的 workspace）。成员、助理、连接、数据都归属于某个工作区，工作区之间互相隔离。"""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(16), server_default="active")  # active | suspended
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Account(Base):
    """登录账号：一个人（邮箱 + 密码）。一个账号可以是多个工作区的成员，在每个工作区里各有一份成员资料（User）。"""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True)  # 小写
    password_hash: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantInvitation(Base):
    """邀请加入工作区：管理员生成链接，对方用链接设置密码（或用已有账号）加入。只存令牌的哈希。"""

    __tablename__ = "tenant_invitations"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantConnection(Base):
    """工作区接入的外部渠道（目前是飞书）：管理员填写的应用配置。非机密的放 config，密钥加密后放 secrets_enc，接口只返回是否已填。"""

    __tablename__ = "tenant_connections"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", name="uq_tenant_connection"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))  # feishu
    config: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    secrets_enc: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="unverified")  # unverified | ok | failed | disabled
    last_error: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    """工作区里的一位成员（他在这个工作区里的资料、助理和全部数据都挂在这里）。

    以前只有飞书登录，所以叫 User 且必须有飞书身份；现在飞书身份可选，登录账号（Account）另存。"""

    __tablename__ = "users"
    # 每个工作区接的是它自己的飞书应用，同一个飞书身份只在一个工作区内唯一
    __table_args__ = (UniqueConstraint("tenant_id", "feishu_open_id", name="uq_users_tenant_open_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # 没指定工作区时归入默认工作区（迁移前的所有用户都在这里），旧代码创建用户的地方不用改
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, default=lambda: DEFAULT_TENANT_ID,
                                                 server_default=str(DEFAULT_TENANT_ID))
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), index=True)
    role: Mapped[str] = mapped_column(String(16), server_default="member")  # owner | admin | member
    status: Mapped[str] = mapped_column(String(16), server_default="active")  # active | deactivated
    feishu_open_id: Mapped[str | None] = mapped_column(String(64), index=True)  # 每个工作区内唯一（见 __table_args__）
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
    # 管理员（工作区的 owner / admin）：和 role 保持一致，旧代码按 is_admin 判断的地方不用改
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
        "private_chat": True,
        "task": True,  # 别人在飞书任务里派给他的事（需要 task:task:read 授权）  # 私聊感知：读他和常联系同事的私聊来识别待办（缺私聊读取授权时会提示重新登录）
    },
    "quiet_start": "21:00",  # 免打扰开始（用户时区）
    "quiet_end": "08:00",
    "brief_enabled": True,  # 每个工作日自动发早间简报
    "brief_time": "08:30",  # 每日简报时间
    "meeting_brief_minutes": 15,  # 会前多久发会议准备
    "max_interrupts_per_hour": 3,  # 立刻打扰的上限，超出的并到下一次汇总
    "digest_times": ["11:30", "16:30"],  # 不急的事攒到这几个时间一起说（工作日；早上的简报也算一次）
    "language": "auto",  # auto = 按他发给 Relay 的消息自动识别；也可指定 zh / en / id
}


class AttentionRule(Base):
    """他明确说过的提醒偏好：“请假审批只放简报”“Budi 的事随时告诉我”“这个群的@不用提醒”。

    由代码在推送前逐条匹配，模型不能绕过；只有他本人（对话里说、卡片上点、网页里改）能新增和修改。
    """

    __tablename__ = "attention_rules"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # 匹配条件，全部满足才算命中：group（approval|mail|chat|invitation|waiting|biz|attendance）、
    # person（人名或邮箱，包含即可）、approval（审批类型）、chat（群名）、system（业务系统名）
    match: Mapped[dict] = mapped_column(JSONB)
    level: Mapped[str] = mapped_column(String(16))  # now | batch | brief | mute
    label: Mapped[str] = mapped_column(Text)  # 给人看的一句话：“请假审批 → 只放简报”
    source: Mapped[str] = mapped_column(String(16))  # chat | card | web | memory（从以前的记忆整理出的候选）
    # active 生效 | proposed 候选（从历史偏好整理出来，等他确认后才生效）| rejected 他说不要（不再提议）
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    evidence: Mapped[str | None] = mapped_column(Text)  # 候选规则的依据：以前他说过的原话
    hits: Mapped[int] = mapped_column(Integer, server_default="0")  # 命中过多少件事（让他知道这条规则在起作用）
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    # 这件事值不值得打扰他：now 立刻说 | batch 攒到固定时间一起说 | brief 只进早上简报 | mute 只在看板里静默跟踪
    attention: Mapped[str | None] = mapped_column(String(16))
    attention_note: Mapped[str | None] = mapped_column(Text)  # 为什么这样分（给他看：“你说过请假审批只放简报”）
    # 判断“同一类事”的依据（拿不到来源信号的事项在创建时写进来，例如群聊待办的提出人、群名）
    facets: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # 上一次为这件事单独发飞书消息的时间和当时的紧急程度：同一件事短时间内再有动静时原地更新那张卡片，
    # 只有升级成紧急才另发一条
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pushed_importance: Mapped[str | None] = mapped_column(String(16))
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
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 上次按最新状态原地更新的时间


class ChatMessage(Base):
    """机器人所在群里的消息（需要“获取群组中所有消息”权限）。不推送给任何人，
    只用来理解要处理的事：从中提取谁让谁做什么，以及起草回复时作为背景。保留 14 天。"""

    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_chat_created", "chat_id", "created_at"),
                      UniqueConstraint("tenant_id", "message_id", name="uq_chat_messages_tenant_message"))

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # 哪个工作区的飞书应用收到的：跨公司的外部群里同一条消息，每个工作区各存一份、各自处理，互相看不到
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True,
                                                 default=lambda: DEFAULT_TENANT_ID, server_default=str(DEFAULT_TENANT_ID))
    message_id: Mapped[str] = mapped_column(String(128))
    chat_id: Mapped[str] = mapped_column(String(128))
    chat_name: Mapped[str | None] = mapped_column(String(255))
    sender_open_id: Mapped[str] = mapped_column(String(64))
    sender_name: Mapped[str | None] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list] = mapped_column(JSONB, server_default="[]")  # [{"open_id", "name"}]
    processed: Mapped[bool] = mapped_column(Boolean, server_default="false")  # 是否已提取过待办
    # 回复的是哪条消息（飞书的话题回复 / 引用回复）：判断“这条@是在回答他刚才的问题”要靠它
    parent_message_id: Mapped[str | None] = mapped_column(String(128))
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
    # 验收清单：接任务时按用户原话定下“做到这几条才算办成”。Relay 只能改每条的状态和证据，不能改条目本身
    # （条目只有用户能改）。[{"id", "text", "status": open|met|unmet, "evidence", "ref", "checked_at"}]
    criteria: Mapped[list] = mapped_column(JSONB, server_default="[]")
    # 结束前的独立核对没通过的次数：超过上限就不再自己反复改，交给用户判断
    check_rounds: Mapped[int] = mapped_column(Integer, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text)  # 跨轮次的工作笔记
    grants: Mapped[list] = mapped_column(JSONB, server_default="[]")  # 用户预先授权自动执行的操作类型
    wait_for: Mapped[dict | None] = mapped_column(JSONB)  # 等待的事件
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    question: Mapped[str | None] = mapped_column(Text)  # 等用户回答的问题
    result: Mapped[str | None] = mapped_column(Text)
    runs: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssuranceEvent(Base):
    """Append-only checks, handoffs, completions and human reviews; never inferred from prose."""
    __tablename__ = "assurance_events"
    __table_args__ = (Index("ix_assurance_events_kind_created", "kind", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    mission_id: Mapped[int | None] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MissionLog(Base):
    """长期任务的时间线：每次醒来做了什么、汇报了什么。"""

    __tablename__ = "mission_logs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # wake | reply（对方回复原文）| step | report | ask | action | done
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Person(Base):
    """同事名册：在私聊、群聊里出现过的人（发言人、被@的人）、通讯录查到的人。
    用来把“Andrew（陈春华）”这样的名字对应到飞书身份，以便发消息、建任务、约会。"""

    __tablename__ = "people"

    # 每个工作区一份名册：别的公司的人不会被找到、也不会被发消息
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True,
                                                 default=lambda: DEFAULT_TENANT_ID, server_default=str(DEFAULT_TENANT_ID))
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
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), default=lambda: DEFAULT_TENANT_ID,
                                                 server_default=str(DEFAULT_TENANT_ID))  # 属于哪个工作区：只推给这个工作区的成员
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


# ---------- 承诺账本（新链路，评估阶段：只计算、不推送） ----------


class LedgerEvent(Base):
    """进入账本的一条事件（只存引用和摘录）：来自邮件、聊天、审批、邀请、任务等，归到某件事上。"""

    __tablename__ = "ledger_events"
    __table_args__ = (UniqueConstraint("user_id", "ref", name="uq_ledger_events_user_ref"),
                      Index("ix_ledger_events_matter", "matter_id"))

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    ref: Mapped[str] = mapped_column(String(160))  # sig:123 / chat:om_xxx / sig:123:state
    matter_id: Mapped[int | None] = mapped_column(ForeignKey("ledger_matters.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(24))
    actor: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    stream: Mapped[str] = mapped_column(String(255))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verdict: Mapped[str] = mapped_column(String(16))  # skipped（规则挡掉）| none（和他无关）| attached
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LedgerMatter(Base):
    """一件事：同一件事的邮件、聊天、审批、会议都归在这里，承诺账本按事整体判断。"""

    __tablename__ = "ledger_matters"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    people: Mapped[list] = mapped_column(JSONB, server_default="[]")
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LedgerCommitment(Base):
    """账本里的一条承诺：谁欠谁什么、什么时候、办完没有、凭什么。每次对账整体替换这件事的承诺。"""

    __tablename__ = "ledger_commitments"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    matter_id: Mapped[int] = mapped_column(ForeignKey("ledger_matters.id", ondelete="CASCADE"), index=True)
    owner: Mapped[str] = mapped_column(String(8))  # me | other
    party: Mapped[str] = mapped_column(String(255))
    what: Mapped[str] = mapped_column(Text)
    due: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # open | done | dropped | stale
    evidence: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvalLabel(Base):
    """用户本人对一条结果的评价：新链路的承诺（ledger）或现有系统的事项（followup）。"""

    __tablename__ = "eval_labels"
    __table_args__ = (UniqueConstraint("user_id", "target", "target_key", name="uq_eval_labels_target"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    target: Mapped[str] = mapped_column(String(16))  # ledger | followup
    # 被评价的对象：承诺用“事项编号:承诺内容”（对账会整体替换承诺行，内容不变就沿用评价），事项用 id
    target_key: Mapped[str] = mapped_column(String(600))
    label: Mapped[str] = mapped_column(String(16))  # up 对 | down 不对
    # 不对的原因（可选）：not_mine 不是我的事 | duplicate 重复了 | too_old 很久以前的事（这三种 = 不该出现）
    #                     already_done 其实已经办完了 | not_done 其实还没办完 | wrong_detail 内容不对（这三种 = 事是真的、判断错了）
    reason: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[dict] = mapped_column(JSONB, server_default="{}")  # 评价时它长什么样（状态、标题）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalFeedback(Base):
    """两边都漏掉的事、或其他意见：用户自己写。"""

    __tablename__ = "eval_feedback"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # missed | comment
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ItemFeedback(Base):
    """用户在真实卡片上对一件事的反馈（飞书卡片和网页共用）。

    outcome：handled_after 提醒后处理了 | handled 没提醒过、他自己标了已处理 | handled_before 提醒前就处理了 |
    not_mine 不归我 | not_worth 不值得提醒 | quieter 这类以后少提醒 | duplicate 重复了。
    pushed_at 记下反馈时这件事有没有被推送过、什么时候，用来算提醒准确率和迟到率。
    """

    __tablename__ = "item_feedback"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("follow_ups.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(16))  # p2p | group | mail | approval | invitation | …（来源类别，只有类别没有内容）
    outcome: Mapped[str] = mapped_column(String(32))
    via: Mapped[str] = mapped_column(String(16))
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seconds_after_push: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GeneratedFile(Base):
    """Relay 替用户生成的文件（Excel、PPT、Word）。只有他本人能下载；verified 是生成后重新打开逐项核对的结果。

    生成和存进飞书云空间都可能比较久：按任务记状态（status / stage），worker 接着做，中途重启也不丢；
    做完（或失败）告诉他。drive 是存进云空间的结果（文件 token、链接、下载回来核对的结果）。
    """

    __tablename__ = "generated_files"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # xlsx | pptx | docx
    filename: Mapped[str] = mapped_column(String(255))
    content: Mapped[bytes | None] = mapped_column(LargeBinary)
    spec: Mapped[dict] = mapped_column(JSONB)
    verified: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(String(16), server_default="done")  # queued | running | done | failed
    stage: Mapped[str | None] = mapped_column(String(64))  # 正在做哪一步（给他看）
    error: Mapped[str | None] = mapped_column(Text)
    save_to_drive: Mapped[dict | None] = mapped_column(JSONB)  # 要存进云空间：{"folder_token": ...}；存完清空
    drive: Mapped[dict | None] = mapped_column(JSONB)  # {"token", "url", "verified": {...}}
    notify: Mapped[bool] = mapped_column(Boolean, server_default="false")  # 后台做完要告诉他
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Delegation(Base):
    """同一工作区里两个人之间的一份委托：请求 → 接受 / 拒绝 / 提修改 → 执行 → 提交 → 验收通过 / 退回；可以取消。

    这是协作状态唯一的权威：双方“待处理”里的事项（key = collab:<id>）只引用它、跟着它变。
    双方各自的对话、记忆、账号权限不共享；对方能看到的只有这里明确写下的内容和共享材料。"""

    __tablename__ = "delegations"
    __table_args__ = (Index("ix_delegations_tenant_status", "tenant_id", "status"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    requester_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assignee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    brief: Mapped[str] = mapped_column(Text)  # 要做什么、为什么
    deliverable: Mapped[str] = mapped_column(Text)  # 交付什么
    acceptance: Mapped[str | None] = mapped_column(Text)  # 怎样算完成
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 没约定就是空，不替人编日期
    materials: Mapped[list] = mapped_column(JSONB, server_default="[]")  # 请求方明确共享的材料 [{title, url?, text?}]
    # requested | countered | accepted | submitted | returned | completed | declined | cancelled
    status: Mapped[str] = mapped_column(String(16), server_default="requested")
    proposal: Mapped[dict | None] = mapped_column(JSONB)  # 承接方提出的修改 {deliverable?, acceptance?, due_at?, note}
    submission: Mapped[dict | None] = mapped_column(JSONB)  # 最近一次提交 {note, materials}
    version: Mapped[int] = mapped_column(Integer, server_default="1")  # 每次变化 +1：防止重复点击、基于旧状态的操作
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DelegationEvent(Base):
    """委托的变更记录：谁在什么时候做了什么（请求、接受、修改、提交、验收……）。"""

    __tablename__ = "delegation_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    delegation_id: Mapped[int] = mapped_column(ForeignKey("delegations.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserConnection(Base):
    """成员自己接入的数据源（不依赖飞书）：标准邮箱（IMAP 收 / SMTP 发）、日历订阅链接（ICS）。

    接了之后，同一套助理行为（判断、待处理、提醒、简报、会前准备、代拟回复）就能用这些数据工作。
    密码 / 订阅链接加密保存，接口只告诉“填了没有”。"""

    __tablename__ = "user_connections"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_connection"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16))  # imap | ics
    config: Mapped[dict] = mapped_column(JSONB, server_default="{}")  # 公开配置：服务器、端口、账号、邮箱地址
    secrets_enc: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="unverified")  # unverified | ok | failed
    last_error: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Device(Base):
    """配对的桌面客户端（第一版：Mac）。设备是一种执行者，不是另一个助理：它只替本人读写他授权的文件夹，
    任务状态仍在云端。令牌只存哈希；本人可以在网页上随时撤销。"""

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    platform: Mapped[str] = mapped_column(String(32))  # darwin | win32
    app_version: Mapped[str | None] = mapped_column(String(32))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # 设备上报的授权文件夹：[{id, label, read, write}]。只有名字，不含完整路径（路径只留在设备上）
    folders: Mapped[list] = mapped_column(JSONB, server_default="[]")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeviceJob(Base):
    """交给设备做的一步（列文件、读文件、存文件）。设备领取后执行、回传结果；同一步只执行一次。"""

    __tablename__ = "device_jobs"
    __table_args__ = (Index("ix_device_jobs_device_status", "device_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # list | read | write
    args: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(String(16), server_default="queued")  # queued | running | done | failed | expired
    result: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
