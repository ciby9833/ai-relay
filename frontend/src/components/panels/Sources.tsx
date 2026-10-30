import { t } from "../../i18n";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type OwnConnection, type OwnConnections } from "../../api";
import { relative } from "../../format";
import { notificationsOn, setNotifications } from "../../notify";

function Status({ conn }: { conn: OwnConnection }) {
  if (!conn.connected) return <span className="badge">{t("未接入")}</span>;
  if (conn.status === "ok") return <span className="badge ok">{t("已连通")}</span>;
  if (conn.status === "failed") return <span className="badge urgent">{t("连接失败")}</span>;
  return <span className="badge warn">{t("未验证")}</span>;
}

function Mailbox({ conn, onChanged }: { conn: OwnConnection; onChanged: (c: OwnConnection) => void }) {
  const [form, setForm] = useState<Record<string, string>>(() => Object.fromEntries(
    Object.entries(conn.config).map(([k, v]) => [k, v == null ? "" : String(v)])));
  const [password, setPassword] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const set = (key: string) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const fill = async () => {
    if (!form.email?.includes("@") || form.imap_host) return;
    const preset = await api.mailPreset(form.email).catch(() => ({}));
    if (Object.keys(preset).length) setForm((f) => ({ ...f, ...Object.fromEntries(Object.entries(preset).map(([k, v]) => [k, String(v)])) }));
    else setAdvanced(true);  // 不认识的邮箱：要填服务器
  };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const values: Record<string, string | number | null> = { ...form, password: password || null };
      for (const key of ["imap_port", "smtp_port"]) if (form[key]) values[key] = Number(form[key]);
      await api.saveMailbox(values);
      setPassword("");
      const tested = await api.testConnection("imap");
      onChanged(tested);
      if (tested.status === "ok") setNote(tested.note ?? t("已连通"));
      else setError(tested.last_error ?? t("连接失败"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="ws-form" onSubmit={save}>
      <label>{t("邮箱地址")}<input type="email" required value={form.email ?? ""} onChange={set("email")} onBlur={() => void fill()} /></label>
      <label>{t("密码（Gmail、Outlook 等要用“应用专用密码”）")}
        <input type="password" autoComplete="off" value={password} required={!conn.secrets.password}
          placeholder={conn.secrets.password ? t("已填写（留空表示不改）") : ""} onChange={(e) => setPassword(e.target.value)} /></label>
      {(advanced || form.imap_host) && (
        <details open={advanced} className="ws-advanced">
          <summary>{t("服务器设置")}{form.imap_host ? `：${form.imap_host}` : ""}</summary>
          <label>{t("收信服务器（IMAP）")}<input value={form.imap_host ?? ""} onChange={set("imap_host")} placeholder="imap.example.com" /></label>
          <label>{t("端口")}<input inputMode="numeric" value={form.imap_port ?? ""} onChange={set("imap_port")} placeholder="993" /></label>
          <label>{t("发信服务器（SMTP）")}<input value={form.smtp_host ?? ""} onChange={set("smtp_host")} placeholder="smtp.example.com" /></label>
          <label>{t("端口")}<input inputMode="numeric" value={form.smtp_port ?? ""} onChange={set("smtp_port")} placeholder="465" /></label>
          <label>{t("登录名（通常就是邮箱地址）")}<input value={form.username ?? ""} onChange={set("username")} /></label>
          <label>{t("“已发送”文件夹（找不到时才需要填）")}<input value={form.sent_folder ?? ""} onChange={set("sent_folder")} /></label>
        </details>
      )}
      {error && <p role="alert" className="error-text">{error}</p>}
      {note && <p className="muted small">{note}</p>}
      <span className="ws-inline">
        <button className="btn primary small" disabled={busy}>{busy ? t("正在连接…") : conn.connected ? t("保存并测试") : t("接入")}</button>
        {conn.connected && <button type="button" className="btn ghost small" disabled={busy}
          onClick={async () => { if (window.confirm(t("断开这个邮箱？已经读进来的邮件和事项会保留。"))) onChanged(await api.disconnect("imap")); }}>{t("断开")}</button>}
      </span>
    </form>
  );
}

function Calendar({ conn, onChanged }: { conn: OwnConnection; onChanged: (c: OwnConnection) => void }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      if (url) await api.saveCalendar({ url });
      setUrl("");
      const tested = await api.testConnection("ics");
      onChanged(tested);
      if (tested.status === "ok") setNote(tested.note ?? t("已连通"));
      else setError(tested.last_error ?? t("连接失败"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="ws-form" onSubmit={save}>
      <label>{t("日历订阅链接（ICS）")}
        <input type="url" autoComplete="off" value={url} required={!conn.connected} onChange={(e) => setUrl(e.target.value)}
          placeholder={conn.connected ? t("已填写（留空表示不改）") : "https://calendar.google.com/calendar/ical/…/basic.ics"} /></label>
      <p className="muted small">{t("Google 日历：设置 → 你的日历 → “iCal 格式的私密地址”；Outlook：设置 → 日历 → 共享日历 → 发布日历 → ICS 链接。只读：Relay 用它做会前准备和简报，不会改你的日历。")}</p>
      {error && <p role="alert" className="error-text">{error}</p>}
      {note && <p className="muted small">{note}</p>}
      <span className="ws-inline">
        <button className="btn primary small" disabled={busy}>{busy ? t("正在连接…") : conn.connected ? t("保存并测试") : t("接入")}</button>
        {conn.connected && <button type="button" className="btn ghost small" disabled={busy}
          onClick={async () => { if (window.confirm(t("断开这个日历？"))) onChanged(await api.disconnect("ics")); }}>{t("断开")}</button>}
      </span>
    </form>
  );
}

/** 接入自己的邮箱和日历：不用飞书也能得到同一套助理（读信、跟进、代拟回复、会前准备、简报）。 */
export default function Sources({ onLoaded }: { onLoaded?: (data: OwnConnections) => void }) {
  const [data, setData] = useState<OwnConnections | null>(null);
  const [notify, setNotify] = useState(notificationsOn());
  const load = useCallback(() => api.ownConnections().then((d) => { setData(d); onLoaded?.(d); }).catch(() => undefined), [onLoaded]);
  useEffect(() => void load(), [load]);
  if (!data) return null;
  const update = (provider: "imap" | "ics") => (conn: OwnConnection) => { const next = { ...data, [provider]: conn }; setData(next); onLoaded?.(next); };
  return (
    <section>
      <h3>{t("邮箱和日历")}</h3>
      <p className="muted small">{data.feishu.linked
        ? t("你在用飞书的邮箱和日历。如果你的工作邮箱不是飞书邮箱，可以在这里接入，Relay 就读这个邮箱。")
        : t("接入你自己的工作邮箱和日历，Relay 就能替你读信、跟进要你处理的事、代拟回复、做会前准备和简报。")}</p>
      <div className="row-card column">
        <div className="row-card-head"><strong>{t("邮箱")}</strong><Status conn={data.imap} /></div>
        {data.imap.verified_at && data.imap.status === "ok" && <span className="muted small">{t("最近验证 {time}", { time: relative(data.imap.verified_at) })}</span>}
        {data.imap.status === "failed" && data.imap.last_error && <span className="error-text small">{data.imap.last_error}</span>}
        <Mailbox conn={data.imap} onChanged={update("imap")} />
      </div>
      <div className="row-card column">
        <div className="row-card-head"><strong>{t("日历")}</strong><Status conn={data.ics} /></div>
        {data.ics.status === "failed" && data.ics.last_error && <span className="error-text small">{data.ics.last_error}</span>}
        <Calendar conn={data.ics} onChanged={update("ics")} />
      </div>
      <label className="toggle">
        <input type="checkbox" checked={notify} onChange={async (e) => setNotify(await setNotifications(e.target.checked))} />
        <span>
          <strong>{t("浏览器通知")}</strong>
          <span className="muted">{typeof Notification === "undefined"
            ? t("这个浏览器不支持通知")
            : t("Relay 有需要你马上知道的事时，在浏览器里弹出通知（打开着 Relay 的标签页时）。")}</span>
        </span>
      </label>
    </section>
  );
}
