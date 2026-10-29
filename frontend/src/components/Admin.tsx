import { useEffect, useState } from "react";
import { api, type ReminderQuality, type ClosureReview, type NotificationDay, type NotificationStats, type QualityRate, type QualityStats, type ReviewVerdict } from "../api";
import { t, intlLocale } from "../i18n";
import Icon from "./Icon";
import CriterionEvidence from "./CriterionEvidence";
import { EvalSummary } from "./Evaluation";
import Performance from "./Performance";

const kinds: (keyof NotificationDay)[] = ["interrupt", "digest", "brief", "meeting", "mission", "other"];
const metrics = [
  ["adminFalseClosure", "false_closure", "adminFalseClosureDef"],
  ["adminCompletionFailure", "completion_failure", "adminCompletionDef"],
  ["adminVerificationFailure", "verification_failure", "adminVerificationDef"],
  ["adminTakeover", "human_takeover", "adminTakeoverDef"],
  ["adminTurnNoAnswer", "turn_no_answer", "adminTurnNoAnswerDef"],
  ["adminTurnForced", "turn_forced_final", "adminTurnForcedDef"],
  ["adminTurnHeavy", "turn_heavy_search", "adminTurnHeavyDef"],
] as const;
const number = (n: number) => n.toLocaleString(intlLocale(), { maximumFractionDigits: 2 });
const percent = (r: QualityRate) => r.rate === null ? "—" : (r.rate * 100).toLocaleString(intlLocale(), { maximumFractionDigits: 1 }) + "%";
const date = (value: string) => new Date(value).toLocaleDateString(intlLocale(), { timeZone: "UTC", month: "short", day: "numeric" });

const EMPTY: QualityRate = { numerator: 0, denominator: 0, rate: null };

function Metric({ label, value = EMPTY, previous = EMPTY }: { label: string; value?: QualityRate; previous?: QualityRate }) {
  return <article className="admin-metric">
    <h3>{t(label)}</h3>
    <div className="admin-metric-value"><strong>{percent(value)}</strong>
      <span className="muted small">{value.denominator ? `${value.numerator} / ${value.denominator}` : t("adminNoSample")}</span></div>
    <p className="muted small">{t("adminPrevious")}: {percent(previous)}</p>
  </article>;
}

function Review({ closure, onSaved }: { closure: ClosureReview; onSaved: () => void }) {
  const [verdict, setVerdict] = useState<ReviewVerdict>(closure.review?.verdict ?? "unknown");
  const [reason, setReason] = useState(closure.review?.reason ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save() {
    setBusy(true); setError("");
    try { await api.reviewClosure(closure.id, verdict, reason.trim()); onSaved(); }
    catch (err) { setError(err instanceof Error ? err.message : t("操作失败")); }
    finally { setBusy(false); }
  }
  const badge = closure.review?.verdict === "false_close" ? "urgent" : closure.review?.verdict === "correct" ? "ok" : "";
  return <details className="admin-review">
    <summary><span className="admin-row-text"><b>{closure.title}</b><span className="muted small">{closure.user} · {date(closure.closed_at)}</span></span>
      <span className={`badge ${badge}`}>{t(closure.review ? `adminVerdict.${closure.review.verdict}` : "adminUnreviewed")}</span><Icon name="chevron" /></summary>
    <div className="admin-row-detail">
      <dl className="admin-conclusion"><dt>{t("adminOriginal")}</dt><dd>{closure.instruction}</dd>
        <dt>{t("adminConclusion")}</dt><dd>{closure.result}</dd></dl>
      {closure.criteria.length === 0 && <p className="muted small">{t("adminLegacy")}</p>}
      <ul className="admin-evidence">{closure.criteria.map(c => <li key={c.id}><b>{c.text}</b><CriterionEvidence item={c} /></li>)}</ul>
      <form onSubmit={e => { e.preventDefault(); void save(); }}>
        <label>{t("adminReviewVerdict")}<select disabled={busy} value={verdict} onChange={e => setVerdict(e.target.value as ReviewVerdict)}>
          {(["unknown", "correct", "false_close"] as const).map(v => <option value={v} key={v}>{t(`adminVerdict.${v}`)}</option>)}
        </select></label>
        <label>{t("adminReviewReason")}<textarea required disabled={busy} maxLength={2000} rows={3} value={reason} placeholder={t("adminReviewHint")} onChange={e => setReason(e.target.value)} /></label>
        {error && <p role="alert" className="error-text">{error}</p>}
        <button className="btn primary" disabled={busy || !reason.trim()}>{t(busy ? "saving" : "adminSaveReview")}</button>
      </form>
    </div>
  </details>;
}

const pct = (v: number | null) => v === null ? "—" : (v * 100).toLocaleString(intlLocale(), { maximumFractionDigits: 1 }) + "%";
const SOURCES: Record<string, string> = { p2p: "私聊", group: "群聊", mail: "邮件", approval: "审批", invitation: "会议邀请", task: "飞书任务", attendance: "考勤", meeting: "会议纪要" };

/** 提醒准不准：来自真实卡片上的“已处理 / 不用跟了（原因）”。只有数字。 */
function Reminders({ days }: { days: number }) {
  const [data, setData] = useState<ReminderQuality | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => { setData(null); void api.reminderQuality(days).then(setData).catch(() => setError(true)); }, [days]);
  if (error) return <p className="error-text">{t("操作失败")}</p>;
  if (!data) return <p role="status" className="muted">{t("loading")}</p>;
  const tile = (label: string, value: string, note: string) => <article className="admin-metric"><h3>{t(label)}</h3>
    <div className="admin-metric-value"><strong>{value}</strong><span className="muted small">{note}</span></div></article>;
  return <section aria-labelledby="admin-reminders-title">
    <div className="admin-section-head"><div><h2 id="admin-reminders-title">{t("提醒准不准")}</h2>
      <p className="muted small">{t("来自真实卡片上的反馈：提醒后处理算准，提醒前已处理 / 不归我 / 不值得 / 重复算不准；没反应的单独统计。")}</p></div></div>
    <div className="admin-metrics">
      {tile("提醒准确率", pct(data.total.accuracy), t("{count} 件有反馈", { count: data.total.judged }))}
      {tile("迟到率", pct(data.total.late), t("提醒前就处理了"))}
      {tile("推送的事", String(data.total.pushed), t("{count} 件没反应", { count: data.total.no_response }))}
      {tile("先放后台的候选", String(data.total.candidates), t("拿不准、没有打扰用户"))}
    </div>
    {Object.keys(data.by_source).length > 0 && <div className="admin-table-wrap" tabIndex={0} role="region" aria-label={t("按来源")}><table>
      <thead><tr><th>{t("来源")}</th><th>{t("提醒准确率")}</th><th>{t("迟到率")}</th><th>{t("有反馈")}</th></tr></thead>
      <tbody>{Object.entries(data.by_source).map(([source, r]) => <tr key={source}><th scope="row">{t(SOURCES[source] ?? source)}</th>
        <td>{pct(r.accuracy)}</td><td>{pct(r.late)}</td><td>{r.judged}</td></tr>)}</tbody></table></div>}
    {data.users.length > 0 && <div className="admin-table-wrap" tabIndex={0} role="region" aria-label={t("按人")}><table>
      <thead><tr><th>{t("用户")}</th><th>{t("推送的事")}</th><th>{t("提醒准确率")}</th><th>{t("迟到率")}</th><th>{t("没反应")}</th><th>{t("新建（私聊）")}</th><th>{t("先放后台的候选")}</th></tr></thead>
      <tbody>{data.users.map(r => <tr key={r.user}><th scope="row">{r.user}</th><td>{r.pushed}</td><td>{pct(r.accuracy)}</td><td>{pct(r.late)}</td>
        <td>{r.no_response}</td><td>{Object.values(r.created).reduce((a, b) => a + b, 0)}（{r.created.p2p ?? 0}）</td><td>{r.candidates}</td></tr>)}</tbody></table></div>}
  </section>;
}

function Quality() {
  const [days, setDays] = useState(7);
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<{ rows: NotificationStats[]; previous: NotificationStats[]; quality: QualityStats; oldQuality: QualityStats } | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  useEffect(() => {
    let cancelled = false;
    setData(null); setError("");
    void Promise.all([api.notificationStats(days), api.notificationStats(days, days), api.qualityStats(days), api.qualityStats(days, days)])
      .then(([rows, previous, quality, oldQuality]) => { if (!cancelled) setData({ rows, previous, quality, oldQuality }); })
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : t("loadError")); });
    return () => { cancelled = true; };
  }, [days, revision]);
  const refresh = () => setRevision(v => v + 1);
  const rows = data?.rows.filter(row => row.user.toLocaleLowerCase().includes(search.toLocaleLowerCase())) ?? [];
  return <main className="thread"><div className="thread-scroll"><div className="admin-page">
    <header className="admin-header"><h1>{t("adminTitle")}</h1>
      <div className="admin-controls"><select aria-label={t("adminWindow")} value={days} onChange={e => setDays(Number(e.target.value))}>
        {[7, 14, 30].map(n => <option key={n} value={n}>{t("adminDays", { count: n })}</option>)}</select>
        <button className="btn secondary" onClick={refresh}><Icon name="refresh" />{t("adminRefresh")}</button></div></header>
    {error ? <div role="alert"><p className="error-text">{error}</p><button className="btn secondary" onClick={refresh}>{t("retry")}</button></div>
      : !data ? <p role="status" className="muted">{t("loading")}</p> : <>
        <section aria-labelledby="admin-quality-title">
          <div className="admin-section-head"><h2 id="admin-quality-title">{t("adminQuality")}</h2>
            <span className="muted small">{date(data.quality.start)} – {date(new Date(new Date(data.quality.end).getTime() - 86400000).toISOString())} · UTC</span></div>
          <div className="admin-metrics">{metrics.map(([label, key]) => <Metric key={key} label={label} value={data.quality[key]} previous={data.oldQuality[key]} />)}</div>
          <div className="admin-quality-foot"><p className="muted small">{t("adminCoverage", { count: data.quality.review_coverage.numerator, total: data.quality.review_coverage.denominator })}
            <span>{t("adminUnknown", { count: data.quality.verification_unknown })}</span></p>
            <details className="admin-definitions"><summary>{t("adminDefinitions")}<Icon name="chevron" size={13} /></summary>
              <dl>{metrics.map(([label, , description]) => <div key={label}><dt>{t(label)}</dt><dd>{t(description)}</dd></div>)}<div><dt>{t("adminNotifications")}</dt><dd>{t("adminNotificationDef")}</dd></div></dl>
              <p className="muted small">{t("adminCollectionStart")}: {data.quality.coverage_start ? new Date(data.quality.coverage_start).toLocaleString(intlLocale()) : t("adminNoSample")}</p>
            </details></div>
        </section>
        <Reminders days={days} />
        <section aria-labelledby="admin-notifications-title"><div className="admin-section-head"><div><h2 id="admin-notifications-title">{t("adminNotifications")}</h2><p className="muted small">{t("adminNotificationWindow")}</p></div>
          <input className="admin-search" type="search" aria-label={t("adminFindUser")} placeholder={t("adminFindUser")} value={search} onChange={e => setSearch(e.target.value)} /></div>
          <div className="admin-list">{!rows.length ? <p className="empty-note">{t("adminNoRows")}</p> : rows.map(row => {
            const old = data.previous.find(p => p.user_id === row.user_id);
            const entries = Object.entries(row.days);
            const total = entries.reduce((n, [, d]) => n + d.pushes, 0);
            const max = Math.max(1, ...entries.map(([, d]) => d.pushes));
            return <details key={row.user_id} className="admin-person"><summary>
              <span className="avatar" aria-hidden="true">{row.user.slice(0, 1)}</span>
              <span className="admin-row-text"><b>{row.user}</b><span className="muted small">{t("adminPushTotal", { count: total, days: row.observed_days })}</span></span>
              <span className="admin-row-number"><b>{number(row.pushes_per_day)} <small>{t("adminPerDay")}</small></b><span className="muted small">{t("adminPrevious")}: {old ? number(old.pushes_per_day) : "—"}</span></span><Icon name="chevron" />
            </summary><div className="admin-row-detail">
              <p className="muted small">{entries[0]?.[0]} – {entries.at(-1)?.[0]} · {row.timezone}</p>
              <div className="admin-bars" aria-label={t("adminDailyPushes")}>{entries.map(([day, d]) => <div key={day} className="admin-bar-column" title={`${day}: ${d.pushes}`}>
                <span>{d.pushes}</span><div style={{ height: `${d.pushes / max * 64}px` }} /><small>{day.slice(8)}</small></div>)}</div>
              <div className="admin-table-wrap" tabIndex={0} role="region" aria-label={t("adminDailyDetail")}><table><caption className="sr-only">{t("adminDailyDetail")}</caption><thead><tr><th>{t("adminDate")}</th><th>{t("adminPushes")}</th>
                {kinds.map(k => <th key={k}>{t(`push.${k}`)}</th>)}<th>{t("adminItems")}</th><th>{t("adminHandled")}</th></tr></thead>
                <tbody>{entries.map(([day, d]) => <tr key={day}><th scope="row">{day}</th><td>{d.pushes}</td>{kinds.map(k => <td key={k}>{d[k]}</td>)}<td>{d.items}</td><td>{d.handled}</td></tr>)}</tbody></table></div>
            </div></details>;
          })}</div>
        </section>
        <section aria-labelledby="admin-reviews-title"><div className="admin-section-head"><h2 id="admin-reviews-title">{t("adminClosureReviews")}</h2>
          <span className="muted small">{t("adminCompleted", { count: data.quality.closed_total })}</span></div>
          {data.quality.closures.length === 0 && <p className="empty-note">{t("adminNoClosures")}</p>}
          {data.quality.closed_total > data.quality.closures.length && <p className="muted small">{t("adminRecentLimit")}</p>}
          <div className="admin-list">{data.quality.closures.map(closure => <Review key={`${closure.id}-${closure.review?.at ?? "new"}`} closure={closure} onSaved={refresh} />)}</div>
        </section>
      </>}
  </div></div></main>;
}

export default function Admin() {
  const [tab, setTab] = useState<"quality" | "performance" | "eval">("quality");
  return <><nav className="admin-tabs" aria-label={t("perfAdminNav")}>
    <button className="btn secondary" aria-pressed={tab === "quality"} onClick={() => setTab("quality")}>{t("adminQuality")}</button>
    <button className="btn secondary" aria-pressed={tab === "performance"} onClick={() => setTab("performance")}>{t("perfTitle")}</button>
    <button className="btn secondary" aria-pressed={tab === "eval"} onClick={() => setTab("eval")}>{t("新旧链路评估")}</button>
  </nav>{tab === "quality" ? <Quality /> : tab === "performance" ? <Performance /> : <div className="admin-page"><EvalSummary /></div>}</>;
}
