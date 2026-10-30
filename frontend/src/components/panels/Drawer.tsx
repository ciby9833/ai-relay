import { t } from "../../i18n";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type AttentionLevel, type Memory, type NotifyRule, type Settings, type SourceStatus, type Task } from "../../api";
import { dayLabel, relative, timeOf } from "../../format";
import Icon from "../Icon";
import type { PanelKind } from "../Sidebar";
import type { User } from "../../api";
import Workspace from "./Workspace";
import Collab from "./Collab";
import Sources from "./Sources";
import LanguageSelect from "../LanguageSelect";
import Automations from "./Automations";
import Integrations from "./Integrations";

function Shell({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const element = dialog.current!;
    element.showModal();
    // Loading content can replace the currently focused control. Keep keyboard
    // focus in the modal when that happens, without moving an existing focus.
    const observer = new MutationObserver(() => {
      if (element.open && !element.contains(document.activeElement)) element.querySelector("button")?.focus();
    });
    observer.observe(element, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      element.close();
      if (previous?.getClientRects().length && getComputedStyle(previous).visibility !== "hidden") previous.focus();
      else document.querySelector<HTMLButtonElement>(".mobile-bar button")?.focus();
    };
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

const LEVELS: [AttentionLevel, string][] = [
  ["now", "立刻告诉我"],
  ["batch", "攒着一起说"],
  ["brief", "只放进早上简报"],
  ["mute", "不提醒，只在看板里跟踪"],
];
const GROUPS: Record<string, string> = {
  approval: "审批", mail: "邮件", chat: "聊天里的事", invitation: "会议邀请",
  waiting: "在等别人的事", biz: "业务系统通知", attendance: "考勤", task: "飞书任务",
};

/** 规则说的是哪一类事：类别 + 人 / 审批类型 / 群 / 系统（人名、群名等是业务数据，不翻译）。 */
function ruleTarget(rule: NotifyRule): string {
  const m = rule.match;
  const parts = [m.approval ? `${m.approval} · ${t("审批")}` : m.group ? t(GROUPS[m.group] ?? m.group) : t("所有事")];
  if (m.person) parts.push(t("相关的人：{name}", { name: m.person }));
  if (m.chat) parts.push(t("群：{name}", { name: m.chat }));
  if (m.system) parts.push(m.system);
  return parts.join(" · ");
}

function NotifyRules() {
  const [rules, setRules] = useState<NotifyRule[] | null>(null);
  const [error, setError] = useState(false);
  const load = useCallback(() => api.notifyRules().then(setRules).catch(() => setError(true)), []);
  useEffect(() => void load(), [load]);
  const act = (task: Promise<unknown>) => task.then(load).catch(() => setError(true));
  const active = (rules ?? []).filter((rule) => rule.status !== "proposed");
  const proposed = (rules ?? []).filter((rule) => rule.status === "proposed");
  return (
    <section>
      <h3>{t("提醒规则")}</h3>
      <p className="muted small">
        {t("你说过的提醒偏好，Relay 每次通知前都会照做。在对话里说“请假审批不用提醒我”“Budi 的事随时告诉我”，或在事项上点“少提醒这类”，都会出现在这里。")}
      </p>
      {proposed.length > 0 && (
        <>
          <p className="small"><strong>{t("等你确认的候选")}</strong> <span className="muted">{t("从你以前说过的话整理出来，确认前不会生效。")}</span></p>
          {proposed.map((rule) => (
            <div key={rule.id} className="row-card rule-row">
              <span>
                <strong>{ruleTarget(rule)}</strong> → {t(LEVELS.find(([level]) => level === rule.level)?.[1] ?? rule.level)}
                {rule.evidence && <span className="muted small"><br />{t("依据：")}「{rule.evidence}」</span>}
              </span>
              <button className="btn primary small" onClick={() => act(api.decideRule(rule.id, "accept"))}>{t("启用")}</button>
              <button className="btn ghost small" onClick={() => act(api.decideRule(rule.id, "reject"))}>{t("不用")}</button>
            </div>
          ))}
        </>
      )}
      {active.length === 0 && <p className="empty-note">{t("还没有规则。")}</p>}
      {active.map((rule) => (
        <div key={rule.id} className="row-card rule-row">
          <span>
            <strong>{ruleTarget(rule)}</strong>
            {rule.hits > 0 && <span className="muted small"> · {t("已用在 {n} 件事上", { n: rule.hits })}</span>}
          </span>
          <select value={rule.level} aria-label={t("提醒方式")} onChange={(e) => act(api.updateRule(rule.id, e.target.value as AttentionLevel))}>
            {LEVELS.map(([level, label]) => <option key={level} value={level}>{t(label)}</option>)}
          </select>
          <button className="icon-button" title={t("删除")} onClick={() => act(api.deleteRule(rule.id))}>
            <Icon name="trash" size={14} />
          </button>
        </div>
      ))}
      <p className="muted small">{t("紧急的事（例如运营事故、客户或上级催办）即使命中“少提醒”的规则，也会照样马上告诉你。")}</p>
      {error && <p role="alert" className="error-text">{t("操作失败")}</p>}
    </section>
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
  task: "飞书任务里派给我的事",
};

function SettingsForm() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [status, setStatus] = useState<Record<string, SourceStatus>>({});
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);
  // 没有飞书的成员：只显示他自己能接的来源（邮件、日历），飞书才有的（审批、考勤……）不出现
  const [feishuLinked, setFeishuLinked] = useState(true);
  const onSources = useCallback((data: { feishu: { linked: boolean } }) => setFeishuLinked(data.feishu.linked), []);

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

      <Sources onLoaded={onSources} />

      <section>
        <h3>{t("留意哪些事")}</h3>
        {Object.entries(SOURCES).filter(([key]) => feishuLinked || key === "mail" || key === "calendar").map(([key, label]) => (
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
        {feishuLinked && <label className="toggle">
          <input
            type="checkbox"
            checked={settings.sources.private_chat ?? true}
            onChange={(e) => update({ sources: { ...settings.sources, private_chat: e.target.checked } })}
          />
          <span>
            <strong>{t("私聊里的待办")}</strong>
            <span className="muted">
              {t("开启后，Relay 以你的身份读你和常联系同事之间的私聊，找出别人让你做的事和你在等别人的事，有了结果自动结束。私聊内容只用于你自己的事项。")}
            </span>
            {status.private_chat?.error ? (
              <span className="error-text">{status.private_chat.error}</span>
            ) : status.private_chat?.last_synced_at ? (
              <span className="muted">{t("syncedAt", { time: relative(status.private_chat.last_synced_at) })}</span>
            ) : null}
          </span>
        </label>}
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
        <div className="field">
          <span>{t("不急的事汇总时间")}</span>
          <span className="field-pair">
            {(settings.digest_times ?? []).map((time, index) => (
              <span key={index} className="field-pair">
                <input type="time" value={time} onChange={(e) => {
                  const next = [...settings.digest_times];
                  next[index] = e.target.value;
                  update({ digest_times: next });
                }} />
                <button className="icon-button" title={t("删除")} onClick={() => update({ digest_times: settings.digest_times.filter((_, i) => i !== index) })}>
                  <Icon name="x" size={12} />
                </button>
              </span>
            ))}
            {(settings.digest_times ?? []).length < 4 && (
              <button className="btn ghost small" onClick={() => update({ digest_times: [...(settings.digest_times ?? []), "14:00"] })}>
                + {t("加一个时间")}
              </button>
            )}
          </span>
        </div>
        <label className="field">
          <span>{t("每小时最多打扰")}</span>
          <input type="number" min={0} max={60} value={settings.max_interrupts_per_hour} onChange={(e) => update({ max_interrupts_per_hour: Number(e.target.value) })} />
        </label>
        <p className="muted small">
          {t("紧急的事和你上级找你的事随时告诉你，不受次数限制；今天要你处理的事马上告诉你，但每小时有上限，超出的稍后再说；其余的攒到汇总时间一起说，早上的简报也算一次。免打扰时段只说紧急的。")}
        </p>
      </section>

      <NotifyRules />

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

export default function Drawer({ kind, onClose, me, onUserChanged, collabId, onCollabChanged }: {
  kind: PanelKind; onClose: () => void; me?: User; onUserChanged?: () => void;
  /** 从“待处理”里的协作事项打开时，直接显示这一份 */
  collabId?: number | null; onCollabChanged?: () => void;
}) {
  const titles: Record<PanelKind, string> = {
    workspace: me?.is_admin ? t("工作区设置") : t("账号与工作区"),
    collab: t("和同事协作"),
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
      {kind === "collab" && <Collab openId={collabId} onChanged={onCollabChanged} />}
      {kind === "workspace" && me && <Workspace me={me} onChanged={() => onUserChanged?.()} />}
    </Shell>
  );
}
