import { localize, t } from "../i18n";
import { useCallback, useEffect, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type Board, type FollowUp, type HomeStatus, type MeetingsData, type ProgressData } from "../api";
import { dayLabel, relative, timeOf } from "../format";
import { ItemCard } from "./cards";
import Icon from "./Icon";
import { MeetingCard } from "./MeetingCard";

export type TrackerTab = "todo" | "meetings";
export type TrackerFocus = { tab: TrackerTab; itemIds?: number[]; n: number };

/** 现在要处理：紧急、今天到期（或已过期）、他说过要立刻知道的 */
function isNow(item: FollowUp) {
  if (item.importance === "urgent" || item.attention === "now") return true;
  if (!item.due_at) return false;
  const end = new Date();
  end.setHours(23, 59, 59, 999);
  return new Date(item.due_at).getTime() <= end.getTime();
}

function Row({ item, highlight, onOpen }: { item: FollowUp; highlight: boolean; onOpen: () => void }) {
  const overdue = item.due_at && new Date(item.due_at).getTime() < Date.now();
  return (
    <button className={`ws-row ${highlight ? "active" : ""} ${item.importance === "urgent" ? "urgent" : ""}`} onClick={onOpen}>
      <span className="ws-row-title">{item.title}</span>
      <span className="ws-row-sub">
        {item.due_at && <span className={overdue ? "due overdue" : "due"}>{dayLabel(item.due_at)} {timeOf(item.due_at)}</span>}
        {localize(item.ask_ui, item.ask)}
      </span>
    </button>
  );
}

/** 最近进展：有了结果的事和发过的汇总、简报，按时间排的日志。默认收起。 */
function Log({ data }: { data: ProgressData | null }) {
  const entries = [
    ...(data?.days.flatMap((d) => d.items.map((i) => ({ at: i.closed_at, text: i.title, note: i.resolution, done: i.status === "done" }))) ?? []),
  ].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 30);
  return (
    <details className="tracker-log">
      <summary>{t("最近进展")} <span className="muted">{entries.length}</span></summary>
      {entries.length === 0 && (data?.notes.length ?? 0) === 0 && <p className="ws-empty small">{t("最近 7 天还没有结果。")}</p>}
      <ol>
        {entries.map((e, n) => (
          <li key={n}>
            <span className="muted small">{relative(e.at)}</span> {e.done ? "✓" : "–"} {e.text}
            {e.note && <span className="muted small"> · {e.note}</span>}
          </li>
        ))}
      </ol>
      {data?.notes.map((note, n) => (
        <details key={n} className="progress-note">
          <summary>{note.kind === "brief" ? t("简报") : t("汇总")} · {relative(note.created_at)}</summary>
          <Markdown remarkPlugins={[remarkGfm]}>{note.text}</Markdown>
        </details>
      ))}
    </details>
  );
}

/** Relay 在跟进：待处理和会议；最近进展是底部的日志。放在对话旁边（窄屏时是浮层），对话用来解释、追问和委托。 */
export default function Tracker({
  focus,
  onAsk,
  onClose,
  onCounts,
}: {
  focus: TrackerFocus | null;
  onAsk: (item: FollowUp) => void;
  onClose?: () => void;
  onCounts?: (count: number) => void;
}) {
  const [tab, setTab] = useState<TrackerTab>("todo");
  const [board, setBoard] = useState<Board | null>(null);
  const [status, setStatus] = useState<HomeStatus | null>(null);
  const [meetings, setMeetings] = useState<MeetingsData | null>(null);
  const [progress, setProgress] = useState<ProgressData | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [highlight, setHighlight] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    const [b, home, m, p] = await Promise.all([api.board(), api.home(), api.meetings(), api.progress()]);
    setBoard({ me: b?.me ?? [], others: b?.others ?? [], relay: b?.relay ?? [] });
    setStatus(home?.status ?? null);
    setMeetings({ upcoming: m?.upcoming ?? [], recent: m?.recent ?? [] });
    setProgress({ days: p?.days ?? [], notes: p?.notes ?? [] });
    onCounts?.(b?.me?.length ?? 0);
  }, [onCounts]);
  useEffect(() => {
    void load().catch(() => setError(true));
    const timer = window.setInterval(() => void load().catch(() => undefined), 30_000);
    return () => window.clearInterval(timer);
  }, [load]);
  // 从对话里的提醒点进来：切到对应的分组，那几件高亮，只有一件时直接打开
  useEffect(() => {
    if (!focus) return;
    setTab(focus.tab);
    setHighlight(focus.itemIds ?? []);
    setSelected(focus.itemIds?.length === 1 ? focus.itemIds[0] : null);
  }, [focus]);

  const sync = async () => {
    setBusy(true);
    setError(false);
    try {
      await api.syncNow();
      await load();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };

  const all = [...(board?.me ?? []), ...(board?.others ?? [])];
  const item = all.find((i) => i.id === selected) ?? null;
  const groups: [string, string, FollowUp[]][] = board ? [
    ["now", t("现在要处理"), board.me.filter(isNow)],
    ["me", t("待处理"), board.me.filter((i) => !isNow(i))],
    ["others", t("在等别人"), board.others],
  ] : [];
  const today = meetings?.upcoming.filter((m) => m.start && new Date(m.start).toDateString() === new Date().toDateString()).length ?? 0;

  return (
    <aside className="tracker" aria-label={t("Relay 在跟进")}>
      <header className="tracker-head">
        <strong>{t("Relay 在跟进")}</strong>
        <span className="muted small">{status?.last_synced_at ? t("{p0}同步", { p0: relative(status.last_synced_at) }) : t("尚未同步")}</span>
        <button className="icon-button" disabled={busy} onClick={sync} title={t("立即同步")} aria-label={t("立即同步")}><Icon name="refresh" size={14} /></button>
        {onClose && <button className="icon-button" onClick={onClose} aria-label={t("关闭")}><Icon name="x" size={16} /></button>}
      </header>
      <div className="tracker-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "todo"} className={tab === "todo" ? "active" : ""} onClick={() => { setTab("todo"); setSelected(null); }}>
          {t("待处理")} <span className="muted">{board?.me.length ?? 0}</span>
        </button>
        <button role="tab" aria-selected={tab === "meetings"} className={tab === "meetings" ? "active" : ""} onClick={() => { setTab("meetings"); setSelected(null); }}>
          {t("会议")} <span className="muted">{today}</span>
        </button>
      </div>
      {status?.source_errors ? <p className="status-warn small">{t("sourceErrorCount", { count: status.source_errors })}</p> : null}
      {error && <p role="alert" className="error-text small">{t("操作失败")}</p>}
      <div className="tracker-body">
        {tab === "todo" && item && (
          <div className="tracker-detail">
            <div className="ws-detail-bar">
              <button className="btn ghost small" onClick={() => setSelected(null)}>‹ {t("返回列表")}</button>
              <span className="spacer" />
              <button className="btn secondary small" onClick={() => onAsk(item)}>{t("在对话里问")}</button>
            </div>
            <ItemCard item={item} onChanged={() => void load()} />
          </div>
        )}
        {tab === "todo" && !item && board && (
          <>
            {groups.map(([key, label, list]) => (list.length > 0 || key === "now") && (
              <div key={key} className="ws-group">
                <div className="ws-group-head">{label} <span className="muted">{list.length}</span></div>
                {list.length === 0 && <div className="ws-empty small">{t("现在没有要你马上处理的事")}</div>}
                {list.map((i) => <Row key={i.id} item={i} highlight={highlight.includes(i.id)} onOpen={() => setSelected(i.id)} />)}
              </div>
            ))}
            {board.relay.length > 0 && (
              <div className="ws-group">
                <div className="ws-group-head">{t("Relay 在盯着")} <span className="muted">{board.relay.length}</span></div>
                {board.relay.map((task, index) => (
                  <div key={index} className="ws-row static">
                    <span className="ws-row-title"><Icon name="clock" size={13} /> {localize(task.title_ui, task.title)}</span>
                    <span className="ws-row-sub">{localize(task.detail_ui, task.detail)}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
        {tab === "meetings" && meetings && (
          <>
            {meetings.upcoming.length === 0 && <p className="ws-empty small">{t("接下来 3 天没有会。")}</p>}
            {meetings.upcoming.map((m) => (
              <MeetingCard key={m.id} meeting={m} past={false}
                onChanged={(next) => setMeetings((d) => d && { ...d, upcoming: d.upcoming.map((x) => (x.id === next.id ? next : x)) })} />
            ))}
            {meetings.recent.length > 0 && <div className="ws-group-head">{t("刚开过的")} <span className="muted">{meetings.recent.length}</span></div>}
            {meetings.recent.map((m) => <MeetingCard key={m.id} meeting={m} past onChanged={() => undefined} />)}
          </>
        )}
        {!board && !error && <p className="ws-empty">{t("loading")}</p>}
      </div>
      <Log data={progress} />
    </aside>
  );
}
