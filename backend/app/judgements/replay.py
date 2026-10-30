"""回放：改了提示词或换了模型以后，拿真实样本和固定样本重跑，用准确率说话，而不是凭感觉。

    # 真实样本：最近 N 天里能从反馈判断对错的那些（只输出数字，不输出内容）
    python -m app.judgements.replay mail_triage --days 14
    # 固定样本：tests/judgements/golden/<判断>.jsonl 里的虚构用例（不碰任何真实数据）
    python -m app.judgements.replay mail_triage --golden

需要配置模型（在服务器上的容器里运行）。每次回放都真的调用模型，会产生费用：样本数用 --limit 控制。
"""

import argparse
import asyncio
import json
import pathlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class Replayable:
    """怎么重跑一个判断、看哪个关键结论。"""

    system: str  # 系统提示词所在的“模块:变量”
    tool: str | None  # 结构化输出的工具定义“模块:变量”；None 表示写文字
    key: str  # 比较的关键结论（labels 里 truth 的键）


def _decide_surface(output: dict) -> bool | None:
    from app.judgements.labels import surfaced

    return surfaced(output)


REPLAY = {
    "mail_triage": (Replayable("app.proactive.engine:TRIAGE_SYSTEM", "app.proactive.engine:TRIAGE_TOOL", "surface"), _decide_surface),
    "mission_completion_check": (Replayable("app.missions.criteria:CHECK_SYSTEM", "app.missions.criteria:CHECK_TOOL", "goal_supported"),
                                 lambda output: output.get("goal_supported")),
    "reply_state": (Replayable("app.proactive.items:REPLY_STATE_SYSTEM", "app.proactive.items:REPLY_STATE_TOOL", "state"),
                    lambda output: output.get("state")),
}
GOLDEN = pathlib.Path(__file__).resolve().parents[2] / "tests" / "judgements" / "golden"


def _load(path: str):
    import importlib

    module, name = path.split(":")
    return getattr(importlib.import_module(module), name)


async def _run(name: str, prompt: str) -> dict:
    from app.proactive.llm import complete_structured

    spec, _ = REPLAY[name]
    return await complete_structured(_load(spec.system), prompt, _load(spec.tool))


def build_input(name: str, fields: dict) -> str:
    """固定样本的输入：用和线上完全一样的函数拼出来。"""
    if name == "mail_triage":
        from app.proactive.engine import triage_input

        return triage_input(**fields)
    if name == "reply_state":
        from app.proactive.items import reply_state_input

        return reply_state_input(**fields)
    raise ValueError(f"{name} 还没有固定样本的输入格式")


def golden_cases(name: str) -> list[dict]:
    path = GOLDEN / f"{name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def replay_golden(name: str) -> dict:
    """固定样本：每条有 fields（输入的各项，按线上同一个函数拼成提示）和 expect（关键结论）。"""
    _, decide = REPLAY[name]
    cases, right, wrong = golden_cases(name), 0, []
    for case in cases:
        got = decide(await _run(name, build_input(name, case["fields"])))
        if got == case["expect"]:
            right += 1
        else:
            wrong.append({"id": case["id"], "expect": case["expect"], "got": got})
    return {"name": name, "cases": len(cases), "right": right, "accuracy": round(right / len(cases), 4) if cases else None, "wrong": wrong}


async def replay_recorded(name: str, days: int, limit: int) -> dict:
    """真实样本：重跑能判断对错的记录，比较“当时的判断”和“现在的判断”各对了多少。只输出数字。"""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.judgements import labels
    from app.models import JudgementRun

    spec, decide = REPLAY[name]
    async with SessionLocal() as session:
        runs = list((await session.execute(select(JudgementRun).where(
            JudgementRun.name == name, JudgementRun.error.is_(None),
            JudgementRun.created_at >= datetime.now(UTC) - timedelta(days=days)).order_by(JudgementRun.id.desc()))).scalars())
        truth = {s.run_id: s.truth.get(spec.key) for s in await labels.samples(session, runs) if spec.key in s.truth}
    runs = [r for r in runs if r.id in truth][:limit]
    before = after = changed = 0
    for run in runs:
        old = decide(run.output or {})
        new = decide(await _run(name, run.input))
        before += old == truth[run.id]
        after += new == truth[run.id]
        changed += old != new
    n = len(runs)
    return {"name": name, "samples": n, "before": round(before / n, 4) if n else None, "after": round(after / n, 4) if n else None,
            "changed": changed}


def main() -> None:
    parser = argparse.ArgumentParser(description="回放后台判断，对比准确率")
    parser.add_argument("name", choices=sorted(REPLAY))
    parser.add_argument("--golden", action="store_true", help="只跑固定样本（虚构用例）")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    result = asyncio.run(replay_golden(args.name) if args.golden else replay_recorded(args.name, args.days, args.limit))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
