import { t } from "../i18n";
import { useCallback, useEffect, useState } from "react";
import { api, type EvalCommitment, type EvalData, type EvalItem, type EvalLabel, type EvalOverview, type EvalRates } from "../api";
import { dayLabel, relative, timeOf } from "../format";
import Icon from "./Icon";

const STATUS: Record<EvalCommitment["status"], string> = { open: "未完成", done: "已办完", dropped: "不用办了", stale: "5 天没动静" };
const LABELS: [EvalLabel, string][] = [["ok", "真实，状态也对"], ["state", "真实，但状态不对"], ["noise", "不是我要管的"]];

function LabelButtons({ value, onChange }: { value: EvalLabel | null; onChange: (label: EvalLabel | null) => void }) {
  return (
    <div className="eval-labels" role="radiogroup">
      {LABELS.map(([label, text]) => (
        <button key={label} type="button" role="radio" aria-checked={value === label}
          className={`btn small ${value === label ? `primary eval-${label}` : "ghost"}`}
          onClick={() => onChange(value === label ? null : label)}>
          {t(text)}
        </button>
      ))}
    </div>
  );
}

function Commitment({ item, onLabel }: { item: EvalCommitment; onLabel: (label: EvalLabel | null) => void }) {
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
      <LabelButtons value={item.label} onChange={onLabel} />
    </article>
  );
}

function Current({ item, onLabel }: { item: EvalItem; onLabel: (label: EvalLabel | null) => void }) {
  const closed = item.status !== "open";
  return (
    <article className="eval-card">
      <div className="eval-matter">{item.title}</div>
      <p className="muted small">
        {dayLabel(item.created_at)} {timeOf(item.created_at)} · {item.kind} ·{" "}
        <span className={`eval-status ${closed ? "done" : "open"}`}>{closed ? `${t("已结束")}：${item.resolution ?? item.status}` : t("未结")}</span>
      </p>
      {item.summary && <p className="muted small">{item.summary}</p>}
      <LabelButtons value={item.label} onChange={onLabel} />
    </article>
  );
}

/** 每个人对照两条链路给出反馈：新链路的承诺账本 vs 现有系统的事项。只看得到自己的。 */
export default function Evaluation() {
  const [data, setData] = useState<EvalData | null>(null);
  const [tab, setTab] = useState<"ledger" | "current">("ledger");
  const [missed, setMissed] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.evaluation().then(setData).catch((e) => setError(e instanceof Error ? e.message : t("操作失败"))), []);
  useEffect(() => void load(), [load]);

  if (!data) return <div className="eval-page">{error ? <p role="alert" className="error-text">{error}</p> : null}</div>;

  const label = async (target: "ledger" | "followup", key: string, value: EvalLabel | null, snapshot: Record<string, string>) => {
    setData((d) => d && {
      ...d,
      ledger: target === "ledger" ? d.ledger.map((c) => (c.key === key ? { ...c, label: value } : c)) : d.ledger,
      current: target === "followup" ? d.current.map((c) => (c.key === key ? { ...c, label: value } : c)) : d.current,
    });
    try { await api.evalLabel(target, key, value, snapshot); } catch { setError(t("保存失败，请重试")); load(); }
  };
  const labeled = (list: { label: EvalLabel | null }[]) => list.filter((x) => x.label).length;

  return (
    <div className="eval-page">
      <header className="eval-head">
        <h1>{t("帮 Relay 变聪明")}</h1>
        <p className="muted">
          {t("我们在试一种新的整理方式：把同一件事的邮件、聊天、审批放在一起，整体判断“谁欠谁什么、办完没有”。它目前只在后台计算，不会给你发提醒。请对照你的真实情况，标一标两边的结果哪些是真的、状态对不对。只有你自己看得到这些内容。")}
        </p>
      </header>

      {!data.enrolled ? (
        <section className="eval-start">
          <p>{t("开始后，Relay 会先整理你最近 7 天的事（大约需要半小时），之后持续更新。")}</p>
          <button className="btn primary" onClick={() => api.evalEnroll().then(load)}>{t("开始评估")}</button>
        </section>
      ) : (
        <>
          <p className="muted small">
            {data.processed_until ? t("已整理到 {time}", { time: relative(data.processed_until) }) : t("正在整理你最近 7 天的事，大约半小时后回来看。")}
          </p>
          <nav className="eval-tabs">
            <button className="btn secondary" aria-pressed={tab === "ledger"} onClick={() => setTab("ledger")}>
              {t("新方式整理的承诺")} · {labeled(data.ledger)}/{data.ledger.length}
            </button>
            <button className="btn secondary" aria-pressed={tab === "current"} onClick={() => setTab("current")}>
              {t("现在系统的事项")} · {labeled(data.current)}/{data.current.length}
            </button>
          </nav>
          {tab === "ledger" ? (
            data.ledger.length ? data.ledger.map((item) => (
              <Commitment key={item.key} item={item}
                onLabel={(v) => label("ledger", item.key, v, { what: item.what, status: item.status, matter: item.matter })} />
            )) : <p className="empty-note">{t("还没有整理出来，稍后再看。")}</p>
          ) : (
            data.current.length ? data.current.map((item) => (
              <Current key={item.key} item={item} onLabel={(v) => label("followup", item.key, v, { title: item.title, status: item.status })} />
            )) : <p className="empty-note">{t("最近 7 天没有事项。")}</p>
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

function Rates({ rates }: { rates: EvalRates }) {
  return <span>{percent(rates.real)} / {percent(rates.correct)} <span className="muted small">({rates.labeled})</span></span>;
}

/** 管理员：各人的评估汇总（只有数字，没有内容）。 */
export function EvalSummary() {
  const [data, setData] = useState<EvalOverview | null>(null);
  useEffect(() => void api.evalOverview().then(setData), []);
  if (!data) return null;
  return (
    <section className="eval-summary">
      <h2>{t("新旧链路评估")}</h2>
      <p className="muted small">{t("每格是“真实率 / 全对率（标注数）”：真实率 = 标为真实的占比，全对率 = 真实且状态也对的占比。内容只有本人看得到。")}</p>
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
