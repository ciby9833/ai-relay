import { t } from "../../i18n";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type Memory, type Settings, type SourceStatus, type Task } from "../../api";
import { dayLabel, relative, timeOf } from "../../format";
import Icon from "../Icon";
import type { PanelKind } from "../Sidebar";
import LanguageSelect from "../LanguageSelect";
import Automations from "./Automations";
import Integrations from "./Integrations";

function Shell({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const element = dialog.current!;
    element.showModal();
    return () => { element.close(); previous?.focus(); };
  }, []);
  return (
      <dialog ref={dialog} className="drawer" aria-labelledby="drawer-title"
        onCancel={(event) => { event.preventDefault(); onClose(); }}
        onKeyDown={(event) => {
          if (event.key !== "Tab") return;
          const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
            'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
          )).filter((element) => element.getClientRects().length > 0);
          const first = controls[0];
          const last = controls[controls.length - 1];
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
        }}
        onClick={(event) => {
          if (event.target !== event.currentTarget) return;
          const bounds = event.currentTarget.getBoundingClientRect();
          if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
        }}>
        <header className="drawer-head">
          <h2 id="drawer-title">{title}</h2>
          <button className="icon-button" onClick={onClose} title={t("关闭")}>
            <Icon name="x" />
          </button>
        </header>
        <div className="drawer-body">{children}</div>
      </dialog>
  );
}

function Memories() {
  const [items, setItems] = useState<Memory[] | null>(null);
  const load = useCallback(() => api.memories().then(setItems), []);
  useEffect(() => void load(), [load]);
  if (!items) return null;
  const groups: [string, Memory[]][] = [
    [t("关于你"), items.filter((m) => m.kind === "profile")],
    [t("发生过的事"), items.filter((m) => m.kind === "episodic")],
  ];
  return (
    <>
      <p className="muted">{t("Relay 记住的这些会用在之后的每次判断和对话里。不对的可以直接删掉。")}</p>
      {items.length === 0 && <p className="empty-note">{t("还没有记忆。聊着聊着就会有了。")}</p>}
      {groups.map(([label, list]) =>
        list.length ? (
          <section key={label}>
            <h3>{label}</h3>
            {list.map((memory) => (
              <div key={memory.id} className="row-card">
                <span>{memory.content}</span>
                <button className="icon-button" title={t("删除")} onClick={() => api.deleteMemory(memory.id).then(load)}>
                  <Icon name="trash" size={14} />
                </button>
              </div>
            ))}
          </section>
        ) : null,
      )}
    </>
  );
}

function Tasks() {
  const [items, setItems] = useState<Task[] | null>(null);
  const load = useCallback(() => api.tasks().then(setItems), []);
  useEffect(() => void load(), [load]);
  if (!items) return null;
  return (
    <>
      <p className="muted">{t("在对话里说“每周一早上 9 点提醒我写周报”就能创建。")}</p>
      {items.length === 0 && <p className="empty-note">{t("还没有定时任务。")}</p>}
      {items.map((task) => (
        <div key={task.id} className="row-card column">
          <div className="row-card-head">
            <strong>{task.title}</strong>
            <button className="icon-button" title={t("删除")} onClick={() => api.deleteTask(task.id).then(load)}>
              <Icon name="trash" size={14} />
            </button>
          </div>
          <span className="muted">
            {task.cron ? t("周期 {p0}", { p0: task.cron }) : t("一次性")}
            {task.next_run_at ? t(" · 下次 {p0} {p1}", { p0: dayLabel(task.next_run_at), p1: timeOf(task.next_run_at) }) : t(" · 已结束")}
          </span>
          <span className="small">{task.prompt}</span>
        </div>
      ))}
    </>
  );
}

const SOURCES: Record<string, string> = {
  mail: "邮件",
  calendar: "日历",
  approval: "审批",
  attendance: "考勤",
  message: "群消息里@我",
};

function SettingsForm() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [status, setStatus] = useState<Record<string, SourceStatus>>({});
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    setError(false);
    void api.settings().then((result) => {
      setSettings(result.settings);
      setStatus(result.sources);
    }).catch(() => setError(true));
  }, []);
  useEffect(load, [load]);
  if (!settings) return <>
    <LanguageSelect hint />
    <p role={error ? "alert" : "status"}>{t(error ? "loadError" : "loading")}</p>
    {error && <button className="btn secondary" onClick={load}>{t("retry")}</button>}
  </>;

  const update = (patch: Partial<Settings>) => {
    setSettings({ ...settings, ...patch });
    setSaved(false);
  };

  return (
    <>
      <label className="toggle">
        <input type="checkbox" checked={settings.proactive} onChange={(e) => update({ proactive: e.target.checked })} />
        <span>
          <strong>{t("主动提醒")}</strong>
          <span className="muted">{t("关闭后 Relay 只在你找它时回应")}</span>
        </span>
      </label>

      <section>
        <h3>{t("留意哪些事")}</h3>
        {Object.entries(SOURCES).map(([key, label]) => (
          <label key={key} className="toggle">
            <input
              type="checkbox"
              checked={settings.sources[key] ?? true}
              onChange={(e) => update({ sources: { ...settings.sources, [key]: e.target.checked } })}
            />
            <span>
              <strong>{t(label)}</strong>
              {status[key]?.error ? (
                <span className="error-text">{status[key].error}</span>
              ) : status[key]?.last_synced_at ? (
                <span className="muted">{t("syncedAt", { time: relative(status[key].last_synced_at) })}</span>
              ) : null}
            </span>
          </label>
        ))}
      </section>

      <section>
        <h3>{t("语言")}</h3>
        <LanguageSelect hint />
        <label className="field">
          <span>{t("Relay 用什么语言和你说话")}</span>
          <select value={settings.language ?? "auto"} onChange={(e) => update({ language: e.target.value as Settings["language"] })}>
            <option value="auto">{t("跟随我的消息自动识别")}</option>
            <option value="zh">{t("简体中文")}</option>
            <option value="en">English</option>
            <option value="id">Bahasa Indonesia</option>
          </select>
        </label>
        <p className="muted small">{t("主动提醒、简报和飞书卡片用这个语言。替你写给别人的邮件和消息，会用对方的语言。")}</p>
      </section>

      <section>
        <h3>{t("节奏")}</h3>
        <label className="field">
          <span>
            <input type="checkbox" checked={settings.brief_enabled} onChange={(e) => update({ brief_enabled: e.target.checked })} /> {t("工作日自动发简报")} </span>
          <input type="time" value={settings.brief_time} disabled={!settings.brief_enabled} onChange={(e) => update({ brief_time: e.target.value })} />
        </label>
        <label className="field">
          <span>{t("免打扰")}</span>
          <span className="field-pair">
            <input type="time" value={settings.quiet_start} onChange={(e) => update({ quiet_start: e.target.value })} />
            {t("至")} <input type="time" value={settings.quiet_end} onChange={(e) => update({ quiet_end: e.target.value })} />
          </span>
        </label>
        <label className="field">
          <span>{t("会前准备提前（分钟）")}</span>
          <input type="number" min={0} max={120} value={settings.meeting_brief_minutes} onChange={(e) => update({ meeting_brief_minutes: Number(e.target.value) })} />
        </label>
        <label className="field">
          <span>{t("每小时最多打扰")}</span>
          <input type="number" min={0} max={60} value={settings.max_interrupts_per_hour} onChange={(e) => update({ max_interrupts_per_hour: Number(e.target.value) })} />
        </label>
        <p className="muted small">{t("新的事会实时告诉你；免打扰时段先记下，结束后再说，紧急的事不受限制。")}</p>
      </section>

      {error && <p role="alert" className="error-text">{t("操作失败")}</p>}
      <button className="btn primary" disabled={saving} onClick={async () => {
        setSaving(true);
        setError(false);
        try { await api.saveSettings(settings); setSaved(true); }
        catch { setError(true); }
        finally { setSaving(false); }
      }}>
        {saving ? t("saving") : saved ? t("已保存") : t("保存")}
      </button>
    </>
  );
}

export default function Drawer({ kind, onClose }: { kind: PanelKind; onClose: () => void }) {
  const titles: Record<PanelKind, string> = {
    memories: t("Relay 记住的事"),
    tasks: t("定时任务"),
    automations: t("自动办的事"),
    settings: t("提醒设置"),
    integrations: t("业务系统接入"),
  };
  return (
    <Shell title={titles[kind]} onClose={onClose}>
      {kind === "memories" && <Memories />}
      {kind === "tasks" && <Tasks />}
      {kind === "automations" && <Automations />}
      {kind === "settings" && <SettingsForm />}
      {kind === "integrations" && <Integrations />}
    </Shell>
  );
}
