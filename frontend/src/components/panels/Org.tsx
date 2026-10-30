import { t } from "../../i18n";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api, type OrgDepartment, type OrgMember, type OrgOverview, type OrgProfile, type User } from "../../api";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="ws-section"><h3>{title}</h3>{children}</section>;
}

function errorText(err: unknown) {
  return err instanceof Error ? err.message : t("操作失败");
}

/** 部门的完整路径（运营中心 / Medan 站） */
function paths(departments: OrgDepartment[]): Map<string, string> {
  const byId = new Map(departments.map((d) => [d.id, d]));
  const out = new Map<string, string>();
  for (const dept of departments) {
    const names: string[] = [];
    const seen = new Set<string>();
    for (let current: OrgDepartment | undefined = dept; current && !seen.has(current.id); current = current.parent_id ? byId.get(current.parent_id) : undefined) {
      seen.add(current.id);
      names.unshift(current.name);
    }
    out.set(dept.id, names.join(" / "));
  }
  return out;
}

/** 本人：部门和上级（管理员设的，只读）、岗位和负责什么（自己能改）。 */
export function MyProfile({ me }: { me: User }) {
  const [profile, setProfile] = useState<OrgProfile | null>(null);
  const [title, setTitle] = useState("");
  const [duty, setDuty] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void api.myOrgProfile().then((p) => { if (!p || Array.isArray(p)) return; setProfile(p); setTitle(p.title ?? ""); setDuty(p.responsibilities ?? ""); }).catch(() => undefined);
  }, []);
  if (!profile) return null;
  const save = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setNote(null);
    try {
      await api.updateOrgMember(me.id, { title, responsibilities: duty });
      setNote(t("已保存。助理会用这些信息理解你的工作。"));
    } catch (err) {
      setError(errorText(err));
    }
  };
  return (
    <Section title={t("我的资料")}>
      <p className="muted small">{t("部门：{dept} · 直属上级：{manager}", { dept: profile.department ?? "—", manager: profile.manager ?? "—" })}</p>
      <form className="ws-form" onSubmit={save}>
        <label>{t("岗位")}<input value={title} maxLength={255} onChange={(e) => setTitle(e.target.value)} /></label>
        <label>{t("负责什么（客户、线路、项目……）")}<textarea rows={2} maxLength={2000} value={duty} onChange={(e) => setDuty(e.target.value)} /></label>
        {error && <p role="alert" className="error-text">{error}</p>}
        {note && <p className="muted small">{note}</p>}
        <button className="btn secondary small">{t("保存")}</button>
      </form>
    </Section>
  );
}

/** 已登录的账号新建一个工作区（公司 / 团队），自己是所有者。 */
export function NewWorkspace({ me }: { me: User }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  if (!me.login_email) return null;
  return (
    <Section title={t("新建工作区")}>
      {!open ? (
        <button className="btn secondary small" onClick={() => setOpen(true)}>+ {t("新建一个工作区")}</button>
      ) : (
        <form className="ws-inline" onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            await api.createWorkspace(name);
            window.location.replace("/");
          } catch (err) {
            setError(errorText(err));
          }
        }}>
          <input aria-label={t("工作区名称（公司或团队）")} placeholder={t("工作区名称（公司或团队）")} required value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn primary small">{t("创建")}</button>
        </form>
      )}
      {error && <p role="alert" className="error-text">{error}</p>}
    </Section>
  );
}

/** 管理员：部门树、成员的部门 / 上级 / 岗位、团队、从飞书同步。 */
export function OrgAdmin({ feishu }: { feishu: boolean }) {
  const [data, setData] = useState<OrgOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [newDept, setNewDept] = useState({ name: "", parent_id: "" });
  const load = useCallback(() => api.org().then((d) => setData({  // 某一块数据缺了只显示为空，不影响整个面板
    departments: d?.departments ?? [], members: d?.members ?? [], teams: d?.teams ?? [], me: d?.me ?? "", can_edit: !!d?.can_edit,
  })).catch((err) => setError(errorText(err))), []);
  useEffect(() => void load(), [load]);
  const deptPaths = useMemo(() => paths(data?.departments ?? []), [data]);
  if (!data) return error ? <p role="alert" className="error-text">{error}</p> : null;
  const run = async (task: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      await task();
      await load();
      if (done) setNote(done);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const sortedDepts = [...data.departments].sort((a, b) => (deptPaths.get(a.id) ?? "").localeCompare(deptPaths.get(b.id) ?? ""));
  const name = (id: string | null) => data.members.find((m) => m.id === id)?.name ?? "—";
  const memberSelect = (value: string | null, onChange: (id: string | null) => void, label: string, exclude?: string) => (
    <select aria-label={label} value={value ?? ""} disabled={busy} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">{t("{field}：未设置", { field: label })}</option>
      {data.members.filter((m) => m.id !== exclude).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
    </select>
  );

  return (
    <>
      {error && <p role="alert" className="error-text">{error}</p>}
      {note && <p className="muted small">{note}</p>}
      <Section title={t("部门")}>
        {feishu && (
          <p className="small">
            <button className="btn secondary small" disabled={busy} onClick={() => run(async () => {
              const stats = await api.syncOrgFromFeishu();
              setNote(t("已从飞书同步 {depts} 个部门、{members} 位成员；手工改过的没有覆盖。", { depts: stats.departments, members: stats.members }));
            })}>{t("从飞书通讯录同步")}</button>{" "}
            <span className="muted">{t("同步部门、上级和岗位；你在这里手工改过的不会被覆盖。")}</span>
          </p>
        )}
        {sortedDepts.length === 0 && <p className="empty-note">{t("还没有部门。")}</p>}
        <ul className="ws-members">
          {sortedDepts.map((d) => (
            <li key={d.id}>
              <span className="ws-member-main">
                <b>{deptPaths.get(d.id)}</b>
                <span className="muted small">{t("负责人：{name}", { name: name(d.lead_id) })}{d.source === "feishu" ? ` · ${t("来自飞书")}` : ""}</span>
              </span>
              <span className="ws-member-actions">
                {memberSelect(d.lead_id, (id) => void run(() => api.updateDepartment(d.id, { lead_id: id })), t("部门负责人"))}
                <button className="btn ghost small" disabled={busy} onClick={() => {
                  const value = window.prompt(t("新的部门名称"), d.name);
                  if (value && value.trim() && value !== d.name) void run(() => api.updateDepartment(d.id, { name: value.trim() }));
                }}>{t("改名")}</button>
                <button className="btn ghost small" disabled={busy} onClick={() => {
                  if (window.confirm(t("删除部门「{name}」？下级部门会挂到它的上级，成员不会被删除。", { name: d.name }))) void run(() => api.deleteDepartment(d.id));
                }}>{t("删除")}</button>
              </span>
            </li>
          ))}
        </ul>
        <form className="ws-inline" onSubmit={(e) => { e.preventDefault(); void run(async () => {
          await api.createDepartment({ name: newDept.name, parent_id: newDept.parent_id || null });
          setNewDept({ name: "", parent_id: "" });
        }); }}>
          <input aria-label={t("部门名称")} placeholder={t("部门名称")} required value={newDept.name} onChange={(e) => setNewDept({ ...newDept, name: e.target.value })} />
          <select aria-label={t("上级部门")} value={newDept.parent_id} onChange={(e) => setNewDept({ ...newDept, parent_id: e.target.value })}>
            <option value="">{t("顶级部门")}</option>
            {sortedDepts.map((d) => <option key={d.id} value={d.id}>{deptPaths.get(d.id)}</option>)}
          </select>
          <button className="btn secondary small" disabled={busy}>{t("添加部门")}</button>
        </form>
      </Section>

      <Section title={t("成员的部门与上级")}>
        <p className="muted small">{t("上级用来判断谁的事更重要（上级找他的事会优先告诉他）；不用于派任务。")}</p>
        <ul className="ws-members org-members">
          {data.members.map((m: OrgMember) => (
            <li key={m.id}>
              <span className="ws-member-main">
                <b>{m.name}</b>
                <span className="muted small">{m.title || t("未填岗位")}{m.responsibilities ? ` · ${m.responsibilities}` : ""}</span>
              </span>
              <span className="ws-member-actions">
                <select aria-label={t("部门")} value={m.department_id ?? ""} disabled={busy}
                  onChange={(e) => void run(() => api.updateOrgMember(m.id, { department_id: e.target.value || null }))}>
                  <option value="">{t("未设置部门")}</option>
                  {sortedDepts.map((d) => <option key={d.id} value={d.id}>{deptPaths.get(d.id)}</option>)}
                </select>
                {memberSelect(m.manager_id, (id) => void run(() => api.updateOrgMember(m.id, { manager_id: id })), t("直属上级"), m.id)}
              </span>
            </li>
          ))}
        </ul>
      </Section>

      <Teams data={data} busy={busy} run={run} memberSelect={memberSelect} />
    </>
  );
}

function Teams({ data, busy, run, memberSelect }: {
  data: OrgOverview; busy: boolean; run: (task: () => Promise<unknown>) => Promise<void>;
  memberSelect: (value: string | null, onChange: (id: string | null) => void, label: string) => React.ReactNode;
}) {
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [summary, setSummary] = useState<Record<string, { id: string; name: string; open: number; overdue: number; waiting: number }[]>>({});
  return (
    <Section title={t("团队")}>
      <p className="muted small">{t("可以跨部门的一组人（例如项目组）。负责人能看成员的事项数量，看不到内容。")}</p>
      {data.teams.length === 0 && <p className="empty-note">{t("还没有团队。")}</p>}
      {data.teams.map((team) => (
        <div key={team.id} className="row-card column">
          <div className="row-card-head">
            <strong>{team.name}</strong>
            <span className="ws-inline">
              <button className="btn ghost small" onClick={() => setEditing(editing === team.id ? null : team.id)}>{editing === team.id ? t("完成") : t("成员")}</button>
              <button className="btn ghost small" onClick={() => void api.teamSummary(team.id).then((rows) => setSummary({ ...summary, [team.id]: rows }))}>{t("看汇总")}</button>
              <button className="btn ghost small" disabled={busy} onClick={() => window.confirm(t("删除团队「{name}」？", { name: team.name })) && void run(() => api.deleteTeam(team.id))}>{t("删除")}</button>
            </span>
          </div>
          <span className="ws-inline small">{t("负责人")} {memberSelect(team.lead_id, (id) => void run(() => api.updateTeam(team.id, { lead_id: id })), t("团队负责人"))}</span>
          <span className="muted small">{data.members.filter((m) => team.member_ids.includes(m.id)).map((m) => m.name).join("、") || t("还没有成员")}</span>
          {editing === team.id && (
            <span className="team-pick">
              {data.members.map((m) => (
                <label key={m.id} className="mac-toggle">
                  <input type="checkbox" checked={team.member_ids.includes(m.id)} disabled={busy} onChange={(e) => void run(() => api.updateTeam(team.id, {
                    member_ids: e.target.checked ? [...team.member_ids, m.id] : team.member_ids.filter((id) => id !== m.id) }))} /> {m.name}
                </label>
              ))}
            </span>
          )}
          {summary[team.id] && <TeamSummary rows={summary[team.id]} />}
        </div>
      ))}
      <form className="ws-inline" onSubmit={(e) => { e.preventDefault(); void run(async () => { await api.createTeam({ name }); setName(""); }); }}>
        <input aria-label={t("团队名称")} placeholder={t("团队名称")} required value={name} onChange={(e) => setName(e.target.value)} />
        <button className="btn secondary small" disabled={busy}>{t("建立团队")}</button>
      </form>
    </Section>
  );
}

function TeamSummary({ rows }: { rows: { id: string; name: string; open: number; overdue: number; waiting: number }[] }) {
  if (!rows.length) return <p className="muted small">{t("还没有成员")}</p>;
  return (
    <table className="team-summary">
      <thead><tr><th>{t("成员")}</th><th>{t("要处理")}</th><th>{t("逾期")}</th><th>{t("在等别人")}</th></tr></thead>
      <tbody>{rows.map((r) => <tr key={r.id}><td>{r.name}</td><td>{r.open}</td><td className={r.overdue ? "error-text" : ""}>{r.overdue}</td><td>{r.waiting}</td></tr>)}</tbody>
    </table>
  );
}

/** 不是管理员的团队负责人：只看自己负责的团队的汇总。 */
export function MyTeams({ me }: { me: User }) {
  const [teams, setTeams] = useState<{ id: string; name: string }[]>([]);
  const [summary, setSummary] = useState<Record<string, { id: string; name: string; open: number; overdue: number; waiting: number }[]>>({});
  useEffect(() => {
    void api.org().then((data) => {
      const led = (data?.teams ?? []).filter((team) => team.lead_id === me.id);
      setTeams(led);
      for (const team of led) void api.teamSummary(team.id).then((rows) => setSummary((s) => ({ ...s, [team.id]: rows })));
    }).catch(() => undefined);
  }, [me.id]);
  if (!teams.length) return null;
  return (
    <Section title={t("我负责的团队")}>
      {teams.map((team) => (
        <div key={team.id} className="row-card column">
          <strong>{team.name}</strong>
          {summary[team.id] && <TeamSummary rows={summary[team.id]} />}
        </div>
      ))}
    </Section>
  );
}
