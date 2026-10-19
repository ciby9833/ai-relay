import { t } from "../../i18n";
import { useCallback, useEffect, useState } from "react";
import { api, type AutomationGrant, type AutomationRun } from "../../api";
import { relative } from "../../format";

/** 自动办的事：当前授权了哪些（可以收回），最近按授权办了什么（能撤销的可以撤销）。 */
export default function Automations() {
  const [data, setData] = useState<{ grants: AutomationGrant[]; history: AutomationRun[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const load = useCallback(() => api.automations().then(setData), []);
  useEffect(() => { void load(); }, [load]);

  const run = async (fn: () => Promise<{ message: string }>) => {
    setBusy(true);
    setNote(null);
    try {
      setNote((await fn()).message);
      await load();
    } catch (error) {
      setNote(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  if (!data) return <p className="muted">{t("加载中…")}</p>;
  return (
    <>
      <section>
        <h3>{t("已授权直接办")}</h3>
        {data.grants.length === 0 ? (
          <p className="muted small">
            {t("还没有授权。定时任务或长期任务准备的操作，确认时可以选“以后直接办”；只覆盖那个任务、那个对象。")}
          </p>
        ) : (
          <ul className="plain-list">
            {data.grants.map((grant) => (
              <li key={`${grant.source}-${grant.source_id}-${grant.kind}-${grant.index ?? ""}`} className="row-between">
                <span>
                  <strong>{grant.label}</strong>
                  <span className="muted small">
                    {" · "}{grant.source === "task" ? t("定时任务") : t("长期任务")}《{grant.source_title}》
                    {grant.granted_at && ` · ${relative(grant.granted_at)}`}
                  </span>
                </span>
                <button
                  className="btn ghost"
                  disabled={busy}
                  onClick={() => window.confirm(t("收回这项授权？以后会重新先问你。")) && run(() => api.revokeAutomation(grant))}
                >
                  {t("收回")}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3>{t("最近自动办的事")}</h3>
        {data.history.length === 0 ? (
          <p className="muted small">{t("最近 30 天没有自动办过事。")}</p>
        ) : (
          <ul className="plain-list">
            {data.history.map((item) => (
              <li key={item.action_id} className="row-between">
                <span>
                  <span className={item.undone_at ? "struck" : ""}>{item.result ?? item.summary}</span>
                  <span className="muted small">
                    {" · "}{relative(item.at)}
                    {item.source_title && ` · 《${item.source_title}》`}
                    {item.status !== "done" && ` · ${t("失败")}`}
                    {item.undone_at && ` · ${t("已撤销")}`}
                  </span>
                </span>
                {item.undoable && (
                  <button
                    className="btn ghost"
                    disabled={busy}
                    onClick={() => window.confirm(t("撤销「{p0}」？", { p0: item.summary })) && run(async () => {
                      const result = await api.decide(item.action_id, "undo");
                      return { message: (result as { message: string }).message };
                    })}
                  >
                    {t("撤销")}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
      {note && <p className="muted small">{note}</p>}
    </>
  );
}
