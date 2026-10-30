import { t } from "../i18n";
import { useEffect, useState, type FormEvent } from "react";
import { api, type User, type WorkspaceChoice } from "../api";
import LanguageSelect from "./LanguageSelect";
import { RelayMark } from "./Icon";

const ERRORS: Record<string, string> = {
  denied: "你取消了飞书授权。",
  state: "登录已过期，请重新发起。",
  feishu: "飞书登录失败，请稍后再试。",
  tenant: "这个飞书账号不属于这个工作区，无法登录。",
  no_feishu: "这个工作区还没有接入飞书，请用邮箱登录。",
  deactivated: "你在这个工作区的账号已停用，请联系管理员。",
};

/** 登录：邮箱 + 密码（账号加入了多个工作区时先选一个），或者用飞书登录；允许注册时可以新建工作区。 */
export default function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [config, setConfig] = useState<{ dev_login: boolean; signup?: boolean; feishu?: boolean }>({ dev_login: false, feishu: true });
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [choose, setChoose] = useState<WorkspaceChoice[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const query = new URLSearchParams(window.location.search);
  const loginError = query.get("login_error");
  // 其他工作区的飞书登录：/?workspace=slug 或管理员给的登录链接
  const feishuHref = query.get("workspace") ? `/api/auth/feishu/login?workspace=${encodeURIComponent(query.get("workspace") ?? "")}` : "/api/auth/feishu/login";

  useEffect(() => {
    api.authConfig().then(setConfig).catch(() => undefined);
  }, []);

  const run = async (task: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await task();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("登录失败。"));
    } finally {
      setBusy(false);
    }
  };

  const login = (tenantId?: string) => run(async () => {
    const result = await api.passwordLogin(email, password, tenantId);
    if ("choose" in result) setChoose(result.choose);
    else onLogin(result);
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (mode === "signup") void run(async () => onLogin(await api.signup(name, email, password, workspace)));
    else void login();
  };

  return (
    <div className="login">
      <div className="login-card">
        <RelayMark size={72} animated emotionId={busy ? 'loading' : error || loginError ? 'error' : choose ? 'questioning' : 'idle'} />
        <h1>Relay</h1>
        <LanguageSelect />
        <p>{t("替你留意邮件、日程和审批，该你知道的事会主动告诉你，该做的事先帮你准备好。")}</p>
        {loginError && <p className="login-error">{ERRORS[loginError] ? t(ERRORS[loginError]) : t("登录失败。")}</p>}
        {choose ? (
          <div className="login-form">
            <p className="muted">{t("选择要进入的工作区")}</p>
            {choose.map((w) => (
              <button key={w.tenant_id} className="btn secondary large" disabled={busy} onClick={() => void login(w.tenant_id)}>{w.name}</button>
            ))}
            <button className="btn ghost" onClick={() => setChoose(null)}>{t("返回")}</button>
          </div>
        ) : (
          <form className="login-form" onSubmit={submit}>
            {mode === "signup" && (
              <>
                <label>{t("你的名字")}<input required value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></label>
                <label>{t("工作区名称（公司或团队）")}<input required value={workspace} onChange={(e) => setWorkspace(e.target.value)} /></label>
              </>
            )}
            <label>{t("邮箱")}<input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></label>
            <label>{t("密码")}<input required type="password" minLength={mode === "signup" ? 8 : undefined} value={password}
              onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "signup" ? "new-password" : "current-password"} /></label>
            {error && <p role="alert" className="login-error">{error}</p>}
            <button className="btn primary large" disabled={busy}>
              {busy ? t("请稍候…") : mode === "signup" ? t("创建工作区") : t("登录")}
            </button>
            {config.signup && (
              <button type="button" className="btn ghost" onClick={() => setMode(mode === "login" ? "signup" : "login")}>
                {mode === "login" ? t("新建一个工作区") : t("已有账号，去登录")}
              </button>
            )}
          </form>
        )}
        {config.feishu !== false && mode === "login" && !choose && (
          <>
            <div className="login-divider"><span>{t("或")}</span></div>
            <a className="btn secondary large" href={feishuHref}>{t("使用飞书登录")}</a>
          </>
        )}
        {config.dev_login && (
          <button className="btn ghost" onClick={() => api.devLogin().then(onLogin)}>
            {t("本地调试登录")}
          </button>
        )}
        <a className="btn ghost" href="/blog/">{t("blogTitle")}</a>
      </div>
    </div>
  );
}
