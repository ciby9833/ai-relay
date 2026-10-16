import { localize, t } from "../i18n";
import { useState } from "react";
import { api, type Board as BoardData, type FollowUp, type HomeStatus } from "../api";
import { dayLabel, relative, timeOf } from "../format";
import { ItemCard } from "./cards";
import Icon from "./Icon";

function Row({ item, open, onToggle, onChanged }: { item: FollowUp; open: boolean; onToggle: () => void; onChanged: () => void }) {
  if (open) {
    return (
      <div className="board-open">
        <button className="board-collapse" onClick={onToggle}>
          <Icon name="x" size={12} /> {t("收起")}
        </button>
        <ItemCard item={item} onChanged={onChanged} />
      </div>
    );
  }
  const overdue = item.due_at && new Date(item.due_at).getTime() < Date.now();
  const sub = localize(item.ask_ui, item.ask);
  return (
    <button className={`board-row ${item.importance === "urgent" ? "urgent" : ""}`} onClick={onToggle}>
      <span className="board-row-title">{item.title}</span>
      <span className="board-row-sub">
        {item.due_at && <span className={overdue ? "due overdue" : "due"}>{dayLabel(item.due_at)} {timeOf(item.due_at)}</span>}
        {sub}
      </span>
    </button>
  );
}

export default function Board({
  board,
  status,
  onChanged,
}: {
  board: BoardData;
  status: HomeStatus | null;
  onChanged: () => void;
}) {
  const [expanded, setExpanded] = useState(() => !window.matchMedia("(max-width: 600px)").matches);
  const [openId, setOpenId] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState(false);

  const run = async (key: string, task: () => Promise<unknown>) => {
    setBusy(key);
    setError(false);
    try {
      await task();
      onChanged();
    } catch {
      setError(true);
    } finally {
      setBusy(null);
    }
  };

  const columns: [string, string, FollowUp[]][] = [
    ["me", t("等你"), board.me],
    ["others", t("等别人"), board.others],
  ];

  return (
    <section className={`board ${expanded ? "" : "collapsed"}`}>
      <header className="board-head">
        <button className="board-toggle" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
          <span className="status-dot" />
          <strong>{t("Relay 正在跟进")}</strong>
          <span className="board-counts">
            {t("等你")} <b>{board.me.length}</b>  {t("· 等别人")} <b>{board.others.length}</b>  {t("· Relay 在办")} <b>{board.relay.length}</b>
          </span>
          <Icon name="chevron" size={14} />
        </button>
        <span className="board-tools">
          {status?.source_errors ? <span className="status-warn">{t("sourceErrorCount", { count: status.source_errors })}</span> : null}
          <span className="muted">{status?.last_synced_at ? t("{p0}同步", { p0: relative(status.last_synced_at) }) : t("尚未同步")}</span>
          <button className="btn ghost small" disabled={!!busy} onClick={() => run("sync", api.syncNow)} title={t("立即同步")}>
            <Icon name="refresh" size={14} /> {busy === "sync" ? t("同步中") : t("同步")}
          </button>
          <button className="btn ghost small" disabled={!!busy} onClick={() => run("brief", api.briefNow)} title={t("现在给我一份简报")}>
            <Icon name="sun" size={14} /> {busy === "brief" ? t("生成中") : t("简报")}
          </button>
        </span>
      </header>
      {error && <p role="alert" className="error-text board-error">{t("操作失败")}</p>}
      {expanded && (
        <div className="board-columns">
          {columns.map(([key, label, list]) => (
            <div key={key} className="board-column">
              <div className="board-column-head">
                {label} <span className="muted">{list.length}</span>
              </div>
              {list.length === 0 && <div className="board-empty">{key === "me" ? t("没有等你处理的事") : t("没有在等别人的事")}</div>}
              {list.map((item) => (
                <Row
                  key={item.id}
                  item={item}
                  open={openId === item.id}
                  onToggle={() => setOpenId(openId === item.id ? null : item.id)}
                  onChanged={onChanged}
                />
              ))}
            </div>
          ))}
          <div className="board-column">
            <div className="board-column-head">
              {t("Relay 在办")} <span className="muted">{board.relay.length}</span>
            </div>
            {board.relay.length === 0 && <div className="board-empty">{t("暂时没有")}</div>}
            {board.relay.map((task, index) => (
              <div key={index} className="board-row static">
                <span className="board-row-title">
                  <Icon name={task.kind === "meeting_prep" ? "calendar" : "clock"} size={13} /> {localize(task.title_ui, task.title)}
                </span>
                <span className="board-row-sub">{localize(task.detail_ui, task.detail)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
