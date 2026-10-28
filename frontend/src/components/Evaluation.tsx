import { t } from "../i18n";
import { useCallback, useEffect, useState } from "react";
import { api, type EvalCommitment, type EvalData, type EvalFeedbackValue, type EvalItem, type EvalOverview, type EvalRates, type EvalReason } from "../api";
import { dayLabel, relative, timeOf } from "../format";
import Icon from "./Icon";

const STATUS: Record<EvalCommitment["status"], string> = { open: "未完成", done: "已办完", dropped: "不用办了", stale: "5 天没动静" };
const DAYS = [1, 2, 3] as const;
// 和 Claude 的反馈方式一样：👍 一下就好；👎 时可以顺手说一下哪里不对（可选）
const REASONS: [EvalReason, string][] = [
  ["not_mine", "不是我的事"], ["already_done", "其实已经办完了"], ["not_done", "其实还没办完"],
  ["duplicate", "重复了"], ["too_old", "很久以前的事"], ["wrong_detail", "内容不对"],
];

function Feedback({ value, onChange }: { value: EvalFeedbackValue | null; onChange: (value: EvalFeedbackValue | null) => void }) {
  const [note, setNote] = useState(value?.note ?? "");
  useEffect(() => setNote(value?.note ?? ""), [value?.note]);
  const set = (label: "up" | "down") =>
    onChange(value?.label === label ? null : { label, reason: null, note: null });
  return (
    <div className="eval-feedback-box">
      <div className="eval-thumbs">
        <button type="button" className={`btn small ${value?.label === "up" ? "primary" : "ghost"}`} aria-pressed={value?.label === "up"}
          title={t("对")} onClick={() => set("up")}>👍 {t("对")}</button>
        <button type="button" className={`btn small ${value?.label === "down" ? "eval-down" : "ghost"}`} aria-pressed={value?.label === "down"}
          title={t("不对")} onClick={() => set("down")}>👎 {t("不对")}</button>
      </div>
      {value?.label === "down" && (
        <div className="eval-reasons">
          <span className="muted small">{t("哪里不对？（可选）")}</span>
          <div className="eval-chips">
            {REASONS.map(([reason, text]) => (
              <button key={reason} type="button" className={`chip ${value.reason === reason ? "active" : ""}`} aria-pressed={value.reason === reason}
                onClick={() => onChange({ ...value, reason: value.reason === reason ? null : reason })}>
                {t(text)}
              </button>
            ))}
          </div>
          <input className="eval-note" value={note} placeholder={t("补充一句（可选）")} aria-label={t("补充一句（可选）")}
            onChange={(e) => setNote(e.target.value)}
            onBlur={() => note.trim() !== (value.note ?? "") && onChange({ ...value, note: note.trim() || null })} />
        </div>
      )}
    </div>
  );
}

function Commitment({ item, onFeedback }: { item: EvalCommitment; onFeedback: (value: EvalFeedbackValue | null) => void }) {
  return (
    <article className="eval-card">
      <div className="eval-matter">{item.matter}</div>
      <p className="eval-what">
        <b>{t(item.owner === "me" ? "我欠" : "对方欠我")}</b> · {item.party} · {item.what}
        {item.due && <span className="muted"> · {t("截止")} {item.due}</span>}
        <span className={`eval-status ${item.status}`}>{t(STATUS[item.status])}</span>
      </p>
      <p className="muted small">{t("依据：")}{item.evidence}</p>
      {item.materials.length > 0 && (
        <details className="eval-materials">
          <summary>{t("这件事的材料（{count} 条）", { count: item.materials.length })}</summary>
          <ul>
            {item.materials.map((m, i) => (
              <li key={i}><span className="muted">{dayLabel(m.at)} {timeOf(m.at)} {m.actor}：</span>{m.text}</li>
            ))}
          </ul>
        </details>
      )}
      <Feedback value={item.feedback} onChange={onFeedback} />
    </article>
  );
}

function Current({ item, onFeedback }: { item: EvalItem; onFeedback: (value: EvalFeedbackValue | null) => void }) {
  const closed = item.status !== "open";
  return (
    <article className="eval-card">
      <div className="eval-matter">{item.title}</div>
      <p className="muted small">
        {dayLabel(item.created_at)} {timeOf(item.created_at)} ·{" "}
        <span className={`eval-status ${closed ? "done" : "open"}`}>{closed ? `${t("已结束")}：${item.resolution ?? item.status}` : t("未结")}</span>
      </p>
      {item.summary && <p className="muted small">{item.summary}</p>}
      <Feedback value={item.feedback} onChange={onFeedback} />
    </article>
  );
}

/** 每个人对照两条链路给出反馈：新方式整理的承诺 vs 现在系统的事项。只看得到自己的。 */
export default function Evaluation() {
  const [days, setDays] = useState(2);
  const [data, setData] = useState<EvalData | null>(null);
  const [tab, setTab] = useState<"ledger" | "current">("ledger");
  const [missed, setMissed] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.evaluation().then(setData).catch((e) => setError(e instanceof Error ? e.message : t("操作失败"))), []);
  useEffect(() => void load(), [load]);
  // 一次评估是一个任务：整理期间每 15 秒刷新一次进度和已经整理出来的结果；整理完就停
  const busy = data?.status === "queued" || data?.status === "running";
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(load, 15_000);
    return () => window.clearInterval(timer);
  }, [busy, load]);

  if (!data) return <div className="eval-page">{error ? <p role="alert" className="error-text">{error}</p> : null}</div>;

  const save = async (target: "ledger" | "followup", key: string, value: EvalFeedbackValue | null, snapshot: Record<string, string>) => {
    setData((d) => d && {
      ...d,
      ledger: target === "ledger" ? d.ledger.map((c) => (c.key === key ? { ...c, feedback: value } : c)) : d.ledger,
      current: target === "followup" ? d.current.map((c) => (c.key === key ? { ...c, feedback: value } : c)) : d.current,
    });
    try { await api.evalLabel(target, key, value, snapshot); } catch { setError(t("保存失败，请重试")); load(); }
  };
  const done = (list: { feedback: EvalFeedbackValue | null }[]) => list.filter((x) => x.feedback).length;
  const start = async () => {
    setStarting(true);
    try { await api.evalEnroll(days); await load(); } catch { setError(t("操作失败")); } finally { setStarting(false); }
  };

  return (
    <div className="eval-page">
      <header className="eval-head">
        <h1>{t("帮 Relay 变聪明")}</h1>
        <p className="muted">
          {t("我们在试一种新方式：把同一件事的邮件、聊天、审批放在一起，判断“谁欠谁什么、办完没有”。它只在后台计算，不会给你发提醒。觉得对就点 👍，不对点 👎，愿意的话说一下哪里不对。只有你自己看得到。")}
        </p>
      </header>

      {!data.enrolled ? (
        <section className="eval-start">
          <p>{t("整理多久的事？")}</p>
          <div className="eval-days" role="radiogroup" aria-label={t("时间范围")}>
            {DAYS.map((d) => (
              <button key={d} type="button" role="radio" aria-checked={days === d} className={`chip ${days === d ? "active" : ""}`}
                disabled={starting} onClick={() => setDays(d)}>
                {t("最近 {count} 天", { count: d })}
              </button>
            ))}
          </div>
          <p className="muted small">{t("开始后范围就定下来了；整理完之后有新消息会自动更新。")}</p>
          <button className="btn primary" disabled={starting} onClick={start}>{starting ? t("正在开始…") : t("开始")}</button>
        </section>
      ) : (
        <>
          <div className="eval-bar" aria-live="polite">
            <span className="chip active">{t("整理范围：最近 {count} 天", { count: data.days })}</span>
            {busy ? (
              <span className="eval-progress">
                <span className="eval-progress-track"><span style={{ width: `${Math.round((data.progress ?? 0) * 100)}%` }} /></span>
                <span className="muted small">
                  {data.status === "queued" ? t("排队中，马上开始…") : t("正在整理 {percent}%，已整理出的结果可以先看", { percent: Math.round((data.progress ?? 0) * 100) })}
                </span>
              </span>
            ) : (
              <span className="muted small">{t("已整理完，有新消息会自动更新（最近一次 {time}）", { time: data.processed_until ? relative(data.processed_until) : "—" })}</span>
            )}
          </div>
          <nav className="eval-tabs">
            <button className="btn secondary" aria-pressed={tab === "ledger"} onClick={() => setTab("ledger")}>
              {t("新方式整理的承诺")} · {done(data.ledger)}/{data.ledger.length}
            </button>
            <button className="btn secondary" aria-pressed={tab === "current"} onClick={() => setTab("current")}>
              {t("现在系统的事项")} · {done(data.current)}/{data.current.length}
            </button>
          </nav>
          {tab === "ledger" ? (
            data.ledger.length ? data.ledger.map((item) => (
              <Commitment key={item.key} item={item}
                onFeedback={(v) => save("ledger", item.key, v, { what: item.what, status: item.status, matter: item.matter })} />
            )) : <p className="empty-note">{busy ? t("正在整理，结果会陆续出现在这里。") : t("这段时间没有整理出要跟进的事。")}</p>
          ) : (
            data.current.length ? data.current.map((item) => (
              <Current key={item.key} item={item} onFeedback={(v) => save("followup", item.key, v, { title: item.title, status: item.status })} />
            )) : <p className="empty-note">{t("这段时间没有事项。")}</p>
          )}

          <section className="eval-missed">
            <h3>{t("两边都漏掉的")}</h3>
            <p className="muted small">{t("你确实欠别人、或在等别人的事，但上面两边都没有。每次写一件。")}</p>
            <textarea value={missed} onChange={(e) => setMissed(e.target.value)} placeholder={t("例如：等 Hendri 发 9 月运单明细")} />
            <button className="btn primary small" disabled={!missed.trim()}
              onClick={() => api.evalFeedback("missed", missed.trim()).then(() => { setMissed(""); load(); })}>
              <Icon name="plus" size={14} /> {t("提交")}
            </button>
            {data.feedback.length > 0 && (
              <ul className="eval-feedback">
                {data.feedback.map((f) => <li key={f.id}>{f.text} <span className="muted small">{relative(f.created_at)}</span></li>)}
              </ul>
            )}
          </section>
        </>
      )}
      {error && <p role="alert" className="error-text">{error}</p>}
    </div>
  );
}

const percent = (value: number | null) => (value === null ? "—" : `${Math.round(value * 100)}%`);
const REASON_TEXT: Record<string, string> = { ...Object.fromEntries(REASONS), unspecified: "没说原因" };

function Rates({ rates }: { rates: EvalRates }) {
  const top = Object.entries(rates.reasons).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0)).slice(0, 2);
  return (
    <span>
      👍 {percent(rates.correct)} <span className="muted small">({rates.labeled})</span>
      {top.length > 0 && <span className="muted small"> · {top.map(([r, n]) => `${t(REASON_TEXT[r] ?? r)} ${n}`).join("、")}</span>}
    </span>
  );
}

/** 管理员：各人的评估汇总（只有数字，没有内容）。 */
export function EvalSummary() {
  const [data, setData] = useState<EvalOverview | null>(null);
  useEffect(() => void api.evalOverview().then(setData), []);
  if (!data) return null;
  return (
    <section className="eval-summary">
      <h2>{t("新旧链路评估")}</h2>
      <p className="muted small">{t("每格是 👍 的占比（反馈数），以及最常见的 👎 原因。内容只有本人看得到。")}</p>
      <div className="table-scroll">
        <table>
          <thead><tr><th>{t("用户")}</th><th>{t("新方式")}</th><th>{t("现在的系统")}</th><th>{t("漏掉的")}</th><th>{t("已整理到")}</th></tr></thead>
          <tbody>
            <tr className="eval-total"><td>{t("合计")}</td><td><Rates rates={data.total.ledger} /></td><td><Rates rates={data.total.current} /></td><td /><td /></tr>
            {data.users.map((row) => (
              <tr key={row.user}>
                <td>{row.user}</td><td><Rates rates={row.ledger} /></td><td><Rates rates={row.current} /></td>
                <td>{row.missed}</td><td className="muted small">{row.processed_until ? relative(row.processed_until) : row.enrolled ? t("整理中") : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
