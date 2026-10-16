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
          <Icon name="x" size={12} /> 收起
        </button>
        <ItemCard item={item} onChanged={onChanged} />
      </div>
    );
  }
  const overdue = item.due_at && new Date(item.due_at).getTime() < Date.now();
  const sub = item.ask;
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
  const [expanded, setExpanded] = useState(true);
  const [openId, setOpenId] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const run = async (key: string, task: () => Promise<unknown>) => {
    setBusy(key);
    try {
      await task();
      onChanged();
    } finally {
      setBusy(null);
    }
  };

  const columns: [string, string, FollowUp[]][] = [
    ["me", "等你", board.me],
    ["others", "等别人", board.others],
  ];

  return (
    <section className={`board ${expanded ? "" : "collapsed"}`}>
      <header className="board-head">
        <button className="board-toggle" onClick={() => setExpanded(!expanded)}>
          <span className="status-dot" />
          <strong>Relay 正在跟进</strong>
          <span className="board-counts">
            等你 <b>{board.me.length}</b> · 等别人 <b>{board.others.length}</b> · Relay 在办 <b>{board.relay.length}</b>
          </span>
          <Icon name="chevron" size={14} />
        </button>
        <span className="board-tools">
          {status?.source_errors ? <span className="status-warn">{status.source_errors} 个数据源出错</span> : null}
          <span className="muted">{status?.last_synced_at ? `${relative(status.last_synced_at)}同步` : "尚未同步"}</span>
          <button className="btn ghost small" disabled={!!busy} onClick={() => run("sync", api.syncNow)} title="立即同步">
            <Icon name="refresh" size={14} /> {busy === "sync" ? "同步中" : "同步"}
          </button>
          <button className="btn ghost small" disabled={!!busy} onClick={() => run("brief", api.briefNow)} title="现在给我一份简报">
            <Icon name="sun" size={14} /> {busy === "brief" ? "生成中" : "简报"}
          </button>
        </span>
      </header>
      {expanded && (
        <div className="board-columns">
          {columns.map(([key, label, list]) => (
            <div key={key} className="board-column">
              <div className="board-column-head">
                {label} <span className="muted">{list.length}</span>
              </div>
              {list.length === 0 && <div className="board-empty">{key === "me" ? "没有等你处理的事" : "没有在等别人的事"}</div>}
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
              Relay 在办 <span className="muted">{board.relay.length}</span>
            </div>
            {board.relay.length === 0 && <div className="board-empty">暂时没有</div>}
            {board.relay.map((task, index) => (
              <div key={index} className="board-row static">
                <span className="board-row-title">
                  <Icon name={task.kind === "meeting_prep" ? "calendar" : "clock"} size={13} /> {task.title}
                </span>
                <span className="board-row-sub">{task.detail}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
