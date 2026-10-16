import { t, type LanguagePreference } from "../i18n";
import { useLocale } from "../useLocale";

export default function LanguageSelect({ hint = false }: { hint?: boolean }) {
  const { preference, setPreference } = useLocale();
  return (
    <div className="language-select">
      <label className="field">
        <span>{t("uiLanguage")}</span>
        <select value={preference} onChange={(event) => setPreference(event.target.value as LanguagePreference)}>
          <option value="auto">{t("followSystem")}</option>
          <option value="en" lang="en">English</option>
          <option value="zh" lang="zh-CN">简体中文</option>
          <option value="id" lang="id">Bahasa Indonesia</option>
        </select>
      </label>
      {hint && <p className="muted small">{t("uiLanguageHint")}</p>}
    </div>
  );
}
