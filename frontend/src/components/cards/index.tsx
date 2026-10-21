import { localize, t } from "../../i18n";
import { useEffect, useRef, useState } from "react";
import { api, type Action, type Card, type FollowUp, type MissionData } from "../../api";
import { dayLabel, timeOf, monthOf, listOf } from "../../format";
import Icon, { RelayMark } from "../Icon";
import AppCard, { Badge } from "./AppCard";
import Materials from "./Materials";

type Props<K extends Card["kind"]> = { card: Extract<Card, { kind: K }>; onChanged: () => void; hasDraft?: boolean };

function useBusy() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (task: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await task();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

function MailCard({ card, onChanged, hasDraft }: Props<"mail">) {
  const { busy, error, run } = useBusy();
  return (
    <AppCard
      icon="mail"
      app={t("邮件")}
      tone={card.importance === "urgent" ? "urgent" : undefined}
      meta={card.time ? `${dayLabel(card.time)} ${timeOf(card.time)}` : undefined}
      footer={
        card.needs_reply && !hasDraft ? (
          <>
            <button className="btn secondary" disabled={busy} onClick={() => run(async () => { await api.draftReply(card.signal_id); onChanged(); })}>
              <Icon name="draft" /> {busy ? t("起草中…") : t("起草回复")}
            </button>
            {error && <span className="card-error">{error}</span>}
          </>
        ) : undefined
      }
    >
      <div className="mail-from">
        <strong>{card.from}</strong>
        {card.importance === "urgent" && <Badge tone="urgent">{t("紧急")}</Badge>}
        {card.needs_reply && <Badge tone="warn">{t("等你回复")}</Badge>}
      </div>
      <div className="mail-subject">{card.subject}</div>
      {card.summary && <p className="card-text">{card.summary}</p>}
    </AppCard>
  );
}

/** 可编辑的邮件草稿：改完点发送；也可以只保存或放弃。 */
function DraftEditor({ action, onChanged }: { action: Action; onChanged: () => void }) {
  const [body, setBody] = useState(action.body ?? "");
  const { busy, error, run } = useBusy();
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => setBody(action.body ?? ""), [action.body]);
  useEffect(() => {
    if (area.current) {
      area.current.style.height = "auto";
      area.current.style.height = `${area.current.scrollHeight}px`;
    }
  }, [body]);

  const pending = action.status === "pending";
  const edited = body !== action.body;
  return (
    <div className="draft">
      <div className="draft-head">
        <span className="muted">{t("收件人")}</span> {action.to}
        {action.reply_all && action.others && action.others.length > 0 && (
          <>
            <br />
            <span className="muted">{t("抄送")}</span> {listOf(action.others)}
          </>
        )}
        {action.subject && (
          <>
            <br />
            <span className="muted">{t("主题")}</span> {action.subject}
          </>
        )}
      </div>
      {pending && action.others && action.others.length > 0 && (
        <label className="toggle compact">
          <input
            type="checkbox"
            checked={!!action.reply_all}
            disabled={busy}
            onChange={(e) => run(async () => { await api.setReplyAll(action.id, e.target.checked); onChanged(); })}
          />
          <span>{t("replyAllCount", { count: action.others.length })}</span>
        </label>
      )}
      {action.references && action.references.length > 0 && (
        <p className="next-step">{t("起草时参考了：")}{listOf(action.references)}</p>
      )}
      {pending ? (
        <textarea ref={area} className="draft-body" aria-label={t("draftBody")} value={body} onChange={(e) => setBody(e.target.value)} rows={4} />
      ) : (
        <div className="draft-body readonly">{action.body}</div>
      )}
      {pending && (
        <div className="inline-actions">
          <button
            className="btn primary"
            disabled={busy}
            onClick={() =>
              run(async () => {
                if (edited) await api.editDraft(action.id, body);
                await api.decide(action.id, "confirm");
                onChanged();
              })
            }
          >
            <Icon name="arrowUp" /> {busy ? t("发送中…") : t("确认发送")}
          </button>
          {edited && (
            <button className="btn secondary" disabled={busy} onClick={() => run(async () => { await api.editDraft(action.id, body); onChanged(); })}>
              {t("保存修改")}
            </button>
          )}
          <button className="btn ghost" disabled={busy} onClick={() => run(async () => { await api.decide(action.id, "cancel"); onChanged(); })}>
            {t("不用了")}
          </button>
        </div>
      )}
      {action.status === "failed" && <div className="card-error">{action.result}</div>}
      {error && <div className="card-error">{error}</div>}
    </div>
  );
}

const ACTION_STATUS: Record<Action["status"], [string, "ok" | "warn" | "urgent" | undefined]> = {
  pending: ["待你确认", "warn"],
  done: ["已发送", "ok"],
  cancelled: ["已取消", undefined],
  failed: ["发送失败", "urgent"],
};

function DraftCard({ card, onChanged }: Props<"draft">) {
  const action = card.action;
  if (!action) return null;
  return (
    <AppCard
      icon="draft"
      app={t("回复草稿")}
      tone={action.status === "done" ? "done" : action.status === "cancelled" ? "muted" : undefined}
      meta={<Badge tone={ACTION_STATUS[action.status][1]}>{t(ACTION_STATUS[action.status][0])}</Badge>}
    >
      <DraftEditor action={action} onChanged={onChanged} />
    </AppCard>
  );
}

const RSVP: Record<string, [string, "ok" | "warn" | "urgent" | undefined]> = {
  accept: ["已接受", "ok"],
  tentative: ["待定", "warn"],
  decline: ["已拒绝", undefined],
  needs_action: ["未回复", "warn"],
};

function EventCard({ card, onChanged }: Props<"event">) {
  const { busy, error, run } = useBusy();
  const start = card.start ? new Date(card.start) : null;
  const action = card.action;
  const awaitingConfirm = action && action.status === "pending";
  const needsReply = card.rsvp === "needs_action" && !awaitingConfirm;
  const rsvp = card.rsvp ? RSVP[card.rsvp] : null;

  const reply = (status: "accept" | "tentative" | "decline") =>
    run(async () => {
      await api.rsvp(card.signal_id, status);
      onChanged();
    });

  return (
    <AppCard
      icon="calendar"
      app={t("日历")}
      meta={rsvp && <Badge tone={rsvp[1]}>{t(rsvp[0])}</Badge>}
      footer={
        needsReply || awaitingConfirm || card.meeting_url || card.app_link ? (
          <>
            {needsReply && (
              <>
                <button className="btn primary" disabled={busy} onClick={() => reply("accept")}>{t("接受")}</button>
                <button className="btn secondary" disabled={busy} onClick={() => reply("tentative")}>{t("待定")}</button>
                <button className="btn ghost" disabled={busy} onClick={() => reply("decline")}>{t("拒绝")}</button>
              </>
            )}
            {awaitingConfirm && (
              <>
                <button className="btn primary" disabled={busy} onClick={() => run(async () => { await api.decide(action.id, "confirm"); onChanged(); })}>
                  {t("确认：")}{action.summary}
                </button>
                <button className="btn ghost" disabled={busy} onClick={() => run(async () => { await api.decide(action.id, "cancel"); onChanged(); })}>
                  {t("取消")}
                </button>
              </>
            )}
            {card.meeting_url && (
              <a className="btn ghost" href={card.meeting_url} target="_blank" rel="noreferrer">
                <Icon name="video" /> {t("加入会议")}
              </a>
            )}
            {card.app_link && !needsReply && (
              <a className="btn ghost" href={card.app_link} target="_blank" rel="noreferrer">
                <Icon name="external" /> {t("在飞书打开")}
              </a>
            )}
            {error && <span className="card-error">{error}</span>}
          </>
        ) : undefined
      }
    >
      <div className="event">
        {start && (
          <div className="event-date">
            <span>{monthOf(card.start)}</span>
            <strong>{start.getDate()}</strong>
          </div>
        )}
        <div className="event-main">
          <div className="event-title">{card.title}</div>
          <div className="muted">
            {card.all_day ? t("全天") : `${card.start ? dayLabel(card.start) : ""} ${timeOf(card.start)}${card.end ? ` – ${timeOf(card.end)}` : ""}`}
            {card.location && (
              <>
                {" · "}
                <Icon name="pin" size={12} /> {card.location}
              </>
            )}
          </div>
          {(card.organizer || card.attendees.length > 0) && (
            <div className="attendees">
              {card.attendees.slice(0, 5).map((name) => (
                <span key={name} className="avatar" title={name}>
                  {name.slice(0, 1)}
                </span>
              ))}
              {card.attendees.length > 5 && <span className="muted">+{card.attendees.length - 5}</span>}
              {card.organizer && <span className="muted">{t("组织者")} {card.organizer}</span>}
            </div>
          )}
          {card.conflicts.length > 0 && (
            <div className="conflict">
              <Icon name="alert" size={13} /> {t("conflictWith", { names: listOf(card.conflicts) })}
            </div>
          )}
        </div>
      </div>
    </AppCard>
  );
}

function ApprovalCard({ card }: Props<"approval">) {
  return (
    <AppCard
      icon="approval"
      app={t("审批")}
      meta={<Badge tone="warn">{t("待你审批")}</Badge>}
      footer={
        card.url ? (
          <a className="btn secondary" href={card.url} target="_blank" rel="noreferrer">
            <Icon name="external" /> {t("去审批")}
          </a>
        ) : undefined
      }
    >
      <div className="card-title">{card.title}</div>
      {card.detail && <p className="card-text">{card.detail}</p>}
    </AppCard>
  );
}

function AlertCard({ card }: Props<"alert">) {
  const app = card.source === "attendance" ? t("考勤") : card.source === "message" ? t("群消息") : t("提醒");
  return (
    <AppCard
      icon={card.source === "attendance" ? "clock" : "bell"}
      app={app}
      tone={card.level === "urgent" ? "urgent" : undefined}
      meta={card.context}
      footer={
        card.url ? (
          <a className="btn secondary" href={card.url} target="_blank" rel="noreferrer">
            <Icon name="external" /> {t("去处理")}
          </a>
        ) : undefined
      }
    >
      <div className="card-title">{card.title}</div>
      {card.detail && <p className="card-text">{card.detail}</p>}
    </AppCard>
  );
}

function DocCard({ card }: Props<"doc">) {
  return (
    <AppCard icon="doc" app={t("飞书文档")} meta={card.updated ? String(card.updated).slice(0, 10) : undefined}>
      {card.url ? (
        <a className="card-title link" href={card.url} target="_blank" rel="noreferrer">
          {card.title} <Icon name="external" size={12} />
        </a>
      ) : (
        <div className="card-title">{card.title}</div>
      )}
      {card.summary && <p className="card-text">{card.summary}</p>}
    </AppCard>
  );
}

const ITEM_KIND: Record<FollowUp["kind"], [string, string]> = {
  reply: ["mail", "等你回复"],
  review: ["doc", "等你处理"],
  invitation: ["calendar", "会议邀请"],
  approval: ["approval", "等你审批"],
  attendance: ["clock", "考勤"],
  mention: ["bell", "群里@你"],
  request: ["bell", "有人找你办事"],
  biz: ["external", "业务系统"],
  waiting: ["clock", "等对方回复"],
  task: ["check", "飞书任务"],
};

const RSVP_LABEL: Record<string, string> = { accept: "接受", tentative: "待定", decline: "拒绝" };

function dueText(value: string | null) {
  if (!value) return null;
  const date = new Date(value);
  const overdue = date.getTime() < Date.now();
  return { text: t(overdue ? "overdueAt" : "dueAt", { date: `${dayLabel(value)} ${timeOf(value)}` }), overdue };
}

export function ItemCard({ item, onChanged, compact }: { item: FollowUp; onChanged: () => void; compact?: boolean }) {
  const { busy, error, run } = useBusy();
  const [icon, label] = ITEM_KIND[item.kind];
  const action = item.action;
  const closed = item.status !== "open";
  const due = dueText(item.due_at);
  const sourceSignal = item.source && "signal_id" in item.source ? item.source.signal_id : null;

  if (closed) {
    return (
      <div className="item-closed">
        <Icon name="check" size={14} /> <s>{item.title}</s> <span className="muted">· {item.resolution}</span>
      </div>
    );
  }

  return (
    <AppCard
      icon={icon}
      app={t(label)}
      tone={item.importance === "urgent" ? "urgent" : undefined}
      meta={
        <>
          {item.importance === "urgent" && <Badge tone="urgent">{t("紧急")}</Badge>}
          {due && <Badge tone={due.overdue ? "urgent" : "warn"}>{due.text}</Badge>}
        </>
      }
      footer={
        <>
          {item.kind === "approval" && !item.quick_approve && item.url && (
            <a className="btn primary" href={item.open_url ?? item.url} target="_blank" rel="noreferrer">
              <Icon name="external" /> {t("去飞书审批")}
            </a>
          )}
          {item.kind === "approval" && item.quick_approve && (
            <>
              <button className="btn primary" disabled={busy} onClick={() => run(async () => { await api.decideApproval(item.id, true); onChanged(); })}>
                <Icon name="check" /> {t("批准")}
              </button>
              <button
                className="btn danger"
                disabled={busy}
                onClick={() => window.confirm(t("驳回「{p0}」？", { p0: item.title })) && run(async () => { await api.decideApproval(item.id, false); onChanged(); })}
              >
                {t("驳回")}
              </button>
            </>
          )}
          {action?.kind === "calendar_rsvp" && action.status === "pending" && (
            <>
              <button className="btn primary" disabled={busy} onClick={() => run(async () => { await api.decide(action.id, "confirm"); onChanged(); })}>
                {t("recommendedAction", { action: t(RSVP_LABEL[action.rsvp ?? "accept"]) })}
              </button>
              {sourceSignal &&
                Object.entries(RSVP_LABEL)
                  .filter(([status]) => status !== action.rsvp)
                  .map(([status, text]) => (
                    <button
                      key={status}
                      className="btn secondary"
                      disabled={busy}
                      onClick={() => run(async () => { await api.rsvp(sourceSignal, status as "accept"); await api.closeItem(item.id, "done"); onChanged(); })}
                    >
                      {t(text)}
                    </button>
                  ))}
            </>
          )}
          {item.url && !(item.kind === "approval" && !item.quick_approve) && (
            <a className="btn ghost" href={item.open_url ?? item.url} target="_blank" rel="noreferrer">
              <Icon name="external" /> {t("在飞书查看")}
            </a>
          )}
          {item.quieter && (
            <button
              className="btn ghost small"
              disabled={busy}
              title={t("以后这一类（同一种审批 / 同一个发件人 / 同一个群）只放进早上的简报，可在提醒设置里改")}
              onClick={() => run(async () => { await api.quieter(item.id, "brief"); onChanged(); })}
            >
              <Icon name="bell" size={14} /> {t("少提醒这类")}
            </button>
          )}
          <span className="spacer" />
          <button className="btn ghost small" disabled={busy} onClick={() => run(async () => { await api.closeItem(item.id, "done"); onChanged(); })}>
            <Icon name="check" size={14} /> {t("我已处理")}
          </button>
          <button className="btn ghost small" disabled={busy} onClick={() => run(async () => { await api.closeItem(item.id, "dismiss"); onChanged(); })}>
            {t("不用跟了")}
          </button>
          {error && <span className="card-error">{error}</span>}
        </>
      }
    >
      <div className="card-title">
        {item.title}
        {item.count > 1 && <span className="muted"> · {t("mailCount", { count: item.count })}</span>}
      </div>
      <p className={`ask ${item.owner === "others" ? "others" : ""}`}>
        {item.owner === "others" ? "⏳ " : t("→ 需要你：")}
        {localize(item.ask_ui, item.ask)}
      </p>
      {item.summary && <p className="card-text">{item.summary}</p>}
      {item.detail.length > 0 && (
        <details className="detail-fields" open={!compact || item.detail.length <= 5}>
          <summary>{t("申请内容")}</summary>
          <dl>
            {item.detail.map((field) => (
              <div key={field.name}>
                <dt>{field.name}</dt>
                <dd>{field.value}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      {item.recommendation && (
        <p className="recommendation">
          <RelayMark size={12} /> {item.recommendation}
        </p>
      )}

      {attentionHint(item) && <p className="muted small attention-hint">{attentionHint(item)}</p>}
      {!compact && <Materials itemId={item.id} />}

      {!compact && action?.kind === "send_mail" && <DraftEditor action={action} onChanged={onChanged} />}
      {compact && action?.kind === "send_mail" && action.status === "pending" && (
        <p className="next-step">{t("Relay 已起草回复，展开确认")}</p>
      )}
    </AppCard>
  );
}

/** 这件事为什么还没（或不会）主动告诉他。 */
function attentionHint(item: FollowUp): string | null {
  if (item.status !== "open") return null;
  if (item.attention === "mute") return t("按你的设置，这类不提醒，只在这里跟踪");
  if (item.announced) return null;
  if (item.attention === "brief") return t("按你的设置，这类放进早上的简报再告诉你");
  if (item.attention === "batch") return t("不急，Relay 会在下次汇总时告诉你");
  return null;
}

const ACTION_ICON: Record<Action["kind"], string> = {
  send_mail: "mail",
  calendar_rsvp: "calendar",
  approval_decision: "approval",
  cloud_write: "doc",
  send_chat: "bell",
  create_task: "check",
  create_event: "calendar",
  update_event: "calendar",
  delete_event: "calendar",
  add_attendees: "calendar",
  base_record: "doc",
};

/** 待确认的操作：说清楚要做什么、对谁，确认后才执行。 */
export function ActionCard({ action, onChanged }: { action: Action; onChanged: () => void }) {
  const { busy, error, run } = useBusy();
  if (action.kind === "send_mail") {
    return (
      <AppCard icon="draft" app={t("邮件草稿")} meta={<Badge tone={ACTION_STATUS[action.status][1]}>{t(ACTION_STATUS[action.status][0])}</Badge>}>
        <DraftEditor action={action} onChanged={onChanged} />
      </AppCard>
    );
  }
  const pending = action.status === "pending";
  const labels: Record<Action["status"], [string, "ok" | "warn" | "urgent" | undefined]> = {
    pending: [t("待你确认"), "warn"],
    done: [t("已执行"), "ok"],
    cancelled: [t("已取消"), undefined],
    failed: [t("失败"), "urgent"],
  };
  return (
    <AppCard
      icon={ACTION_ICON[action.kind] ?? "check"}
      app={t("待确认操作")}
      tone={action.status === "done" ? "done" : action.status === "cancelled" ? "muted" : undefined}
      meta={<Badge tone={labels[action.status][1]}>{labels[action.status][0]}</Badge>}
      footer={
        pending ? (
          <>
            <button className="btn primary" disabled={busy} onClick={() => run(async () => { await api.decide(action.id, "confirm"); onChanged(); })}>
              <Icon name="check" /> {t("确认执行")}
            </button>
            {action.grantable && (
              <button
                className="btn ghost"
                disabled={busy}
                title={t("只授权这个定时任务、同一个对象；在“自动办的事”里可以随时收回")}
                onClick={() => run(async () => { await api.decide(action.id, "grant"); onChanged(); })}
              >
                {t("确认，以后直接办")}
              </button>
            )}
            <button className="btn ghost" disabled={busy} onClick={() => run(async () => { await api.decide(action.id, "cancel"); onChanged(); })}>
              {t("不用了")}
            </button>
            {error && <span className="card-error">{error}</span>}
          </>
        ) : action.undoable ? (
          <>
            <button
              className="btn ghost"
              disabled={busy}
              onClick={() => window.confirm(t("撤销「{p0}」？", { p0: action.summary })) && run(async () => { await api.decide(action.id, "undo"); onChanged(); })}
            >
              {t("撤销")}
            </button>
            {error && <span className="card-error">{error}</span>}
          </>
        ) : action.link ? (
          <a className="btn ghost" href={action.link} target="_blank" rel="noreferrer">
            <Icon name="external" /> {t("在飞书查看")}
          </a>
        ) : undefined
      }
    >
      <div className="card-title">
        {action.auto && <span className="auto-tag">{t("自动办理")}</span>}
        {action.summary}
        {action.undone_at && <span className="muted"> · {t("已撤销")}</span>}
      </div>
      {action.to && <p className="next-step">{t("对象：")}{action.to}</p>}
      {action.shown && (
        <div className="detail-fields">
          <dl>
            {Object.entries(action.shown).map(([name, value]) => (
              <div key={name}>
                <dt>{name}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      {action.start && <p className="next-step">{t("时间：")}{dayLabel(action.start)} {timeOf(action.start)}</p>}
      {action.due && <p className="next-step">{t("截止：")}{dayLabel(action.due)} {timeOf(action.due)}</p>}
      {action.cells ? (
        <div className="cell-table-wrap">
          <table className="cell-table">
            <thead><tr><th>{t("单元格")}</th><th>{t("原值")}</th><th>{t("新值")}</th></tr></thead>
            <tbody>
              {action.cells.map((c) => (
                <tr key={c.cell}>
                  <td className="cell-ref">{c.cell}</td>
                  <td className={c.before.trim() ? "cell-old overwritten" : "cell-old"}>{c.before.trim() || t("（空）")}</td>
                  <td>{String(c.after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {action.notes && action.notes.length > 0 && <p className="next-step">{t("注意：")}{listOf(action.notes)}</p>}
        </div>
      ) : action.body && <div className="draft-body readonly">{action.body}</div>}
      {action.kind === "cloud_write" && action.status === "done" && action.result && <div className="draft-body readonly">{action.result}</div>}
      {action.status === "failed" && action.result && <p className="card-error">{action.result}</p>}
    </AppCard>
  );
}

const MISSION_STATUS: Record<MissionData["status"], [string, "ok" | "warn" | "urgent" | undefined]> = {
  active: ["推进中", "ok"],
  waiting: ["在等对方", undefined],
  asking: ["在等你回答", "warn"],
  done: ["已完成", "ok"],
  failed: ["没办成", "urgent"],
  cancelled: ["已取消", undefined],
};

export function MissionCard({ mission, onChanged, onOpen }: { mission: MissionData; onChanged: () => void; onOpen?: (id: number) => void }) {
  const [answer, setAnswer] = useState("");
  const { busy, error, run } = useBusy();
  const done = mission.plan.filter((s) => s.status === "done").length;
  const [label, tone] = MISSION_STATUS[mission.status];
  return (
    <AppCard
      icon="clock"
      app={t("长期任务")}
      meta={<Badge tone={tone}>{t(label)}</Badge>}
      footer={
        onOpen ? (
          <button className="btn ghost small" onClick={() => onOpen(mission.id)}>
            {t("查看进展")} <Icon name="chevron" size={12} />
          </button>
        ) : undefined
      }
    >
      <div className="card-title">{mission.title}</div>
      {mission.plan.length > 0 && (
        <div className="progress">
          <div className="progress-bar" style={{ width: `${(done / mission.plan.length) * 100}%` }} />
          <span className="muted small">
            {t("stepCount", { done, total: mission.plan.length })}
            {mission.waiting_for ? t(" · 在等{p0}", { p0: mission.waiting_for }) : ""}
          </span>
        </div>
      )}
      {mission.result && <p className="card-text">{mission.result}</p>}
      {mission.status === "asking" && mission.question && (
        <div className="mission-question">
          <p className="ask">{t("→ 需要你回答：")}{mission.question}</p>
          <div className="inline-actions">
            <input value={answer} aria-label={t("你的回答")} placeholder={t("你的回答")} onChange={(e) => setAnswer(e.target.value)} />
            <button className="btn primary" disabled={busy || !answer.trim()} onClick={() => run(async () => { await api.answerMission(mission.id, answer); setAnswer(""); onChanged(); })}>
              {t("回复")}
            </button>
          </div>
          {error && <span className="card-error">{error}</span>}
        </div>
      )}
      {mission.pending_actions.length > 0 && (
        <p className="ask">{t("pendingActions", { count: mission.pending_actions.length })}</p>
      )}
    </AppCard>
  );
}

export default function InlineCard({ card, onChanged, hasDraft }: { card: Card; onChanged: () => void; hasDraft?: boolean }) {
  switch (card.kind) {
    case "mail":
      return <MailCard card={card} onChanged={onChanged} hasDraft={hasDraft} />;
    case "draft":
      return <DraftCard card={card} onChanged={onChanged} />;
    case "event":
      return <EventCard card={card} onChanged={onChanged} />;
    case "approval":
      return <ApprovalCard card={card} onChanged={onChanged} />;
    case "alert":
      return <AlertCard card={card} onChanged={onChanged} />;
    case "doc":
      return <DocCard card={card} onChanged={onChanged} />;
    case "item":
      return card.item ? <ItemCard item={card.item} onChanged={onChanged} /> : null;
    case "mission":
      return card.mission ? <MissionCard mission={card.mission} onChanged={onChanged} onOpen={(id) => window.dispatchEvent(new CustomEvent("relay:open-mission", { detail: id }))} /> : null;
    case "action":
      return card.action ? <ActionCard action={card.action} onChanged={onChanged} /> : null;
  }
}
