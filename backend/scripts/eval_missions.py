"""长期任务结束前独立核对的评测：用和生产一样的提示词和模型，跑一组来自真实失败的场景。

    docker compose exec api python -m scripts.eval_missions [--repeat 2]

核对者是“grader”，它判错了，后面所有“办成没有”都不可信。所以按评测设计的做法：
- 用例来自真实发生过的失败（Nikki 回“1”/“月底前”、只回“收到”、把发了邮件说成对方已确认、只做了一半……），
  也放进确实办成的例子，免得核对者一律卡住；
- 每个用例跑多次，看同一份材料两次判断是否一致（--repeat）；
- 判错的用例逐条打印，不要把它们原样塞进提示词，修根因。

只调用模型，不读写飞书和数据库。
"""

import argparse
import asyncio
import json
import sys

from app.missions.criteria import CHECK_SYSTEM, CHECK_TOOL
from app.proactive.llm import complete_structured

# (用户原话, [(验收条目, 证据原文)], 给用户的结论, 期望：每条是否被支持, 期望：结论是否如实)
CASES = [
    ("提醒下 Nikki 把需求进度同步给需求人，让他给个结果，帮我盯着",
     [("Nikki 给出需求进度的结果", "时间线（reply）：[对方回复了]\n- Nikki：1\n- Nikki：预计月底前完成")],
     "Nikki 已经给出结果", [False], False),
    ("提醒下 Nikki 把需求进度同步给需求人，让他给个结果，帮我盯着",
     [("Nikki 给出需求进度的结果", "时间线（reply）：[对方回复了]\n- Nikki：已经同步给需求人了，结论是下周三上线")],
     "Nikki 已同步给需求人，结论是下周三上线", [True], True),
    ("让 Hendri 把 9 月运单明细发我",
     [("Hendri 发来 9 月运单明细", "时间线（reply）：[对方回复了]\n- Hendri：收到，我看看")],
     "Hendri 已经处理了", [False], False),
    ("让 Hendri 把 9 月运单明细发我",
     [("Hendri 发来 9 月运单明细", "mail #812 Hendri《9 月运单明细》：明细见附件，共 12,340 单。附件：Sep_waybills.xlsx")],
     "Hendri 发来了 9 月运单明细（共 12,340 单，附件 Sep_waybills.xlsx）", [True], True),
    ("约 Fiona 开会并确认她参加",
     [("Fiona 确认参加会议", "操作 #77：发送邮件给 Fiona 邀请开会 → 已发送：回复 Fiona（写入后核对：未核对）")],
     "已经和 Fiona 约好，她会参加", [False], False),
    ("约 Fiona 开会并确认她参加",
     [("Fiona 确认参加会议", "mail #901 Fiona《Accepted: J&T // OpenAI @ Mon 4pm》：Fiona has accepted this invitation.")],
     "Fiona 已接受会议邀请（周一下午 4 点）", [True], True),
    ("让张三和李四都填好反馈表",
     [("张三填好反馈表", "时间线（reply）：- 张三：已经填好了，S 列都更新了"),
      ("李四填好反馈表", "（没有证据）")],
     "两个人都填好了", [True, False], False),
    ("把我的意见填进 Jennifer 的反馈表 S49、S50",
     [("S49、S50 填入我的意见", "操作 #90：填写 S49、S50 → 已填好（写入后核对：读回 S49、S50 与填写的一致）")],
     "已在反馈表 S49、S50 填入你的意见，读回核对一致", [True], True),
    ("Tolong ingatkan Budi kirim penawaran harga, pantau sampai dia kirim",
     [("Budi mengirim penawaran harga", "时间线（reply）：- Budi：Besok pagi saya kirim ya")],
     "Budi sudah mengirim penawaran", [False], False),
    ("让 Veigar 修好签收坐标的问题",
     [("签收坐标问题修好", "时间线（reply）：- Veigar：原因找到了，是安卓定位权限被回收，今晚发版修复")],
     "原因找到了，Veigar 说今晚发版修复，还没确认修好", [False], True),
]


async def judge(instruction, items, result):
    blocks = [f"[{n}] {text}\n状态：met；执行者说：已做到\n证据原文：{evidence}" for n, (text, evidence) in enumerate(items, 1)]
    prompt = f"<材料>\n用户原话：{instruction}\n\n验收标准与证据：\n" + "\n\n".join(blocks) + f"\n\n准备给用户的结论：{result}\n</材料>"
    verdict = await complete_structured(CHECK_SYSTEM, prompt, CHECK_TOOL)
    by_id = {c["id"]: c for c in verdict.get("criteria") or []}
    return [bool(by_id.get(n, {}).get("supported")) for n in range(1, len(items) + 1)], bool(verdict.get("result_faithful"))


async def main(repeat: int) -> None:
    correct = total = unstable = 0
    for instruction, items, result, expected, faithful in CASES:
        runs = [await judge(instruction, items, result) for _ in range(repeat)]
        if any(r != runs[0] for r in runs):
            unstable += 1
        for got in runs:
            total += 1
            # 核对者最重要的是“不该放行的不放行”：每条和结论都要对上
            if got == (expected, faithful):
                correct += 1
            else:
                print("  ✗", json.dumps({"instruction": instruction, "result": result, "expected": [expected, faithful], "got": got},
                                        ensure_ascii=False))
    print(f"独立核对：{correct}/{total}（{len(CASES)} 个场景 × {repeat} 次），前后判断不一致的场景：{unstable}")
    sys.exit(0 if correct == total and unstable == 0 else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=2)
    asyncio.run(main(parser.parse_args().repeat))
