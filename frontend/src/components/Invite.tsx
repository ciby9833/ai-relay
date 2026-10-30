import { t } from "../i18n";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import LanguageSelect from "./LanguageSelect";
import { RelayMark } from "./Icon";

/** 打开邀请链接：新邮箱设置名字和密码加入；已有账号的输入密码确认是本人。加入后进入这个工作区。 */
export default function Invite({ token }: { token: string }) {
  const [info, setInfo] = useState<{ workspace: string; email: string; role: string; has_account: boolean } | null>(null);
  const [invalid, setInvalid] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.invitationInfo(token).then(setInfo).catch((err) => setInvalid(err instanceof Error ? err.message : t("邀请链接无效")));
  }, [token]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.acceptInvitation(token, password, info?.has_account ? undefined : name);
      window.location.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <div className="login-card">
        <RelayMark size={40} />
        <h1>Relay</h1>
        <LanguageSelect />
        {invalid && <p role="alert" className="login-error">{invalid}</p>}
        {!info && !invalid && <p className="muted">{t("loading")}</p>}
        {info && (
          <form className="login-form" onSubmit={submit}>
            <p>{t("你被邀请加入工作区「{name}」", { name: info.workspace })}</p>
            <p className="muted small">{info.email}</p>
            {!info.has_account && (
              <label>{t("你的名字")}<input required value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></label>
            )}
            <label>{info.has_account ? t("你的登录密码") : t("设置登录密码（至少 8 位）")}
              <input required type="password" minLength={info.has_account ? undefined : 8} value={password}
                onChange={(e) => setPassword(e.target.value)} autoComplete={info.has_account ? "current-password" : "new-password"} />
            </label>
            {error && <p role="alert" className="login-error">{error}</p>}
            <button className="btn primary large" disabled={busy}>{busy ? t("请稍候…") : t("加入工作区")}</button>
          </form>
        )}
      </div>
    </div>
  );
}
