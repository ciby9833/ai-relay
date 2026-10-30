import { t } from "../../i18n";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type CollabAction, type CollabMaterial, type Delegation } from "../../api";
import { dayLabel, relative, timeOf } from "../../format";
import Icon from "../Icon";

const ACTION_LABEL: Record<CollabAction, string> = {
  accept: "接受", decline: "拒绝", counter: "提出修改", submit: "提交结果",
  agree: "同意修改", revise: "修改要求", approve: "验收通过", return: "退回修改", cancel: "取消请求",
};
const NEEDS_NOTE: Partial<Record<CollabAction, string>> = {
  decline: "拒绝的理由", counter: "为什么要改、想怎么改", submit: "交付了什么", return: "哪里需要改",
};
const PRIMARY: CollabAction[] = ["accept", "submit", "agree", "approve"];
const LOG_LABEL: Record<string, string> = { request: "发出请求", ...ACTION_LABEL };
const STATUS_TONE: Record<Delegation["status"], string> = {
  requested: "warn", countered: "warn", accepted: "", submitted: "warn", returned: "warn", completed: "ok", declined: "", cancelled: "",
};

/** 每行一份材料：带 https 链接的当链接，否则当一段内容。只有写在这里的才会给对方看。 */
function parseMaterials(text: string): CollabMaterial[] {
  return text.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const url = line.match(/https:\/\/\S+/)?.[0];
    if (url) return { title: line.replace(url, "").trim() || url, url };
    return { title: line.slice(0, 30), text: line };
  });
}

function when(iso: string | null) {
  return iso ? `${dayLabel(iso)} ${timeOf(iso)}` : t("未约定");
}

function Materials({ items }: { items: CollabMaterial[] }) {
  if (!items.length) return null;
  return (
    <ul className="collab-materials">
      {items.map((m, n) => (
        <li key={n}>
          <Icon name="doc" size={13} />{" "}
          {m.url ? <a href={m.url} target="_blank" rel="noreferrer">{m.title}</a> : <b>{m.title}</b>}
          {m.text && m.text !== m.title && <span className="muted small"> {m.text}</span>}
        </li>
      ))}
    </ul>
  );
}

function myTurn(d: Delegation) {
  return d.actions.some((a) => PRIMARY.includes(a) || a === "counter");
}

function Detail({ id, onBack, onChanged }: { id: number; onBack: () => void; onChanged: () => void }) {
  const [d, setD] = useState<Delegation | null>(null);
  const [pending, setPending] = useState<CollabAction | null>(null);
  const [note, setNote] = useState("");
  const [changes, setChanges] = useState<Record<string, string>>({});
  const [materials, setMaterials] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api.delegation(id).then(setD).catch((e) => setError(e instanceof Error ? e.message : t("操作失败"))), [id]);
  useEffect(() => void load(), [load]);
  if (!d) return error ? <p role="alert" className="error-text">{error}</p> : <p className="muted">{t("loading")}</p>;

  const other = d.role === "requester" ? d.assignee.name : d.requester.name;
  const run = async (action: CollabAction) => {
    setBusy(true);
    setError(null);
    try {
      const body: Parameters<typeof api.actDelegation>[1] = { action, version: d.version };
      if (note.trim()) body.note = note.trim();
      if (action === "counter" || action === "revise") {
        const picked = Object.fromEntries(Object.entries(changes).filter(([, v]) => v.trim()));
        if (picked.due_at) picked.due_at = new Date(picked.due_at).toISOString();
        body.changes = picked;
      }
      if (action === "submit" || action === "revise") {
        const list = parseMaterials(materials);
        if (list.length || action === "submit") body.materials = list;
      }
      setD(await api.actDelegation(d.id, body));
      setPending(null);
      setNote("");
      setChanges({});
      setMaterials("");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
      void load();  // 可能对方刚改过：显示最新状态
    } finally {
      setBusy(false);
    }
  };
  // 不需要填写的直接执行；需要说明 / 修改的先展开表单
  const start = (action: CollabAction) => {
    if (action === "cancel" && !window.confirm(t("取消这个请求？对方会收到通知。"))) return;
    if (NEEDS_NOTE[action] || action === "revise") setPending(action);
    else void run(action);
  };

  return (
    <div className="collab-detail">
      <button className="link small" onClick={onBack}>← {t("返回列表")}</button>
      <div className="detail-badges">
        <span className={`badge ${STATUS_TONE[d.status]}`}>{t(d.status_text)}</span>
        <span className="badge">{d.role === "requester" ? t("你请 {name}", { name: other }) : t("{name} 请你", { name: other })}</span>
      </div>
      <h3 className="detail-title">{d.title}</h3>
      <dl className="collab-fields">
        <dt>{t("要做什么")}</dt><dd className="pre">{d.brief}</dd>
        <dt>{t("交付")}</dt><dd>{d.deliverable}</dd>
        <dt>{t("怎样算完成")}</dt><dd>{d.acceptance || <span className="muted">{t("没写")}</span>}</dd>
        <dt>{t("期限")}</dt><dd>{when(d.due_at)}</dd>
      </dl>
      {d.materials.length > 0 && <div><h4>{t("共享的材料")}</h4><Materials items={d.materials} /></div>}
      {d.status === "countered" && d.proposal && (
        <div className="collab-box">
          <b>{t("{name} 提出修改", { name: d.assignee.name })}</b>
          {d.proposal.note && <p className="pre">{d.proposal.note}</p>}
          {d.proposal.deliverable && <p>{t("交付")}：{d.proposal.deliverable}</p>}
          {d.proposal.acceptance && <p>{t("怎样算完成")}：{d.proposal.acceptance}</p>}
          {d.proposal.due_at && <p>{t("期限")}：{when(d.proposal.due_at)}</p>}
        </div>
      )}
      {d.submission && (
        <div className="collab-box">
          <b>{t("{name} 提交的结果", { name: d.assignee.name })}</b> <span className="muted small">{relative(d.submission.at)}</span>
          <p className="pre">{d.submission.note}</p>
          <Materials items={d.submission.materials} />
        </div>
      )}

      {pending ? (
        <form className="ws-form collab-form" onSubmit={(e: FormEvent) => { e.preventDefault(); void run(pending); }}>
          <b>{t(ACTION_LABEL[pending])}</b>
          {(pending === "counter" || pending === "revise") && (
            <>
              {pending === "revise" && <label>{t("要做什么")}<textarea rows={3} defaultValue={d.brief} onChange={(e) => setChanges({ ...changes, brief: e.target.value })} /></label>}
              <label>{t("交付")}<input defaultValue={d.deliverable} onChange={(e) => setChanges({ ...changes, deliverable: e.target.value })} /></label>
              <label>{t("怎样算完成")}<input defaultValue={d.acceptance ?? ""} onChange={(e) => setChanges({ ...changes, acceptance: e.target.value })} /></label>
              <label>{t("期限（可不填）")}<input type="datetime-local" onChange={(e) => setChanges({ ...changes, due_at: e.target.value })} /></label>
            </>
          )}
          {NEEDS_NOTE[pending] && (
            <label>{t(NEEDS_NOTE[pending]!)}<textarea required rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></label>
          )}
          {(pending === "submit" || pending === "revise") && (
            <label>{t("材料（每行一份：标题 + https 链接，或直接贴内容）")}
              <textarea rows={2} value={materials} onChange={(e) => setMaterials(e.target.value)} /></label>
          )}
          <span className="ws-inline">
            <button className="btn primary small" disabled={busy}>{t("确定")}</button>
            <button type="button" className="btn ghost small" onClick={() => setPending(null)}>{t("返回")}</button>
          </span>
        </form>
      ) : d.actions.length > 0 ? (
        <div className="collab-actions">
          {d.actions.map((a) => (
            <button key={a} className={`btn ${PRIMARY.includes(a) ? "primary" : a === "cancel" || a === "decline" ? "ghost" : "secondary"} small`}
              disabled={busy} onClick={() => start(a)}>{t(ACTION_LABEL[a])}</button>
          ))}
        </div>
      ) : (
        <p className="muted small">{["completed", "declined", "cancelled"].includes(d.status) ? t("这份协作已经结束。") : t("等 {name} 处理。", { name: other })}</p>
      )}
      {error && <p role="alert" className="error-text">{error}</p>}

      {d.log && d.log.length > 0 && (
        <details className="collab-log">
          <summary>{t("变更记录（{count}）", { count: d.log.length })}</summary>
          <ol>
            {d.log.map((e, n) => (
              <li key={n}><span className="muted small">{e.at ? relative(e.at) : ""}</span> {e.who} · {t(LOG_LABEL[e.kind] ?? e.kind)}
                {e.note && <span className="muted">：{e.note}</span>}</li>
            ))}
          </ol>
        </details>
      )}
      <p className="muted small">{t("对方只能看到这里写明的内容和共享的材料，看不到你的对话和记忆。")}</p>
    </div>
  );
}

function NewRequest({ onDone, onBack }: { onDone: (id: number) => void; onBack: () => void }) {
  const [people, setPeople] = useState<{ id: string; name: string; email: string | null }[] | null>(null);
  const [form, setForm] = useState({ assignee_id: "", title: "", brief: "", deliverable: "", acceptance: "", due_at: "", materials: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => void api.colleagues().then(setPeople).catch(() => setPeople([])), []);
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const d = await api.createDelegation({
        assignee_id: form.assignee_id, title: form.title, brief: form.brief, deliverable: form.deliverable,
        acceptance: form.acceptance || null, due_at: form.due_at ? new Date(form.due_at).toISOString() : null,
        materials: parseMaterials(form.materials),
      });
      onDone(d.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    } finally {
      setBusy(false);
    }
  };
  if (people && !people.length) {
    return <><button className="link small" onClick={onBack}>← {t("返回列表")}</button>
      <p className="empty-note">{t("这个工作区里还没有别的成员。可以请管理员在“工作区设置”里邀请同事。")}</p></>;
  }
  return (
    <form className="ws-form collab-form" onSubmit={submit}>
      <button type="button" className="link small" onClick={onBack}>← {t("返回列表")}</button>
      <label>{t("请谁")}
        <select required value={form.assignee_id} onChange={set("assignee_id")}>
          <option value="">{t("选择同事")}</option>
          {(people ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}{p.email ? ` · ${p.email}` : ""}</option>)}
        </select>
      </label>
      <label>{t("标题")}<input required maxLength={200} value={form.title} onChange={set("title")} /></label>
      <label>{t("要做什么（背景、为什么）")}<textarea required rows={4} value={form.brief} onChange={set("brief")} /></label>
      <label>{t("交付什么")}<input required value={form.deliverable} onChange={set("deliverable")} /></label>
      <label>{t("怎样算完成（可不填）")}<input value={form.acceptance} onChange={set("acceptance")} /></label>
      <label>{t("期限（可不填，没约定就不填）")}<input type="datetime-local" value={form.due_at} onChange={set("due_at")} /></label>
      <label>{t("共享给对方的材料（每行一份：标题 + https 链接，或直接贴内容）")}<textarea rows={2} value={form.materials} onChange={set("materials")} /></label>
      <p className="muted small">{t("对方会在“待处理”里收到，由本人决定接受、拒绝或提出修改。只有这里写的内容会给对方看。")}</p>
      {error && <p role="alert" className="error-text">{error}</p>}
      <button className="btn primary" disabled={busy}>{t("发出请求")}</button>
    </form>
  );
}

/** 和同事的协作：请同事做事、回应别人的请求、提交和验收。 */
export default function Collab({ openId, onChanged }: { openId?: number | null; onChanged?: () => void }) {
  const [view, setView] = useState<"list" | "new" | number>(openId ?? "list");
  const [items, setItems] = useState<Delegation[] | null>(null);
  const [closed, setClosed] = useState<Delegation[] | null>(null);
  const [error, setError] = useState(false);
  const load = useCallback(() => {
    onChanged?.();  // “待处理”里的协作事项跟着变
    return api.delegations().then(setItems).catch(() => setError(true));
  }, [onChanged]);
  useEffect(() => void api.delegations().then(setItems).catch(() => setError(true)), []);

  if (view === "new") return <NewRequest onBack={() => setView("list")} onDone={(id) => { void load(); setView(id); }} />;
  if (typeof view === "number") return <Detail id={view} onBack={() => { setView("list"); void load(); }} onChanged={() => void load()} />;

  const mine = (items ?? []).filter(myTurn);
  const waiting = (items ?? []).filter((d) => !myTurn(d));
  const Row = ({ d }: { d: Delegation }) => {
    const other = d.role === "requester" ? d.assignee.name : d.requester.name;
    return (
      <button className="item-row" onClick={() => setView(d.id)}>
        <span className="item-row-main">
          <span className="ws-row-title">{d.title}</span>
          <span className="ws-row-sub">
            <span className="row-tag">{d.role === "requester" ? t("你请 {name}", { name: other }) : t("{name} 请你", { name: other })}</span>
            {t(d.status_text)}{d.due_at ? ` · ${when(d.due_at)}` : ""}
          </span>
        </span>
        <Icon name="chevron" size={14} />
      </button>
    );
  };
  return (
    <>
      <p className="muted">{t("请同一个工作区的同事做事，对方接受后完成并提交，你来验收。也可以在对话里说“请 Budi 周五前把报价单整理好”。")}</p>
      <button className="btn primary" onClick={() => setView("new")}>+ {t("请同事帮忙")}</button>
      {error && <p role="alert" className="error-text">{t("操作失败")}</p>}
      {items && (
        <>
          <section><h3>{t("轮到你（{count}）", { count: mine.length })}</h3>
            {mine.length ? mine.map((d) => <Row key={d.id} d={d} />) : <p className="empty-note">{t("没有要你处理的协作。")}</p>}</section>
          <section><h3>{t("在等对方（{count}）", { count: waiting.length })}</h3>
            {waiting.length ? waiting.map((d) => <Row key={d.id} d={d} />) : <p className="empty-note">{t("没有在等对方的协作。")}</p>}</section>
          <section>
            {closed ? (
              <><h3>{t("已结束")}</h3>
                {closed.filter((d) => ["completed", "declined", "cancelled"].includes(d.status)).map((d) => <Row key={d.id} d={d} />)}</>
            ) : (
              <button className="link small" onClick={() => void api.delegations(true).then(setClosed)}>{t("看已结束的")}</button>
            )}
          </section>
        </>
      )}
    </>
  );
}
