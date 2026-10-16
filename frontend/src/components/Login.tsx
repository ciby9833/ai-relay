import { t } from "../i18n";
import { useEffect, useState } from "react";
import { api, type User } from "../api";
import LanguageSelect from "./LanguageSelect";
import { RelayMark } from "./Icon";

const ERRORS: Record<string, string> = {
  denied: "你取消了飞书授权。",
  state: "登录已过期，请重新发起。",
  feishu: "飞书登录失败，请稍后再试。",
  tenant: "这个飞书账号不属于本公司，无法登录。",
};

export default function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [devLogin, setDevLogin] = useState(false);
  const error = new URLSearchParams(window.location.search).get("login_error");

  useEffect(() => {
    api.authConfig().then((config) => setDevLogin(config.dev_login));
  }, []);

  return (
    <div className="login">
      <div className="login-card">
        <RelayMark size={40} />
        <h1>Relay</h1>
        <LanguageSelect />
        <p>{t("替你留意邮件、日程和审批，该你知道的事会主动告诉你，该做的事先帮你准备好。")}</p>
        {error && <p className="login-error">{ERRORS[error] ? t(ERRORS[error]) : t("登录失败。")}</p>}
        <a className="btn primary large" href="/api/auth/feishu/login">
          {t("使用飞书登录")}
        </a>
        {devLogin && (
          <button className="btn ghost" onClick={() => api.devLogin().then(onLogin)}>
            {t("本地调试登录")}
          </button>
        )}
      </div>
    </div>
  );
}
