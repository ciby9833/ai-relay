"""跟进判断的准确性评测：用和生产一样的提示词和模型，跑一组标注好的真实场景。

    docker compose exec api python -m scripts.eval_followups

覆盖三类判断：
1. 群聊/私聊里，未结事项有没有实质进展（done / committed / 不算进展）——群聊事项自动关闭的准确性
2. 邮件：对方的新消息（同一线程或另一个线程）对“在等的事”意味着什么——跨线程关联的准确性
3. 他回复之后还需不需要等对方——“回复了不等于办完了”

只调用模型，不读写飞书和数据库。
"""

import asyncio
import json
import sys

from app.proactive.chats import TASKS_TOOL
from app.proactive.items import PROGRESS_TOOL, REPLY_STATE_TOOL
from app.proactive.llm import complete_structured
from app.proactive.prompts import CHAT_TASKS_SYSTEM, PROGRESS_SYSTEM, REPLY_STATE_SYSTEM

NOW = "2026-10-19 15:00 Monday"

# (在等的事, 新消息, 期望：done / committed / none)
CHAT_PROGRESS = [
    ("等 Nikki：把操作部的需求进度同步给需求人", ["Nikki：1", "Nikki：预计月底前完成"], "committed"),
    ("等 Nikki：把操作部的需求进度同步给需求人", ["Nikki：已经同步给需求人了，名单发群里了"], "done"),
    ("等 Nikki：把操作部的需求进度同步给需求人", ["Nikki：收到"], "none"),
    ("等 Veigar：排查签收坐标获取不到实时经纬度的问题", ["Veigar：在查了，有点复杂"], "none"),
    ("等 Veigar：排查签收坐标获取不到实时经纬度的问题", ["Veigar：原因找到了，是安卓定位权限被系统回收，今晚发版修复"], "committed"),
    ("等 Veigar：排查签收坐标获取不到实时经纬度的问题", ["Veigar：已经修好上线了，你那边再看看"], "done"),
    ("等 Hendri：发 9 月运单明细", ["Hendri：明细已经发你邮箱了"], "done"),
    ("等 Hendri：发 9 月运单明细", ["Hendri：今天中午大家吃什么？"], "none"),
    ("等 Hendri：发 9 月运单明细", ["Hendri：Besok pagi saya kirim ya"], "committed"),
    ("Jennifer 让你：10 月 20 日前在反馈表里填 IT 部门意见", ["Xavier：好的我看下"], "none"),
    ("Jennifer 让你：10 月 20 日前在反馈表里填 IT 部门意见", ["Xavier：已经填好了，S 列和 T 列都更新了"], "done"),
    ("等 Amber：确认新版本是否可以发布", ["Amber：测试还有两个 bug，修完再说"], "none"),
    # 2026-10-22 生产复盘：对方说早就发过了 / 本人回答了“有没有异议” / “都弄了”其实在答别的问题
    ("等 Veigar(吴英杰)：单独拎出三段码叉叉的数据统计数量，用于后续分析原因",
     ["Veigar(吴英杰)：@Xavier(吴川) 这里说的就是三段码的准确率嘛", "Xavier(吴川)：是的是的，接下来要做改善，得把这部分数据分析一下",
      "Veigar(吴英杰)：这个我发过给你们呀，这就是最新的三段码准确率", "Veigar(吴英杰)：这周四我会再拉一次数据"], "done"),
    ("Pieter Dickens 让你：查看蒋旭提出的调整顺序的小需求文档并确认是否有异议", ["Xavier(吴川)：没啥问题"], "done"),
    ("Bernie 让你：在介绍PPT中整理一些体现目标市场潜力的数字",
     ["Bernie：团建各部门都搞了么，回头双十一后面又开始忙", "Maggie：都弄了", "Maggie：郭哥他们部门吃饭了，我们去茂物野生动物园了"], "none"),
]

# 一次回复同时回应好几件事：(未结事项列表, 新消息, 每件期望)
MULTI_PROGRESS = [
    (["等 Veigar(吴英杰)：单独拎出三段码叉叉的数据统计数量，用于后续分析原因",
      "等 Veigar(吴英杰)：抓取数据核实出仓单子的三段码与签收的三段码是否一致"],
     ["Veigar(吴英杰)：这个我发过给你们呀，这就是最新的三段码准确率，叉叉的明细也在里面", "Veigar(吴英杰)：最新的结果 [文件]"],
     ["done", "done"]),
    (["等 Hendri：发 9 月运单明细", "等 Hendri：确认下周培训的时间"],
     ["Hendri：明细已经发你邮箱了"], ["done", "none"]),
]

# (在等的事, 新消息（标题 + 正文）, 期望：done / committed / ack / unrelated)
MAIL_PROGRESS = [
    ("等 Fiona 回复（确认会议时间）", ("Invitation: J&T Cargo Indonesia // OpenAI @ Mon Oct 19 4pm", "You have been invited by Fiona to attend an event on Monday Oct 19 4pm"), "done"),
    ("等 Fiona 回复（确认会议时间）", ("Re: J&T Cargo // OpenAI", "Thank you, I've sent out an invite. Could you share your team's questions before the meeting?"), "done"),
    ("等 Fiona 回复（确认会议时间）", ("OpenAI DevDay recap", "Here are the highlights from DevDay and our newest models."), "unrelated"),
    ("等 Jennifer 回复（确认 V10 合同里 IT 条款的最终版本）", ("Re: Agreement V10", "Thanks Xavier, noted. I will consolidate with legal and get back to you."), "ack"),
    ("等 Jennifer 回复（确认 V10 合同里 IT 条款的最终版本）", ("Re: Agreement V10", "Lazada has agreed to all IT clauses, final version attached."), "done"),
    ("等 Jennifer 回复（确认 V10 合同里 IT 条款的最终版本）", ("Re: Agreement V10", "Lazada will reply by Friday, I'll update you then."), "committed"),
    ("等 Hendri 回复（提供 9 月发货量导数需求的字段说明）", ("Invitation: Weekly sync @ Tue", "You have been invited to Weekly sync"), "unrelated"),
    ("等 Hendri 回复（提供 9 月发货量导数需求的字段说明）", ("Re: 印尼导数需求", "字段说明在附件里，网点维度按 A/B 级网点汇总"), "done"),
    ("等供应商回复（报价）", ("Re: Quotation", "We are checking with our factory, will revert asap."), "ack"),
    ("等供应商回复（报价）", ("Re: Quotation", "Please find attached our quotation, valid until end of month."), "done"),
]

# (对方上一封, 他的回复, 期望：还要不要等对方)
REPLY_STATE = [
    ("Will you be attending the call? Or do you want to postpone it?", "Hi Fiona, we can proceed as scheduled. My colleagues will attend.", False),
    ("Will you be attending the call? Or do you want to postpone it?", "Can we move it to Wednesday 2pm instead?", True),
    ("Please share your team's questions before the meeting.", "Here are our questions: 1) data residency 2) pricing for API.", False),
    ("Could you confirm the IT feedback in the sheet by Oct 20?", "Done, I've filled in columns S and T.", False),
    ("Could you confirm the IT feedback in the sheet by Oct 20?", "I filled most of it, but please confirm whether row 63 should be Pending?", True),
    ("Mohon konfirmasi jadwal meeting minggu depan.", "Selasa jam 10 bisa? Tolong dikonfirmasi ya.", True),
    ("Terima kasih atas bantuannya.", "Sama-sama, semoga lancar.", False),
    ("请问 9 月运单明细什么时候能给？", "明天上午发你。", False),
]


# 私聊里谁让谁做事（他是 Xavier，另一方是 Zorvan）：(消息, 期望 (requester, assignee) 或 None)
PRIVATE_TASKS = [
    (["Zorvan：你周五前把 9 月的报表发我"], ("Zorvan", "Xavier")),
    (["Xavier：你明天把合同盖章版发我一下"], ("Xavier", "Zorvan")),
    (["Zorvan：那个接口文档你看下有没有问题", "Xavier：好的，我下午看"], ("Zorvan", "Xavier")),
    (["Zorvan：周末愉快！"], None),
    (["Xavier：Tolong kirim data pengiriman bulan September besok ya"], ("Xavier", "Zorvan")),
]


async def extract_private(messages: list[str]):
    lines = [f"[{i}] 10-19 14:{30 + i} {m}" for i, m in enumerate(messages)]
    result = await complete_structured(
        CHAT_TASKS_SYSTEM, f"<now>{NOW}</now>\n<chat kind=\"Xavier 和 Zorvan 的私聊（只有这两个人）\">\n" + "\n".join(lines) + "\n</chat>", TASKS_TOOL,
    )
    tasks = result.get("tasks") or []
    return (tasks[0]["requester"], tasks[0]["assignee"]) if tasks else None


async def judge_chat(task: str, messages: list[str]) -> str:
    lines = [f"[{i}] 10-19 14:{30 + i} {m}" for i, m in enumerate(messages)]
    result = await complete_structured(
        CHAT_TASKS_SYSTEM,
        f"<now>{NOW}</now>\n<chat kind=\"群聊\">\n" + "\n".join(lines) + f"\n</chat>\n\n<open>\n[#1] {task}\n</open>",
        TASKS_TOOL,
    )
    verdicts = [p["verdict"] for p in result.get("progress") or [] if p.get("item_id") == 1]
    return verdicts[0] if verdicts else "none"


async def judge_multi(tasks: list[str], messages: list[str]) -> list[str]:
    lines = [f"[{i}] 10-19 14:{30 + i} {m}" for i, m in enumerate(messages)]
    pending = "\n".join(f"[#{n}] {t}" for n, t in enumerate(tasks, 1))
    result = await complete_structured(
        CHAT_TASKS_SYSTEM, f"<now>{NOW}</now>\n<chat kind=\"群聊\">\n" + "\n".join(lines) + f"\n</chat>\n\n<open>\n{pending}\n</open>", TASKS_TOOL,
    )
    verdicts = {p.get("item_id"): p["verdict"] for p in result.get("progress") or []}
    return [verdicts.get(n, "none") for n in range(1, len(tasks) + 1)]


async def judge_mail(task: str, title: str, body: str) -> str:
    result = await complete_structured(
        PROGRESS_SYSTEM,
        f"<now>{NOW}</now>\n在等的事：{task}\n\n<message>\n对方：《{title}》\n{body}\n</message>\n\nevidence 用简体中文写。",
        PROGRESS_TOOL,
    )
    return result.get("verdict")


async def judge_reply(theirs: str, mine: str) -> bool:
    result = await complete_structured(
        REPLY_STATE_SYSTEM, f"<mail>\n对方上一封：{theirs}\n\n他的回复：\n{mine}\n</mail>\n\nsummary 用简体中文写。", REPLY_STATE_TOOL,
    )
    return bool(result.get("needs_response"))


async def run(name, cases, judge) -> tuple[int, int]:
    correct, misses = 0, []
    for *inputs, expected in cases:
        got = await judge(*inputs)
        if got == expected:
            correct += 1
        else:
            misses.append({"inputs": inputs, "expected": expected, "got": got})
    print(f"{name}: {correct}/{len(cases)}")
    for miss in misses:
        print("  ✗", json.dumps(miss, ensure_ascii=False))
    return correct, len(cases)


async def main() -> None:
    totals = [
        await run("群聊/私聊事项进展", CHAT_PROGRESS, judge_chat),
        await run("一次回复回应好几件事", MULTI_PROGRESS, judge_multi),
        await run("邮件进展（同线程/跨线程）", MAIL_PROGRESS, lambda task, mail: judge_mail(task, *mail)),
        await run("回复后还要不要等对方", REPLY_STATE, judge_reply),
        await run("私聊里谁让谁做事", PRIVATE_TASKS, extract_private),
    ]
    correct, total = sum(c for c, _ in totals), sum(t for _, t in totals)
    print(f"合计：{correct}/{total}")
    sys.exit(0 if correct == total else 1)


if __name__ == "__main__":
    asyncio.run(main())
