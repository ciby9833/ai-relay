"""给本地调试账号（dev-user）写入一套虚构的演示数据，用于截图、录屏和宣传。

用法（需 .env 里 DEV_LOGIN=true，且不是生产环境）：
    docker compose exec -T api python - < scripts/seed_demo.py
    docker compose exec -T -e DEMO_LANG=id api python - < scripts/seed_demo.py   # 看板事项用印尼语，截印尼语界面时用
重复执行会先清掉 dev-user 的旧数据。所有人名、单号、邮件都是虚构的。
任务都停在“等待”状态、提醒时间放到很久以后，worker 不会因为演示数据去调模型或发消息。
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Conversation, FollowUp, Memory, Message, Mission, MissionLog, PendingAction, Signal, SourceState, User,
    UserSettings,
)

NOW = datetime.now(UTC)
FAR = NOW + timedelta(days=30)


# DEMO_LANG=id 时看板事项换成印尼语：印尼语界面配中文内容的截图没有说服力
ID_ITEMS = {
    "customs": ("JT-SG2417: dokumen bea cukai, batas Rabu siang", "Bea cukai minta faktur komersial asli; Dewi tanya apakah boleh lewat pelabuhan cadangan.",
                "Periksa draf balasan Relay, lalu kirim", "Draf balasan sudah siap: kirim dokumen asli hari ini + setuju ganti pelabuhan.", None),
    "quote": ("Rudi minta diskon 5% lagi untuk kontainer 40 ft", "Tarif Q4 rute Surabaya; kontainer 20 ft sudah disetujui.",
              "Kirim penawaran final sebelum Jumat", "Berdasarkan margin historis, maksimal 3%; tawarkan kunci harga 3 bulan.", None),
    "approval": ("Bayar vendor September: IDR 186.400.000", "Keuangan sudah mencocokkan rekap tagihan.",
                 "Setujui", "Jumlah sesuai rekap tagihan, bisa langsung disetujui.", None),
    "review": ("Laporan gangguan gudang minggu ke-3 Oktober", "6 paket rusak, 2 salah kirim; 3 di antaranya vendor yang sama.",
               "Baca dan putuskan perlu rapat dengan vendor", "Masukkan vendor ini ke agenda rapat minggu depan.", None),
    "waybill": ("Menunggu Budi kirim rincian resi minggu ini", "Sudah diingatkan sekali di grup hari Senin.",
                "Ingatkan lagi jika belum ada sebelum Kamis 10:00", None, "Budi Santoso"),
    "contract": ("Menunggu Legal: kontrak sewa gudang baru", "Dikirim Jumat lalu; Legal janji balas minggu ini.",
                 "Tindak lanjut otomatis jika 3 hari tidak dibalas", None, "Tim Legal"),
}
DEMO_LANG = os.getenv("DEMO_LANG", "zh")


def h(hours: float) -> datetime:
    return NOW + timedelta(hours=hours)


async def main() -> None:
    settings = get_settings()
    assert settings.dev_login_enabled, "只在本地 DEV_LOGIN=true 时使用"
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.feishu_open_id == "dev-user"))).scalar_one_or_none()
        if user is None:
            user = User(feishu_open_id="dev-user", name="林晓", timezone=settings.default_timezone)
            session.add(user)
            await session.flush()
        user.name = "林晓"
        for model in (FollowUp, PendingAction, Signal, Mission, Memory, SourceState, UserSettings):
            await session.execute(delete(model).where(model.user_id == user.id))
        await session.execute(delete(Conversation).where(Conversation.user_id == user.id))
        await session.flush()
        # 演示账号没有飞书授权：关掉数据源同步，只留一条“刚同步过”的状态给看板显示
        sources = ["mail", "calendar", "approval", "attendance", "private_chat"]
        session.add(UserSettings(user_id=user.id, data={"sources": {s: False for s in sources}}))
        session.add(SourceState(user_id=user.id, source="mail", cursor={}, last_synced_at=h(-0.05)))

        # ---------- 原始信号（展开跟进事项时显示的邮件） ----------
        def mail(title, frm, addr, summary, hours_ago, urgent=False, reply=True):
            s = Signal(
                user_id=user.id, source="mail", kind="mail", external_id=f"demo-{title}", title=title,
                body=summary, summary=summary, occurred_at=h(-hours_ago), status="tracked",
                importance="urgent" if urgent else "normal", needs_reply=reply,
                payload={"from_name": frm, "from_address": addr},
            )
            session.add(s)
            return s

        m_customs = mail("JT-SG2417 清关补件：需要商业发票原件", "PT Samudra Logistik · Dewi", "dewi@samudra.example",
                         "海关要求补交商业发票原件和装箱单，周三中午前不交会延误 2 天；对方问是否同意改走雅加达备用口岸。", 1.5, urgent=True)
        m_quote = mail("Q4 泗水线运价确认", "PT Nusantara Retail · Rudi", "rudi@nusantara.example",
                       "客户接受 20 尺柜报价，但希望 40 尺柜再降 5%，并要求周五前给最终版本。", 5)
        m_weekly = mail("10 月第三周仓库异常汇总", "仓储组 · 周敏", "zhoumin@example.com",
                        "本周 6 单破损、2 单错发，其中 3 单涉及同一承运商。", 20, reply=False)
        await session.flush()

        # ---------- 待确认操作：Relay 先起草好的回复 ----------
        draft = PendingAction(
            user_id=user.id, kind="send_mail", summary="回复 Dewi：同意补件并改走备用口岸", signal_id=m_customs.id,
            payload={
                "to": "dewi@samudra.example", "subject": "Re: JT-SG2417 清关补件：需要商业发票原件",
                "body": "Hi Dewi,\n\n商业发票原件和装箱单今天下午 4 点前由我们雅加达办公室直接送到报关行，扫描件先附在这封邮件里。\n"
                        "同意改走备用口岸，额外的短驳费用请按上次约定的标准报给我们。\n\n如果周三上午还有缺的材料，请直接打我电话。\n\n谢谢！\n林晓",
                "references": ["JT-SG2417 订单记录", "上周和 Samudra 的费用约定"],
            },
        )
        session.add(draft)
        await session.flush()

        # ---------- 跟进看板 ----------
        def item(key, kind, owner, title, summary, next_step, rec, *, waiting=None, due=None, urgent=False,
                 signals=(), action=None, remind=None):
            if DEMO_LANG == "id":
                title, summary, next_step, rec, waiting_id = ID_ITEMS[key]
                waiting = waiting_id or waiting
            f = FollowUp(
                user_id=user.id, key=f"demo:{key}", kind=kind, owner=owner, title=title, summary=summary,
                next_step=next_step, recommendation=rec, waiting_on=waiting, due_at=due,
                importance="urgent" if urgent else "normal", signal_ids=[s.id for s in signals],
                action_id=action.id if action else None, remind_at=remind, announced_at=NOW, status="open",
            )
            session.add(f)
            return f

        i_customs = item("customs", "reply", "me", "JT-SG2417 清关补件，周三中午截止",
                         "海关要补商业发票原件；Dewi 问能否改走备用口岸。", "确认草稿并发出",
                         "已起草回复：今天送原件 + 同意改口岸。确认即可发送。",
                         due=h(20), urgent=True, signals=[m_customs], action=draft)
        item("quote", "reply", "me", "Rudi 要求 40 尺柜再降 5%", "泗水线 Q4 运价，20 尺柜已接受。",
             "周五前给最终报价", "按历史毛利，最多可让 3%；建议附带 3 个月锁价换取让步。", due=h(70), signals=[m_quote])
        item("approval", "approval", "me", "付款审批：承运商 9 月尾款 IDR 186,400,000", "财务已核对对账单，等你审批。",
             "审批", "金额与对账单一致，可直接批准。", due=h(28))
        item("review", "review", "me", "周敏：10 月第三周仓库异常汇总", "6 单破损、2 单错发，3 单集中在同一承运商。",
             "看一下，决定是否约谈承运商", "建议把这家承运商列入下周例会议题。", signals=[m_weekly])
        item("waybill", "waiting", "others", "等 Budi 交本周运单明细", "周一已在群里提醒过一次。",
             "周四 10:00 前没交再催", None, waiting="Budi Santoso", due=h(46), remind=FAR)
        item("contract", "waiting", "others", "等法务回复新仓库租赁合同修改意见", "上周五发出，对方说本周内回。",
             "3 天没回自动跟进", None, waiting="法务 · 陈律师", remind=FAR)

        # ---------- 长期任务 ----------
        mission_conv = Conversation(user_id=user.id, channel="mission", title="约齐评审会")
        session.add(mission_conv)
        await session.flush()
        mission = Mission(
            user_id=user.id, conversation_id=mission_conv.id, title="约齐泗水新仓评审会",
            goal="约 Budi、Sari、周敏下周开泗水新仓选址评审会，跟到三人都接受邀请",
            status="waiting", next_run_at=FAR, runs=4, grants=[], due_at=h(24 * 5),
            plan=[
                {"step": "查三人下周的忙闲", "status": "done"},
                {"step": "选出共同空闲时段：周二 14:00–15:30", "status": "done"},
                {"step": "发会议邀请并附上选址对比表", "status": "done"},
                {"step": "跟到三人都接受", "status": "doing"},
            ],
            notes="Budi、周敏已接受；Sari 还没回复，周四上午再提醒。",
        )
        session.add(mission)
        await session.flush()
        for kind, text, ago in [
            ("step", "接下任务：约齐泗水新仓评审会", 30),
            ("step", "查了三人下周的日历，周二 14:00 都有空", 29.5),
            ("action", "已发出会议邀请《泗水新仓选址评审》", 29),
            ("report", "Budi、周敏已接受，Sari 未回复", 6),
        ]:
            session.add(MissionLog(mission_id=mission.id, kind=kind, text=text, created_at=h(-ago)))

        # ---------- 主线对话 ----------
        home = Conversation(user_id=user.id, channel="home", title="Relay")
        session.add(home)
        await session.flush()

        def say(role, blocks, ago, event=False):
            if event:
                session.add(Message(conversation_id=home.id, role="user", created_at=h(-ago - 0.001),
                                    content=[{"type": "text", "text": "<event>新的跟进事项</event>", "meta": "event"}]))
            session.add(Message(conversation_id=home.id, role=role, content=blocks, created_at=h(-ago)))

        say("user", [{"type": "text", "text": "帮我约 Budi、Sari、周敏下周开泗水新仓评审会，跟到大家都确认"}], 30)
        say("assistant", [{"type": "text", "text": "好的，我接下了。我会查三个人的忙闲、发邀请，并一直跟到大家都接受。有进展会在这里告诉你。"},
                          {"type": "card", "card": {"kind": "mission", "mission_id": mission.id}}], 29.9)
        say("assistant", [{"type": "text", "text": "早上好，林晓。今天有 **1 件紧急的事**：JT-SG2417 清关补件周三中午截止，回复我已经替你起草好了，确认就能发。\n\n另外 Rudi 想把 40 尺柜再降 5%，我按历史毛利算过，建议最多让 3%。"},
                          {"type": "card", "card": {"kind": "item", "item_id": None}}], 1.4, event=True)
        await session.flush()
        # 回填卡片里的 item_id
        last = (await session.execute(
            select(Message).where(Message.conversation_id == home.id, Message.role == "assistant").order_by(Message.created_at.desc())
        )).scalars().first()
        last.content = [b if b["type"] != "card" else {"type": "card", "card": {"kind": "item", "item_id": i_customs.id}} for b in last.content]

        # ---------- 长期记忆 ----------
        for text in [
            "林晓负责印尼区域的客户运营，主要客户：PT Nusantara Retail、PT Samudra Logistik",
            "林晓偏好邮件简洁、先说结论；对外邮件用英文或印尼语，对内用中文",
            "泗水线 20 尺柜报价底线为历史毛利 12%",
        ]:
            session.add(Memory(user_id=user.id, kind="profile", content=text))

        await session.commit()
        print("demo data ready for", user.id)


asyncio.run(main())
