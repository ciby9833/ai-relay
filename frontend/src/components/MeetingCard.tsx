import { t } from "../i18n";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type Meeting } from "../api";
import { dayLabel, timeOf } from "../format";
import Icon from "./Icon";

const RSVP: Record<string, string> = { accept: "已接受", decline: "已拒绝", tentative: "待定", needs_action: "未回复邀请" };
const SOURCE: Record<string, string> = { agenda: "议程", doc: "文档", minutes: "纪要", actions: "行动项", mail: "邮件", chat: "聊天" };

function safeUrl(url: string | null) {
  return url && /^https:\/\//.test(url) ? url : null;
}

/** 一个会：会前准备（依据可展开）、会后纪要和行动项。参加、回复邀请、会后承诺分开显示。 */
export function MeetingCard({ meeting, past, onChanged }: { meeting: Meeting; past: boolean; onChanged: (m: Meeting) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const prepare = async () => {
    setBusy(true);
    setError(false);
    try {
      onChanged(await api.prepareMeeting(meeting.id));
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };
  const join = safeUrl(meeting.meeting_url);
  return (
    <article className="meeting-card">
      <header className="meeting-head">
        <span className="meeting-time">{meeting.start ? `${dayLabel(meeting.start)} ${meeting.all_day ? t("全天") : timeOf(meeting.start)}` : ""}</span>
        <strong className="meeting-title">{meeting.title}</strong>
        {meeting.rsvp && !past && (
          <span className={`badge ${meeting.rsvp === "needs_action" ? "warn" : ""}`}>{t(RSVP[meeting.rsvp] ?? meeting.rsvp)}</span>
        )}
      </header>
      <p className="muted small">
        {[meeting.organizer && t("组织者：{name}", { name: meeting.organizer }), meeting.location].filter(Boolean).join(" · ")}
      </p>
      {!past && (
        <section className="meeting-prep">
          {meeting.prep ? (
            <>
              <div className="meeting-prep-text"><Markdown remarkPlugins={[remarkGfm]}>{meeting.prep.text}</Markdown></div>
              {meeting.prep.sources.length > 0 && (
                <details className="meeting-sources">
                  <summary>{t("依据（{count} 份材料）", { count: meeting.prep.sources.length })}</summary>
                  <ul>
                    {meeting.prep.sources.map((s, n) => (
                      <li key={n}>
                        <span className="badge">{t(SOURCE[s.kind] ?? s.kind)}</span>{" "}
                        {safeUrl(s.url) ? <a href={safeUrl(s.url)!} target="_blank" rel="noreferrer">{s.title}</a> : s.title}
                        <span className="muted small"> · {s.why}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          ) : (
            <p className="muted small">{t("会前 Relay 会只用和这个会确实相关的材料整理准备；也可以现在就整理。")}</p>
          )}
        </section>
      )}
      {past && (
        <section className="meeting-prep">
          {meeting.minutes ? (
            <p>
              <Icon name="external" size={13} />{" "}
              {safeUrl(meeting.minutes.url) ? <a href={safeUrl(meeting.minutes.url)!} target="_blank" rel="noreferrer">{meeting.minutes.title}</a> : meeting.minutes.title}
              <span className="muted small"> · {t("纪要里有 {count} 个行动项", { count: meeting.minutes.actions })}</span>
            </p>
          ) : (
            <p className="muted small">{meeting.minutes_missing ? t("没有找到这次会的纪要，没有提取行动项。") : t("会后会去找这次会的纪要，找到后提取行动项。")}</p>
          )}
        </section>
      )}
      {meeting.actions.length > 0 && (
        <ul className="meeting-actions">
          {meeting.actions.map((a) => (
            <li key={a.id} className={a.status === "open" ? "" : "done"}>
              {a.status === "open" ? "○" : "✓"} {a.title}
              {a.status !== "open" && a.resolution && <span className="muted small"> · {a.resolution}</span>}
            </li>
          ))}
        </ul>
      )}
      <footer className="meeting-foot">
        {join && !past && <a className="btn primary small" href={join} target="_blank" rel="noreferrer">{t("加入会议")}</a>}
        {safeUrl(meeting.url) && <a className="btn ghost small" href={safeUrl(meeting.url)!} target="_blank" rel="noreferrer">{t("在飞书查看")}</a>}
        {!past && (
          <button className="btn secondary small" disabled={busy} onClick={prepare}>
            {busy ? t("整理中…") : meeting.prep ? t("重新整理") : t("现在整理会前准备")}
          </button>
        )}
        {error && <span className="card-error">{t("操作失败")}</span>}
      </footer>
    </article>
  );
}
