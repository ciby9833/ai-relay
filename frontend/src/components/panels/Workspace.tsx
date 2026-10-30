import { t } from "../../i18n";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type FeishuConnection, type Invitation, type Member, type User, type WorkspaceChoice } from "../../api";
import { relative } from "../../format";
import { MyDevices } from "./ThisMac";
import { MyProfile, MyTeams, NewWorkspace, OrgAdmin } from "./Org";

const ROLE: Record<Member["role"], string> = { owner: "所有者", admin: "管理员", member: "成员" };

function CopyLine({ label, value }: { label: string; value: string }) {
  return (
    <label className="ws-copy">{label}
      <span className="ws-link">
        <input readOnly value={value} aria-label={label} onFocus={(e) => e.currentTarget.select()} />
        <button type="button" className="btn secondary small" onClick={() => void navigator.clipboard?.writeText(value)}>{t("复制")}</button>
      </span>
    </label>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="ws-section"><h3>{title}</h3>{children}</section>;
}

/** 账号：切换工作区；设置 / 修改登录密码（原来只用飞书登录的，设置后也能用邮箱登录）。 */
function AccountPart({ me, onChanged }: { me: User; onChanged: () => void }) {
  const [list, setList] = useState<WorkspaceChoice[]>([]);
  const [email, setEmail] = useState(me.email ?? "");
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => void api.workspaces().then(setList).catch(() => undefined), []);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setMessage(null);
    try {
      await api.setPassword(password, me.has_password ? current : undefined, me.login_email ? undefined : email);
      setMessage(t("已保存。之后也可以用邮箱和密码登录。"));
      setPassword("");
      setCurrent("");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    }
  };
  return (
    <>
      {list.length > 1 && (
        <Section title={t("切换工作区")}>
          <div className="ws-switch">
            {list.map((w) => (
              <button key={w.tenant_id} className={`btn ${w.current ? "primary" : "secondary"} small`} disabled={w.current}
                onClick={async () => { await api.switchWorkspace(w.tenant_id); window.location.replace("/"); }}>{w.name}</button>
            ))}
          </div>
        </Section>
      )}
      <Section title={me.has_password ? t("修改登录密码") : t("设置邮箱登录")}>
        <form className="ws-form" onSubmit={save}>
          {!me.login_email && (
            <label>{t("登录邮箱")}<input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
          )}
          {me.login_email && <p className="muted small">{t("登录邮箱：{email}", { email: me.login_email })}</p>}
          {me.has_password && (
            <label>{t("当前密码")}<input required type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" /></label>
          )}
          <label>{t("新密码（至少 8 位）")}<input required type="password" minLength={8} value={password}
            onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" /></label>
          {error && <p role="alert" className="error-text">{error}</p>}
          {message && <p className="muted small">{message}</p>}
          <button className="btn primary small">{t("保存")}</button>
        </form>
      </Section>
    </>
  );
}

/** 管理员：成员、邀请、飞书接入。 */
function AdminPart({ me }: { me: User }) {
  const [name, setName] = useState(me.tenant?.name ?? "");
  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invitation[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<Member["role"]>("member");
  const [link, setLink] = useState<string | null>(null);
  const [feishu, setFeishu] = useState<FeishuConnection | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [m, i, f] = await Promise.all([api.members(), api.invitations(), api.feishuConnection()]);
    setMembers(m);
    setInvites(i);
    setFeishu(f);
    setForm({ app_id: f.config.app_id ?? "", tenant_key: f.config.tenant_key ?? "" });
  }, []);
  useEffect(() => void load().catch(() => setError(t("操作失败"))), [load]);

  const run = async (task: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await task();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    } finally {
      setBusy(false);
    }
  };
  const roles: Member["role"][] = me.role === "owner" ? ["owner", "admin", "member"] : ["admin", "member"];
  const status = feishu?.status ?? "none";

  return (
    <>
      {error && <p role="alert" className="error-text">{error}</p>}
      <Section title={t("工作区名称")}>
        <form className="ws-inline" onSubmit={(e) => { e.preventDefault(); void run(() => api.renameWorkspace(name)); }}>
          <input aria-label={t("工作区名称")} value={name} onChange={(e) => setName(e.target.value)} required />
          <button className="btn secondary small" disabled={busy}>{t("保存")}</button>
        </form>
      </Section>

      <Section title={t("成员（{count}）", { count: members.filter((m) => m.status === "active").length })}>
        <ul className="ws-members">
          {members.map((m) => (
            <li key={m.id} className={m.status === "deactivated" ? "muted" : ""}>
              <span className="ws-member-main">
                <span><b>{m.name}</b>{m.me && <span className="badge ws-me">{t("你")}</span>}</span>
                <span className="muted small">{m.email ?? "—"}{m.feishu ? ` · ${t("飞书")}` : ""}{m.password ? ` · ${t("邮箱登录")}` : ""}
                  {m.last_login_at ? ` · ${relative(m.last_login_at)}` : ""}</span>
              </span>
              {m.me ? <span className="badge">{t(ROLE[m.role])}</span> : (
                <span className="ws-member-actions">
                  <select aria-label={t("角色")} value={m.role} disabled={busy || (m.role === "owner" && me.role !== "owner")}
                    onChange={(e) => void run(() => api.changeMember(m.id, { role: e.target.value as Member["role"] }))}>
                    {(m.role === "owner" && me.role !== "owner" ? ["owner" as const] : roles).map((r) => <option key={r} value={r}>{t(ROLE[r])}</option>)}
                  </select>
                  <button className="btn ghost small" disabled={busy}
                    onClick={() => void run(() => api.changeMember(m.id, { status: m.status === "active" ? "deactivated" : "active" }))}>
                    {m.status === "active" ? t("停用") : t("恢复")}
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      </Section>

      <Section title={t("邀请成员")}>
        <form className="ws-inline" onSubmit={(e) => { e.preventDefault(); void run(async () => { setLink((await api.invite(inviteEmail, inviteRole)).link); setInviteEmail(""); }); }}>
          <input type="email" required placeholder="name@company.com" aria-label={t("邮箱")} value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} />
          <select aria-label={t("角色")} value={inviteRole} onChange={(e) => setInviteRole(e.target.value as Member["role"])}>
            {roles.map((r) => <option key={r} value={r}>{t(ROLE[r])}</option>)}
          </select>
          <button className="btn primary small" disabled={busy}>{t("生成邀请链接")}</button>
        </form>
        {link && (
          <p className="ws-link">
            <input readOnly value={link} aria-label={t("邀请链接")} onFocus={(e) => e.currentTarget.select()} />
            <button className="btn secondary small" onClick={() => void navigator.clipboard?.writeText(link)}>{t("复制")}</button>
            <span className="muted small">{t("7 天内有效，只能用一次。目前需要你把链接发给对方。")}</span>
          </p>
        )}
        {invites.length > 0 && (
          <ul className="ws-members">
            {invites.map((i) => (
              <li key={i.id}>
                <span className="ws-member-main"><b>{i.email}</b><span className="muted small">{t(ROLE[i.role as Member["role"]] ?? i.role)} · {t("等待接受")}</span></span>
                <button className="btn ghost small" disabled={busy} onClick={() => void run(() => api.revokeInvitation(i.id))}>{t("撤回")}</button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={t("飞书接入")}>
        <p className="muted small">{t("飞书是可选的外部渠道：接入后成员可以用飞书登录，Relay 能读取飞书里的邮件、日程、审批和消息，并通过飞书提醒。没接入时，Relay 本身的对话、记忆和任务照常可用。")}</p>
        <p className="small">
          {t("状态")}：<span className={`badge ${status === "ok" ? "ok" : status === "failed" ? "urgent" : "warn"}`}>
            {status === "ok" ? t("已连通") : status === "failed" ? t("连接失败") : status === "unverified" ? t("未验证") : t("未接入")}</span>
          {feishu?.last_error && <span className="error-text small"> {feishu.last_error}</span>}
        </p>
        {feishu?.managed && <p className="muted small">{t("默认工作区沿用服务器上的飞书配置，这里只读；需要更换时请联系平台运维。")}</p>}
        <form className="ws-form" onSubmit={(e) => { e.preventDefault(); void run(async () => { await api.saveFeishu(form); setForm((f) => ({ app_id: f.app_id, tenant_key: f.tenant_key })); }); }}>
          <fieldset className="ws-fieldset" disabled={feishu?.managed}>
          <label>App ID<input value={form.app_id ?? ""} onChange={(e) => setForm({ ...form, app_id: e.target.value })} /></label>
          <label>{t("企业 Tenant Key（只允许这家企业的飞书账号登录）")}<input value={form.tenant_key ?? ""} onChange={(e) => setForm({ ...form, tenant_key: e.target.value })} /></label>
          {(["app_secret", "verification_token", "encrypt_key"] as const).map((key) => (
            <label key={key}>{{ app_secret: "App Secret", verification_token: "Verification Token", encrypt_key: "Encrypt Key" }[key]}
              <input type="password" autoComplete="off" value={form[key] ?? ""}
                placeholder={feishu?.secrets[key] ? t("已填写（留空表示不改）") : ""}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
            </label>
          ))}
          </fieldset>
          {feishu?.redirect_uri && <p className="muted small">{t("飞书后台的重定向 URL 填：{url}", { url: feishu.redirect_uri })}</p>}
          {feishu?.events_url && (
            <div className="ws-urls">
              <CopyLine label={t("事件订阅和卡片回调的请求地址（订阅“接收消息”事件和“卡片回传交互”）")} value={feishu.events_url} />
              {feishu.login_url && <CopyLine label={t("成员用飞书登录这个工作区的链接")} value={feishu.login_url} />}
            </div>
          )}
          <span className="ws-inline">
            {!feishu?.managed && <button className="btn primary small" disabled={busy}>{t("保存")}</button>}
            <button type="button" className="btn secondary small" disabled={busy || !feishu?.configured} onClick={() => void run(() => api.testFeishu())}>
              {t("测试连接")}
            </button>
          </span>
        </form>
      </Section>
    </>
  );
}

export default function Workspace({ me, onChanged }: { me: User; onChanged: () => void }) {
  return (
    <>
      <p className="muted small">{t("当前工作区：{name}", { name: me.tenant?.name ?? "—" })} · {t(ROLE[me.role ?? "member"])}</p>
      <MyProfile me={me} />
      {!me.is_admin && <MyTeams me={me} />}
      <AccountPart me={me} onChanged={onChanged} />
      <MyDevices />
      <NewWorkspace me={me} />
      {me.is_admin && <AdminPart me={me} />}
      {me.is_admin && <OrgAdmin feishu={!!me.feishu_linked} />}
    </>
  );
}
