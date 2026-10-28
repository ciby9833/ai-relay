"""影子实验：按事项对账重建承诺账本，和现有跟进事项对比（只读生产数据，结果写文件）。

    python -m scripts.shadow_ledger --users "Xavier(吴川)" "Kange（康林峰）" --days 7 --detail all --out /out

隐私：报告里所有人只有计数和 token 用量；邮件、聊天等具体内容只出现在每人自己的标注页里（labeling-<名字>.html），
只给他本人标注。
"""

import argparse
import asyncio
import html
import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db import SessionLocal
from app.ledger import shadow
from app.llm.gemini_provider import GeminiProvider
from app.llm.google import genai_client
from app.models import User


def aggregate(user: User, result: dict, items: list, days: int) -> dict:
    events, matters, meter = result["events"], result["matters"], result["meter"]
    commitments = [c for m in matters.values() for c in m.commitments]
    status = Counter((c.owner, c.status) for c in commitments)
    tokens = sum(sum(v) for v in meter.tokens.values())
    return {
        "user": user.name,
        "events": len(events), "kept": sum(e.keep for e in events),
        "kept_by_rule": Counter(e.why.split("｜")[0] for e in events if e.keep).most_common(),
        "attached_none": sum("无关" in e.why for e in events),
        "matters": len(matters), "matters_with_commitments": sum(bool(m.commitments) for m in matters.values()),
        "shadow": {
            "open_me": status[("me", "open")], "open_other": status[("other", "open")],
            "done": status[("me", "done")] + status[("other", "done")],
            "dropped": status[("me", "dropped")] + status[("other", "dropped")],
            "stale": status[("me", "stale")] + status[("other", "stale")],
        },
        "current": {
            "created": len(items), "open_now": sum(i.status == "open" for i in items),
            "by_kind": Counter(f"{i.kind}:{i.status}" for i in items).most_common(),
        },
        "cost": {"calls": meter.calls, "tokens": meter.tokens, "tokens_per_day": round(tokens / days), "errors": meter.errors,
                 "model_seconds": round(meter.seconds)},
    }


LABELS_SHADOW = [("ok", "真实，状态也对"), ("state", "真实，但状态不对"), ("noise", "不是我要管的")]
LABELS_CURRENT = [("ok", "真实，状态也对"), ("state", "真实，但状态不对"), ("noise", "不该出现")]
STATUS = {"open": "未完成", "done": "已办完", "dropped": "不用办了", "stale": "5 天没动静"}
OWNER = {"me": "我欠", "other": "对方欠我"}


def labeling_page(user: User, result: dict, items: list) -> str:
    tz = ZoneInfo(user.timezone)
    rows = []
    for m in sorted(result["matters"].values(), key=lambda m: m.last or m.created, reverse=True):
        if not m.commitments:
            continue
        material = "".join(f"<li>{html.escape(shadow._line(e, tz))}</li>" for e in m.events[-12:])
        for n, c in enumerate(m.commitments):
            key = f"s{m.id}-{n}"
            radios = "".join(f'<label><input type="radio" name="{key}" value="{v}"> {t}</label>' for v, t in LABELS_SHADOW)
            rows.append(f"""<article data-key="{key}" data-group="shadow"><h3>{html.escape(m.title)}</h3>
<p class="c"><b>{OWNER[c.owner]}</b> · {html.escape(c.party)} · {html.escape(c.what)}{(' · 截止 ' + html.escape(c.due)) if c.due else ''}
 <span class="st {c.status}">{STATUS[c.status]}</span></p><p class="ev">依据：{html.escape(c.evidence)}</p>
<details><summary>这件事的材料（{len(m.events)} 条）</summary><ul>{material}</ul></details><div class="r">{radios}</div></article>""")
    current = []
    for i in sorted(items, key=lambda i: i.created_at, reverse=True):
        key = f"c{i.id}"
        radios = "".join(f'<label><input type="radio" name="{key}" value="{v}"> {t}</label>' for v, t in LABELS_CURRENT)
        state = "未结" if i.status == "open" else f"已结束：{i.resolution or i.status}"
        current.append(f"""<article data-key="{key}" data-group="current"><h3>{html.escape(i.title)}</h3>
<p class="c">{i.created_at.astimezone(tz):%m-%d %H:%M} · {html.escape(i.kind)} · <span class="st {'open' if i.status == 'open' else 'done'}">{html.escape(state)}</span></p>
<p class="ev">{html.escape((i.summary or '')[:200])}</p><div class="r">{radios}</div></article>""")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>影子实验标注</title><style>
:root{{--bg:#faf9f5;--fg:#1f1e1d;--muted:#6b6a65;--card:#fff;--line:#e6e3da;--accent:#c96442}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1f1e1d;--fg:#f0eee6;--muted:#a3a199;--card:#2a2927;--line:#3a3936}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,"PingFang SC",sans-serif;margin:0;padding:16px;max-width:900px;margin:auto}}
article{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}}
h1{{font-size:20px}} h2{{font-size:17px;margin-top:28px}} h3{{font-size:15px;margin:0 0 4px}}
.c,.ev{{margin:4px 0}} .ev,details,summary{{color:var(--muted);font-size:13px}} ul{{padding-left:18px}} li{{overflow-wrap:anywhere}}
.st{{font-size:12px;padding:1px 6px;border-radius:6px;border:1px solid var(--line)}} .st.done{{color:#2e7d32}} .st.open{{color:var(--accent)}}
.r label{{margin-right:14px;display:inline-block}} textarea{{width:100%;min-height:90px;box-sizing:border-box}}
button{{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:8px 16px;font-size:15px}} .bar{{position:sticky;top:0;background:var(--bg);padding:8px 0}}
</style></head><body>
<h1>影子实验标注 · {html.escape(user.name)}</h1>
<p>同一段时间（最近几天）里，A 是新链路“按事项对账”整理出的承诺，B 是现有系统建的事项。请按你的真实情况标注：
这件事是不是真的要你管、现在的状态对不对。最后在 C 写下两边都没抓到、但你确实欠别人或在等别人的事。标注会自动保存在本页面，完成后点“导出”，把文件发给我。</p>
<div class="bar"><button onclick="exportLabels()">导出标注</button> <span id="n"></span></div>
<h2>A · 新链路的承诺账本（{len(rows)} 条）</h2>{''.join(rows) or '<p>（没有）</p>'}
<h2>B · 现有系统的事项（{len(current)} 件）</h2>{''.join(current) or '<p>（没有）</p>'}
<h2>C · 两边都漏掉的</h2><textarea id="missed" placeholder="每行一件：谁欠谁什么"></textarea>
<script>
const KEY = "shadow-labels-{user.id}";
let saved = {{}}; try {{ saved = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{}}
for (const [k, v] of Object.entries(saved.labels || {{}})) {{ const el = document.querySelector(`input[name="${{k}}"][value="${{v}}"]`); if (el) el.checked = true; }}
document.getElementById("missed").value = saved.missed || "";
function collect() {{ const labels = {{}}; document.querySelectorAll("input[type=radio]:checked").forEach(r => labels[r.name] = r.value);
  return {{ user: "{html.escape(user.name)}", labels, missed: document.getElementById("missed").value }}; }}
function save() {{ const d = collect(); try {{ localStorage.setItem(KEY, JSON.stringify(d)); }} catch (e) {{}}
  document.getElementById("n").textContent = `已标注 ${{Object.keys(d.labels).length}} / {len(rows) + len(current)}`; }}
document.addEventListener("change", save); document.addEventListener("input", save); save();
function exportLabels() {{ const blob = new Blob([JSON.stringify(collect(), null, 2)], {{ type: "application/json" }});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "shadow-labels.json"; a.click(); }}
</script></body></html>"""


async def main(names: list[str], days: int, detail: list[str], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    provider = GeminiProvider(genai_client())
    report = {"start": start.isoformat(), "end": end.isoformat(), "days": days,
              "models": {"attach": shadow.ATTACH_MODEL, "reconcile": shadow.RECONCILE_MODEL}, "users": []}
    async with SessionLocal() as session:
        for name in names:
            user = (await session.execute(select(User).where(User.name == name))).scalars().first()
            if user is None:
                print(f"找不到用户 {name}", flush=True)
                continue
            print(f"开始 {name}", flush=True)
            result = await shadow.replay(session, provider, user, start, end)
            items = await shadow.current_items(session, user, start, end)
            summary = aggregate(user, result, items, days)
            report["users"].append(summary)
            print(json.dumps(summary, ensure_ascii=False, default=str), flush=True)
            if detail and (name in detail or "all" in detail):
                # 每人一份，只给他本人标注（里面有他的邮件和私聊）
                safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", name).strip("_")
                (out / f"labeling-{safe}.html").write_text(labeling_page(user, result, items), encoding="utf-8")
            await session.rollback()  # 只读：不留下任何改动
            (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("完成", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", nargs="+", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--detail", nargs="*", default=[], help="为这些人生成标注页（每人一份，给本人标注）；all 表示全部")
    parser.add_argument("--out", default="/out")
    args = parser.parse_args()
    asyncio.run(main(args.users, args.days, args.detail, Path(args.out)))
