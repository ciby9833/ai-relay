import { localize, t } from "../i18n";
import { useCallback, useEffect, useState } from "react";
import { api, type Board, type FollowUp, type HomeStatus } from "../api";
import { dayLabel, relative, timeOf } from "../format";
import { ItemCard } from "./cards";
import Icon from "./Icon";

/** 现在要处理：紧急、今天到期（或已过期）、他说过要立刻知道的 */
function isNow(item: FollowUp) {
  if (item.importance === "urgent" || item.attention === "now") return true;
  if (!item.due_at) return false;
  const end = new Date();
  end.setHours(23, 59, 59, 999);
  return new Date(item.due_at).getTime() <= end.getTime();
}

function Row({ item, active, onOpen }: { item: FollowUp; active: boolean; onOpen: () => void }) {
  const overdue = item.due_at && new Date(item.due_at).getTime() < Date.now();
  return (
    <button className={`ws-row ${active ? "active" : ""} ${item.importance === "urgent" ? "urgent" : ""}`} onClick={onOpen}
      aria-current={active ? "true" : undefined}>
      <span className="ws-row-title">{item.title}</span>
      <span className="ws-row-sub">
        {item.due_at && <span className={overdue ? "due overdue" : "due"}>{dayLabel(item.due_at)} {timeOf(item.due_at)}</span>}
        {localize(item.ask_ui, item.ask)}
      </span>
    </button>
  );
}

/** 待处理：需要他做的事和他在等的事。左边列表、右边详情（手机上点进去全屏，返回回到列表）。 */
export default function Inbox({ onAsk }: { onAsk: (item: FollowUp) => void }) {
  const [board, setBoard] = useState<Board | null>(null);
  const [status, setStatus] = useState<HomeStatus | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    const [data, home] = await Promise.all([api.board(), api.home()]);
    setBoard(data);
    setStatus(home.status);
  }, []);
  useEffect(() => {
    void load().catch(() => setError(true));
    const timer = window.setInterval(() => void load().catch(() => undefined), 30_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const run = async (key: string, task: () => Promise<unknown>) => {
    setBusy(key);
    setError(false);
    try {
      await task();
      await load();
    } catch {
      setError(true);
    } finally {
      setBusy(null);
    }
  };

  if (!board) return <main className="workspace"><p className="ws-empty">{error ? t("操作失败") : t("loading")}</p></main>;

  const now = board.me.filter(isNow);
  const later = board.me.filter((i) => !isNow(i));
  const groups: [string, string, FollowUp[]][] = [
    ["now", t("现在要处理"), now],
    ["me", t("待处理"), later],
    ["others", t("在等别人"), board.others],
  ];
  const all = [...board.me, ...board.others];
  const item = all.find((i) => i.id === selected) ?? null;

  return (
    <main className={`workspace ${item ? "has-detail" : ""}`}>
      <section className="ws-list" aria-label={t("待处理")}>
        <header className="ws-head">
          <h1>{t("待处理")}</h1>
          <span className="ws-tools">
            {status?.source_errors ? <span className="status-warn">{t("sourceErrorCount", { count: status.source_errors })}</span> : null}
            <span className="muted small">{status?.last_synced_at ? t("{p0}同步", { p0: relative(status.last_synced_at) }) : t("尚未同步")}</span>
            <button className="btn ghost small" disabled={!!busy} onClick={() => run("sync", api.syncNow)} title={t("立即同步")}>
              <Icon name="refresh" size={14} /> {busy === "sync" ? t("同步中") : t("同步")}
            </button>
          </span>
        </header>
        {error && <p role="alert" className="error-text">{t("操作失败")}</p>}
        {groups.map(([key, label, list]) => (list.length > 0 || key === "now") && (
          <div key={key} className="ws-group">
            <div className="ws-group-head">{label} <span className="muted">{list.length}</span></div>
            {list.length === 0 && <div className="ws-empty small">{t("现在没有要你马上处理的事")}</div>}
            {list.map((i) => <Row key={i.id} item={i} active={i.id === selected} onOpen={() => setSelected(i.id)} />)}
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
      </section>
      <section className="ws-detail" aria-label={t("详情")}>
        {item ? (
          <>
            <div className="ws-detail-bar">
              <button className="btn ghost small ws-back" onClick={() => setSelected(null)}>
                ‹ {t("返回列表")}
              </button>
              <span className="spacer" />
              <button className="btn secondary small" onClick={() => onAsk(item)}>
                <Icon name="plus" size={14} /> {t("问 Relay")}
              </button>
            </div>
            <ItemCard item={item} onChanged={() => void load()} />
          </>
        ) : (
          <p className="ws-empty">{t("选一件事，看发生了什么、依据和准备好的下一步。")}</p>
        )}
      </section>
    </main>
  );
}
