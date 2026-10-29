import { localize, t } from "../i18n";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type FollowUp, type Meeting, type MeetingSource } from "../api";
import { dayLabel, relative, timeOf } from "../format";
import { approvalGroup, conflicts, isMail, isNow, type Work } from "../work";
import { ItemCard } from "./cards";
import Icon from "./Icon";
import type { WorkView } from "./WorkDock";

/** 带进对话的对象：输入框上方显示成可移除的标签，发送时附上 */
export type AskContext = { label: string; ref: string };

type Entry =
  | { type: "item"; id: number }
  | { type: "group"; name: string }
  | { type: "meeting"; id: number }
  | { type: "source"; source: MeetingSource; meeting: string };

const RSVP: Record<string, [string, string]> = {
  accept: ["已接受", "ok"], tentative: ["待定", "warn"], needs_action: ["待回复邀请", "warn"], decline: ["已拒绝", ""],
};
const SOURCE: Record<string, string> = { agenda: "议程", doc: "文档", minutes: "纪要", actions: "行动项", mail: "邮件", chat: "聊天" };
const safe = (url: string | null | undefined) => (url && /^https:\/\//.test(url) ? url : null);

function meetingContext(m: Meeting): AskContext {
  const when = m.start ? `${dayLabel(m.start)} ${timeOf(m.start)}` : "";
  return { label: `${t("会议")}：${m.title}`, ref: t("关于会议《{title}》（{when}）：", { title: m.title, when }) };
}

function itemContext(item: FollowUp): AskContext {
  return { label: item.title, ref: t("关于 #{id}《{title}》：", { id: item.id, title: item.title }) };
}

function ItemRow({ item, onOpen, highlight }: { item: FollowUp; onOpen: () => void; highlight?: boolean }) {
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

function MeetingRow({ meeting, all, onOpen }: { meeting: Meeting; all: Meeting[]; onOpen: () => void }) {
  const [label, tone] = RSVP[meeting.rsvp ?? ""] ?? [null, ""];
  return (
    <button className="meeting-row" onClick={onOpen}>
      <span className="meeting-row-time">
        {meeting.all_day ? t("全天") : meeting.start ? timeOf(meeting.start) : ""}
        {meeting.end && !meeting.all_day && <small>{timeOf(meeting.end)}</small>}
      </span>
      <span className="meeting-row-main">
        <strong>{meeting.title}</strong>
        {meeting.organizer && <span className="muted small">{meeting.organizer}</span>}
        <span className="meeting-row-badges">
          {label && <span className={`badge ${tone}`}>{t(label)}</span>}
          {meeting.prep?.worth_pushing && <span className="badge ok">{t("简报已就绪")}</span>}
          {meeting.minutes && <span className="badge ok">{t("有纪要")}</span>}
          {conflicts(meeting, all).length > 0 && <span className="badge warn">{t("时间重叠")}</span>}
        </span>
      </span>
      <Icon name="chevron" size={14} />
    </button>
  );
}

function MeetingDetail({ meeting, all, work, onOpen, onAsk }: {
  meeting: Meeting; all: Meeting[]; work: Work; onOpen: (entry: Entry) => void; onAsk: (ctx: AskContext) => void;
}) {
  const [tab, setTab] = useState<"prep" | "sources" | "actions">("prep");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const past = meeting.end ? new Date(meeting.end).getTime() < Date.now() : false;
  const overlap = conflicts(meeting, all);
  const [rsvp, tone] = RSVP[meeting.rsvp ?? ""] ?? [null, ""];
  const prepare = async () => {
    setBusy(true);
    setError(false);
    try {
      await api.prepareMeeting(meeting.id);
      await work.refresh();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };
  const sources = meeting.prep?.sources ?? [];
  const join = safe(meeting.meeting_url);
  return (
    <div className="detail">
      <div className="detail-badges">
        {meeting.start && <span className="badge">{dayLabel(meeting.start)} {meeting.all_day ? t("全天") : timeOf(meeting.start)}</span>}
        {rsvp && <span className={`badge ${tone}`}>{t(rsvp)}</span>}
      </div>
      <h2 className="detail-title">{meeting.title}</h2>
      <p className="detail-meta"><Icon name="clock" size={13} /> {meeting.start ? `${dayLabel(meeting.start)} ${timeOf(meeting.start)}${meeting.end ? `–${timeOf(meeting.end)}` : ""}` : ""}
        {meeting.location && ` · ${meeting.location}`}</p>
      {meeting.organizer && <p className="detail-meta"><Icon name="memory" size={13} /> {t("组织者：{name}", { name: meeting.organizer })}
        {meeting.attendees.length > 0 && ` · ${t("{count} 人参会", { count: meeting.attendees.length + 1 })}`}</p>}
      {overlap.length > 0 && (
        <p className="detail-warn">
          <Icon name="alert" size={14} /> {t("和《{title}》时间重叠。", { title: overlap[0].title })}{" "}
          <button className="link" onClick={() => onOpen({ type: "meeting", id: overlap[0].id })}>{t("查看另一场")}</button>
        </p>
      )}
      <div className="detail-tabs" role="tablist">
        {([["prep", t("会前简报")], ["sources", `${t("相关材料")} ${sources.length}`], ["actions", t("会后行动")]] as const).map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>
      {tab === "prep" && (
        meeting.prep ? (
          <div className="detail-prep"><Markdown remarkPlugins={[remarkGfm]}>{meeting.prep.text}</Markdown>
            <p className="muted small">{t("整理于 {time}，只用会前已有、和这个会确实相关的材料", { time: relative(meeting.prep.generated_at) })}</p></div>
        ) : (
          <p className="ws-empty small">{past ? t("这个会已经开过了，没有整理会前简报。") : t("会前会只用和这个会确实相关的材料整理简报；也可以现在就整理。")}</p>
        )
      )}
      {tab === "sources" && (
        sources.length ? (
          <ul className="source-list">
            {sources.map((s, n) => (
              <li key={n}>
                <button className="source-row" onClick={() => onOpen({ type: "source", source: s, meeting: meeting.title })}>
                  <Icon name="doc" size={14} />
                  <span><b>{s.title}</b><span className="muted small">{t(SOURCE[s.kind] ?? s.kind)} · {s.why}</span></span>
                  <Icon name="chevron" size={13} />
                </button>
              </li>
            ))}
          </ul>
        ) : <p className="ws-empty small">{t("没有找到和这个会直接相关的材料。")}</p>
      )}
      {tab === "actions" && (
        <>
          {meeting.minutes ? (
            <p className="small">{t("纪要")}：{safe(meeting.minutes.url) ? <a href={safe(meeting.minutes.url)!} target="_blank" rel="noreferrer">{meeting.minutes.title}</a> : meeting.minutes.title}
              <span className="muted"> · {t("纪要里有 {count} 个行动项", { count: meeting.minutes.actions })}</span></p>
          ) : (
            <p className="ws-empty small">{!past ? t("会议结束后，Relay 会去找这次会的纪要，找到后提取分给你的行动项。")
              : meeting.minutes_missing ? t("没有找到这次会的纪要，没有提取行动项。") : t("正在找这次会的纪要。")}</p>
          )}
          {meeting.actions.length > 0 && (
            <ul className="meeting-actions">
              {meeting.actions.map((a) => (
                <li key={a.id} className={a.status === "open" ? "" : "done"}>
                  {a.status === "open" ? <button className="link" onClick={() => onOpen({ type: "item", id: a.id })}>○ {a.title}</button> : <>✓ {a.title}</>}
                  {a.status !== "open" && a.resolution && <span className="muted small"> · {a.resolution}</span>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {error && <p className="error-text small">{t("操作失败")}</p>}
      <footer className="detail-foot">
        <button className="btn primary block" onClick={() => onAsk(meetingContext(meeting))}><Icon name="plus" size={14} /> {t("带着这场会议问 Relay")}</button>
        <div className="detail-foot-row">
          {meeting.invitation_item_id && <button className="btn secondary small" onClick={() => onOpen({ type: "item", id: meeting.invitation_item_id! })}>{t("回复邀请")}</button>}
          {join && !past && <a className="btn secondary small" href={join} target="_blank" rel="noreferrer">{t("加入会议")}</a>}
          {safe(meeting.url) && <a className="btn ghost small" href={safe(meeting.url)!} target="_blank" rel="noreferrer">{t("在飞书查看")}</a>}
          {!past && <button className="btn ghost small" disabled={busy} onClick={prepare}>{busy ? t("整理中…") : meeting.prep ? t("重新整理") : t("现在整理")}</button>}
        </div>
      </footer>
    </div>
  );
}

/** 右侧详情栏：列表 → 详情 → 材料，逐级返回（Esc 也是）。待处理、会议、进展三个列表共用。 */
export default function Inspector({ work, view, focus, onClose, onAsk }: {
  work: Work;
  view: WorkView;
  focus: { itemIds: number[]; n: number } | null;
  onClose: () => void;
  onAsk: (ctx: AskContext) => void;
}) {
  const [stack, setStack] = useState<Entry[]>([]);
  const [toast, setToast] = useState<{ item: FollowUp; message: string } | null>(null);
  const [highlight, setHighlight] = useState<number[]>([]);
  const body = useRef<HTMLDivElement>(null);
  const top = stack[stack.length - 1];
  const open = (entry: Entry) => setStack((s) => [...s, entry]);
  const back = () => setStack((s) => s.slice(0, -1));

  useEffect(() => setStack([]), [view]);
  useEffect(() => {
    if (!focus) return;
    setHighlight(focus.itemIds);
    setStack(focus.itemIds.length === 1 ? [{ type: "item", id: focus.itemIds[0] }] : []);
  }, [focus]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || document.querySelector("dialog[open]")) return;
      if (stack.length) back();
      else onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [stack.length, onClose]);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 8000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const board = work.board;
  const items = [...(board?.me ?? []), ...(board?.others ?? [])];
  const meetings = [...(work.meetings?.upcoming ?? []), ...(work.meetings?.recent ?? [])];
  const closed = (item: FollowUp, message: string) => {
    setToast({ item, message });
    back();
  };
  const undo = async (id: number) => {
    await api.undoItem(id);
    setToast(null);
    await work.refresh();
  };
  const title = top?.type === "meeting" || top?.type === "source" ? t("会议") : top ? t("待处理")
    : view === "todo" ? t("待处理") : view === "mail" ? t("邮件") : view === "meetings" ? t("会议") : t("进展");

  const todoList = () => {
    if (!board) return null;
    const me = board.me.filter((i) => !isMail(i));
    const others = board.others.filter((i) => !isMail(i));
    const sections: [string, FollowUp[]][] = [
      [t("现在要处理"), me.filter(isNow)], [t("需要你"), me.filter((i) => !isNow(i))], [t("在等对方"), others],
    ];
    return (
      <>
        {sections.map(([label, list]) => {
          if (!list.length) return null;
          // 同一种审批放在一起看：每张仍然各自确认
          const seen = new Set<string>();
          const rows = list.flatMap((item) => {
            const name = approvalGroup(item);
            const same = name ? list.filter((i) => approvalGroup(i) === name) : [];
            if (name && same.length > 1) {
              if (seen.has(name)) return [];
              seen.add(name);
              return [(
                <button key={`g-${name}`} className="ws-row" onClick={() => open({ type: "group", name })}>
                  <span className="ws-row-title">{name}</span>
                  <span className="ws-row-sub">{t("{count} 张申请，每张单独处理", { count: same.length })}</span>
                </button>
              )];
            }
            return [<ItemRow key={item.id} item={item} highlight={highlight.includes(item.id)} onOpen={() => open({ type: "item", id: item.id })} />];
          });
          return <div key={label} className="ws-group"><div className="ws-group-head">{label} <span className="muted">{list.length}</span></div>{rows}</div>;
        })}
        {me.length + others.length === 0 && <p className="ws-empty">{t("现在没有需要你处理的事。")}</p>}
        {board.relay.length > 0 && (
          <div className="ws-group">
            <div className="ws-group-head">{t("Relay 在盯着")} <span className="muted">{board.relay.length}</span></div>
            {board.relay.map((task, index) => (
              <div key={index} className="ws-row static">
                <span className="ws-row-title">{localize(task.title_ui, task.title)}</span>
                <span className="ws-row-sub">{localize(task.detail_ui, task.detail)}</span>
              </div>
            ))}
          </div>
        )}
      </>
    );
  };

  // 邮件：只有要他回、要他看、在等对方回信的才在这里；每封带上下文，点开有草稿（收件人、回复全部的理由）、相关材料和转发
  const mailList = () => {
    if (!board) return null;
    const mails = [...board.me, ...board.others].filter(isMail);
    const sections: [string, FollowUp[]][] = [
      [t("要你回复"), mails.filter((i) => i.owner === "me" && i.kind === "reply")],
      [t("要你看"), mails.filter((i) => i.owner === "me" && i.kind !== "reply")],
      [t("在等对方回信"), mails.filter((i) => i.owner === "others")],
    ];
    return (
      <>
        {sections.map(([label, list]) => list.length > 0 && (
          <div key={label} className="ws-group">
            <div className="ws-group-head">{label} <span className="muted">{list.length}</span></div>
            {list.map((item) => <ItemRow key={item.id} item={item} highlight={highlight.includes(item.id)} onOpen={() => open({ type: "item", id: item.id })} />)}
          </div>
        ))}
        {mails.length === 0 && <p className="ws-empty">{t("没有要你处理的邮件。知会、群发和系统通知不会出现在这里。")}</p>}
      </>
    );
  };

  const meetingList = () => {
    const upcoming = work.meetings?.upcoming ?? [];
    const days = new Map<string, Meeting[]>();
    for (const m of upcoming) days.set(m.start ? dayLabel(m.start) : "", [...(days.get(m.start ? dayLabel(m.start) : "") ?? []), m]);
    const clash = upcoming.find((m) => conflicts(m, upcoming).length > 0);
    return (
      <>
        {clash && <p className="detail-warn"><Icon name="alert" size={14} /> {t("{time} 有会议时间重叠，确认一下参会安排。", { time: clash.start ? timeOf(clash.start) : "" })}</p>}
        {upcoming.length === 0 && <p className="ws-empty">{t("接下来 3 天没有会。")}</p>}
        {[...days.entries()].map(([day, list]) => (
          <div key={day} className="ws-group">
            <div className="ws-group-head">{day} <span className="muted">{t("{count} 场", { count: list.length })}</span></div>
            {list.map((m) => <MeetingRow key={m.id} meeting={m} all={upcoming} onOpen={() => open({ type: "meeting", id: m.id })} />)}
          </div>
        ))}
        {(work.meetings?.recent.length ?? 0) > 0 && (
          <div className="ws-group">
            <div className="ws-group-head">{t("刚开过的")}</div>
            {work.meetings!.recent.map((m) => <MeetingRow key={m.id} meeting={m} all={[]} onOpen={() => open({ type: "meeting", id: m.id })} />)}
          </div>
        )}
        <p className="muted small inspector-note"><Icon name="check" size={12} /> {t("只用和你及这个会相关、你有权看的材料")}</p>
      </>
    );
  };

  const progressList = () => (
    <>
      {(work.progress?.days.length ?? 0) === 0 && <p className="ws-empty">{t("最近 7 天还没有结果。")}</p>}
      {work.progress?.days.map((day) => (
        <div key={day.date} className="ws-group">
          <div className="ws-group-head">{dayLabel(`${day.date}T12:00:00`)} <span className="muted">{day.items.length}</span></div>
          {day.items.map((item) => (
            <div key={item.id} className="ws-row static">
              <span className="ws-row-title">{item.status === "done" ? "✓" : "–"} {item.title}</span>
              <span className="ws-row-sub">{item.resolution} · {timeOf(item.closed_at)}
                {item.undoable && <> · <button className="link" onClick={() => void undo(item.id)}>{t("撤销")}</button></>}</span>
            </div>
          ))}
        </div>
      ))}
      {(work.progress?.notes.length ?? 0) > 0 && (
        <div className="ws-group">
          <div className="ws-group-head">{t("汇总和简报")}</div>
          {work.progress!.notes.map((note, n) => (
            <details key={n} className="progress-note">
              <summary>{note.kind === "brief" ? t("简报") : t("汇总")} · {relative(note.created_at)}</summary>
              <Markdown remarkPlugins={[remarkGfm]}>{note.text}</Markdown>
            </details>
          ))}
        </div>
      )}
    </>
  );

  const content = () => {
    if (!top) return view === "todo" ? todoList() : view === "mail" ? mailList() : view === "meetings" ? meetingList() : progressList();
    if (top.type === "group") {
      const list = items.filter((i) => approvalGroup(i) === top.name);
      return <div className="ws-group"><div className="ws-group-head">{top.name} <span className="muted">{list.length}</span></div>
        {list.map((i) => <ItemRow key={i.id} item={i} onOpen={() => open({ type: "item", id: i.id })} />)}</div>;
    }
    if (top.type === "item") {
      const item = items.find((i) => i.id === top.id);
      if (!item) return <p className="ws-empty">{t("这件事已经结束了。")}</p>;
      return (
        <div className="detail">
          <ItemCard item={item} onChanged={() => void work.refresh()} onClosed={closed} />
          <footer className="detail-foot">
            <button className="btn primary block" onClick={() => onAsk(itemContext(item))}><Icon name="plus" size={14} /> {t("带着这件事问 Relay")}</button>
          </footer>
        </div>
      );
    }
    if (top.type === "meeting") {
      const meeting = meetings.find((m) => m.id === top.id);
      return meeting ? <MeetingDetail meeting={meeting} all={work.meetings?.upcoming ?? []} work={work} onOpen={open} onAsk={onAsk} />
        : <p className="ws-empty">{t("找不到这个会了（可能已取消）。")}</p>;
    }
    const s = top.source;
    return (
      <div className="detail">
        <div className="detail-badges"><span className="badge">{t(SOURCE[s.kind] ?? s.kind)}</span></div>
        <h2 className="detail-title small">{s.title}</h2>
        <p className="detail-meta">{t("为什么相关")}：{s.why}</p>
        <p className="detail-meta">{t("用于会议《{title}》的会前简报", { title: top.meeting })}</p>
        {safe(s.url) ? <a className="btn secondary small" href={safe(s.url)!} target="_blank" rel="noreferrer"><Icon name="external" size={13} /> {t("在飞书打开原文")}</a>
          : <p className="muted small">{t("这份材料在会议描述或 Relay 的记录里，没有单独的原文链接。")}</p>}
      </div>
    );
  };

  return (
    <aside className="inspector" aria-label={t("详情栏")}>
      <header className="inspector-head">
        {stack.length > 0 && <button className="icon-button" onClick={back} aria-label={t("返回")}><Icon name="back" size={16} /></button>}
        <strong>{title}{!top && view === "todo" && <span className="muted"> {items.length}</span>}</strong>
        <span className="spacer" />
        <button className="icon-button" onClick={onClose} aria-label={t("关闭")}><Icon name="x" size={16} /></button>
      </header>
      <div className="inspector-body" ref={body}>
        {!work.board && !work.error ? <p className="ws-empty">{t("loading")}</p> : content()}
      </div>
      {toast && (
        <div className="inspector-toast" role="status">
          <span>{toast.message}</span>
          <button className="link" onClick={() => void undo(toast.item.id)}>{t("撤销")}</button>
        </div>
      )}
    </aside>
  );
}
