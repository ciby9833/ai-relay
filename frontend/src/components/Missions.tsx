import { t } from "../i18n";
import { useCallback, useEffect, useState } from "react";
import { api, type MissionData } from "../api";
import { dayLabel, relative, timeOf } from "../format";
import { ActionCard, MissionCard } from "./cards";
import Icon, { RelayMark } from "./Icon";

const LOG_ICON: Record<string, string> = {
  wake: "clock",
  step: "chevron",
  report: "bell",
  ask: "alert",
  reply: "mail",
  action: "check",
  done: "check",
};

/** 验收清单：做到这几条才算办成。Relay 只能标记状态和证据，条目只有你能改。 */
function Criteria({ mission, open, onSaved }: { mission: MissionData; open: boolean; onSaved: () => Promise<void> }) {
  const items = mission.criteria ?? [];
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  if (!items.length && !open) return null;
  const save = async () => {
    setError(null);
    try {
      await api.setCriteria(mission.id, draft.split("\n").map((line) => line.trim()).filter(Boolean));
      setEditing(false);
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    }
  };
  return (
    <section>
      <h3>{t("验收清单")}</h3>
      <p className="muted small">{t("做到这几条才算办成。Relay 每标记一条都要附上证据，结束前还会独立核对一遍；条目只有你能改。")}</p>
      {editing ? (
        <>
          <textarea className="criteria-editor" rows={Math.max(3, items.length + 1)} value={draft} aria-label={t("验收清单，每行一条")}
            onChange={(e) => setDraft(e.target.value)} />
          <div className="inline-actions">
            <button className="btn primary small" onClick={save}>{t("保存")}</button>
            <button className="btn ghost small" onClick={() => setEditing(false)}>{t("取消")}</button>
          </div>
          {error && <p role="alert" className="error-text">{error}</p>}
        </>
      ) : (
        <>
          <ul className="criteria">
            {items.map((item) => (
              <li key={item.id} className={`criterion ${item.status}`}>
                <span className="criterion-mark">{item.status === "met" ? "✓" : item.status === "unmet" ? "!" : "○"}</span>
                <span>
                  {item.text}
                  {item.evidence && <span className="muted small criterion-evidence">{t("依据：")}{item.evidence}</span>}
                </span>
              </li>
            ))}
          </ul>
          {!items.length && <p className="empty-note">{t("这个任务还没有验收清单，以你交代的原话为准。")}</p>}
          {open && (
            <button className="btn ghost small" onClick={() => { setDraft(items.map((item) => item.text).join("\n")); setEditing(true); }}>
              {t("修改")}
            </button>
          )}
        </>
      )}
    </section>
  );
}

function Detail({ id, grantable, onChanged }: { id: number; grantable: Record<string, string>; onChanged: () => void }) {
  const [mission, setMission] = useState<MissionData | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => setMission(await api.mission(id)), [id]);
  useEffect(() => {
    void load();
    const timer = window.setInterval(load, 15_000);
    return () => window.clearInterval(timer);
  }, [load]);

  if (!mission) return null;
  const open = ["active", "waiting", "asking"].includes(mission.status);
  const refresh = async () => {
    await load();
    onChanged();
  };
  const act = async (task: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await task();
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mission-detail">
      <header className="mission-head">
        <h1>{mission.title}</h1>
        {open && (
          <span className="mission-tools">
            <button className="btn secondary" disabled={busy} onClick={() => act(() => api.wakeMission(mission.id))}>
              <Icon name="refresh" /> {t("立即推进")}
            </button>
            <button className="btn ghost" disabled={busy} onClick={() => window.confirm(t("停止这个任务？")) && act(() => api.cancelMission(mission.id))}>
              {t("停止")}
            </button>
          </span>
        )}
      </header>
      {mission.instruction && <p className="mission-goal">{t("你交代的：")}「{mission.instruction}」</p>}
      <p className="mission-goal">{mission.goal}</p>
      {mission.due_at && <p className="muted small">{t("截止 / 复查：")}{dayLabel(mission.due_at)} {timeOf(mission.due_at)}</p>}
      <p className="muted small">
        {t("runCount", { count: mission.runs })}
        {mission.status === "waiting" && mission.waiting_for ? t(" · 正在等{p0}", { p0: mission.waiting_for }) : ""}
        {mission.status === "active" && mission.next_run_at ? t(" · 下次 {p0} {p1}", { p0: dayLabel(mission.next_run_at), p1: timeOf(mission.next_run_at) }) : ""}
      </p>

      <MissionCard mission={mission} onChanged={refresh} />

      {mission.pending_actions.length > 0 && (
        <section>
          <h3>{t("等你确认")}</h3>
          <div className="cards">
            {mission.pending_actions.map((action) => (
              <ActionCard key={action.id} action={action} onChanged={refresh} />
            ))}
          </div>
        </section>
      )}

      <Criteria mission={mission} open={open} onSaved={refresh} />

      {mission.plan.length > 0 && (
        <section>
          <h3>{t("计划")}</h3>
          <ul className="plan">
            {mission.plan.map((step, index) => (
              <li key={index} className={step.status === "done" ? "done" : ""}>
                <span className="plan-check">{step.status === "done" && <Icon name="check" size={12} />}</span>
                {step.step}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3>{t("允许 Relay 在这个任务里自动做")}</h3>
        <p className="muted small">{t("默认所有对外操作都先问你。勾选后，这类操作在本任务里会直接执行，做完告诉你。审批始终需要你逐张处理。")}</p>
        {Object.keys(grantable).map((key) => (
          <label key={key} className="toggle">
            <input
              type="checkbox"
              disabled={!open || busy}
              checked={mission.grants.includes(key)}
              onChange={(e) =>
                act(() => api.setGrants(mission.id, e.target.checked ? [...mission.grants, key] : mission.grants.filter((g) => g !== key)))
              }
            />
            <span>
              <strong>{t(`grant.${key}`)}</strong>
            </span>
          </label>
        ))}
      </section>

      {mission.notes && (
        <section>
          <h3>{t("Relay 的工作笔记")}</h3>
          <div className="draft-body readonly">{mission.notes}</div>
        </section>
      )}

      <section>
        <h3>{t("时间线")}</h3>
        <ol className="timeline">
          {(mission.logs ?? []).map((entry, index) => (
            <li key={index} className={`log-${entry.kind}`}>
              <Icon name={LOG_ICON[entry.kind] ?? "chevron"} size={13} />
              <div>
                <div className="timeline-text">{entry.text}</div>
                <div className="muted small">{relative(entry.at)}</div>
              </div>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

export default function Missions({ selected, onSelect }: { selected: number | null; onSelect: (id: number | null) => void }) {
  const [missions, setMissions] = useState<MissionData[]>([]);
  const [grantable, setGrantable] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    const data = await api.missions();
    setMissions(data.missions);
    setGrantable(data.grantable);
  }, []);
  useEffect(() => void load(), [load]);

  return (
    <main className="thread">
      <div className="thread-scroll">
        <div className="thread-inner">
          {selected ? (
            <>
              <button className="btn ghost small back" onClick={() => onSelect(null)}>
                {t("← 全部长期任务")}
              </button>
              <Detail id={selected} grantable={grantable} onChanged={load} />
            </>
          ) : (
            <>
              <div className="welcome compact">
                <RelayMark size={28} />
                <h1>{t("长期任务")}</h1>
                <p>{t("需要持续推进、要等别人回应的事，交给 Relay 在后台办。在主线里说“帮我盯着……直到……”“约齐……开会”就行。")}</p>
              </div>
              {missions.length === 0 && <p className="empty-note">{t("还没有长期任务。")}</p>}
              <div className="cards">
                {missions.map((mission) => (
                  <MissionCard key={mission.id} mission={mission} onChanged={load} onOpen={onSelect} />
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
