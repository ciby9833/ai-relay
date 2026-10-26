"""一次性复核还开着的“群里@你还没回”事项：读那条@前后的聊天，判断还需不需要他回复。

    docker compose exec api python -m scripts.recheck_mentions            # 只列出判断结果，不改任何东西
    docker compose exec api python -m scripts.recheck_mentions --apply    # 按判断关闭不需要他回复的事项

以前的规则是“@了他、两小时内他没在群里说话就提醒，直到他在群里说话”，不看上下文，留下了很多其实是
答复他自己问题、抄送、或已经有结论的事项。新消息的判断已经改成先读上下文；这个脚本只处理改之前留下的。
还需要回复的事项保持打开，并补上会话链接，之后这个群里有新消息时会和其他未结事项一起判断进展。
"""

import argparse
import asyncio
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ChatMessage, FollowUp, Signal, User
from app.proactive import chats, items
from app.proactive.llm import complete_structured
from app.proactive.prompts import CHAT_TASKS_SYSTEM

BEFORE, AFTER = 12, 40


async def judge(session, item: FollowUp, signal: Signal, user: User) -> dict | None:
    chat_id = (signal.payload or {}).get("chat_id")
    if not chat_id or signal.occurred_at is None:
        return None
    same = (ChatMessage.chat_id == chat_id) & ChatMessage.owner_user_id.is_(None)
    before = list((await session.execute(select(ChatMessage).where(same, ChatMessage.created_at < signal.occurred_at)
                                         .order_by(ChatMessage.created_at.desc()).limit(BEFORE))).scalars())[::-1]
    after = list((await session.execute(select(ChatMessage).where(same, ChatMessage.created_at >= signal.occurred_at)
                                        .order_by(ChatMessage.created_at).limit(AFTER))).scalars())
    if not after:
        return None
    tz = ZoneInfo(user.timezone)
    replied = await chats._parents(session, before + after)
    lines = [f"（之前）{m.sender_name or '某人'}{replied.get(m.message_id, '')}：{m.text}" for m in before]
    lines += [f"[{i}] {m.created_at.astimezone(tz):%m-%d %H:%M} {m.sender_name or '某人'}{replied.get(m.message_id, '')}：{m.text}"
              for i, m in enumerate(after)]
    result = await complete_structured(
        CHAT_TASKS_SYSTEM,
        f"<now>{after[-1].created_at.astimezone(tz):%Y-%m-%d %H:%M %A}</now>\n<chat kind=\"群聊\">\n" + "\n".join(lines) + "\n</chat>\n\n"
        f"<open>\n[#{item.id}] {user.name} 被@了还没回：「{(signal.body or '')[:200]}」\n</open>\n\n"
        "这次只判断 <open> 里这件事：那条@需不需要他回复、后面的消息里是否已经有了答复或结论。tasks 和 asks 给空列表。",
        chats.TASKS_TOOL,
    )
    return next((c for c in result.get("progress") or [] if c.get("item_id") == item.id), {"verdict": "open"})


async def main(apply: bool) -> None:
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(FollowUp, User).join(User, User.id == FollowUp.user_id)
            .where(FollowUp.kind == "mention", FollowUp.status == "open").order_by(FollowUp.id)
        )).all()
        closed = kept = 0
        for item, user in rows:
            signal = await session.get(Signal, item.signal_ids[-1]) if item.signal_ids else None
            if signal is None:
                continue
            chat_id = (signal.payload or {}).get("chat_id")
            if chat_id and not item.url:
                item.url = chats.chat_link(chat_id)  # 之后这个群的新消息会一起判断这件事
            try:
                verdict = await judge(session, item, signal, user)
            except Exception as exc:  # noqa: BLE001
                print(f"#{item.id} {user.name} 判断失败：{exc}")
                continue
            done = bool(verdict) and verdict.get("verdict") == "done"
            evidence = chats.clean_evidence((verdict or {}).get("evidence") or "")
            print(f"#{item.id} [{user.name}] 「{(signal.body or '')[:40]}」 → {'不用他回了：' + evidence if done else '仍需回复'}")
            if done:
                closed += 1
                if apply:
                    items.close(item, "done", f"读过上下文：{evidence}".rstrip("："))
                    signal.status = "done"
            else:
                kept += 1
        print(f"共 {len(rows)} 件：可关闭 {closed} 件，仍需回复 {kept} 件" + ("（已关闭）" if apply else "（只列出，未修改；加 --apply 执行）"))
        if apply:
            await session.commit()
        else:
            await session.rollback()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
