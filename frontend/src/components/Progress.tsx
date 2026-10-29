import { t } from "../i18n";
import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type ProgressData } from "../api";
import { dayLabel, relative, timeOf } from "../format";

/** 进展：已经有结果的事（按天），以及 Relay 发过的汇总和简报。不需要他做什么，想看时再看。 */
export default function Progress() {
  const [data, setData] = useState<ProgressData | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => void api.progress().then(setData).catch(() => setError(true)), []);

  return (
    <main className="workspace single">
      <section className="ws-list wide">
        <header className="ws-head"><h1>{t("进展")}</h1></header>
        {!data && <p className="ws-empty">{error ? t("操作失败") : t("loading")}</p>}
        {data && data.days.length === 0 && data.notes.length === 0 && <p className="ws-empty">{t("最近 7 天还没有结果。")}</p>}
        {data?.days.map((day) => (
          <div key={day.date} className="ws-group">
            <div className="ws-group-head">{dayLabel(`${day.date}T12:00:00`)} <span className="muted">{day.items.length}</span></div>
            {day.items.map((item) => (
              <div key={item.id} className="ws-row static">
                <span className="ws-row-title">{item.status === "done" ? "✓" : "–"} {item.title}</span>
                <span className="ws-row-sub">{item.resolution} · {timeOf(item.closed_at)}</span>
              </div>
            ))}
          </div>
        ))}
        {data && data.notes.length > 0 && (
          <div className="ws-group">
            <div className="ws-group-head">{t("汇总和简报")}</div>
            {data.notes.map((note, n) => (
              <details key={n} className="progress-note">
                <summary>{note.kind === "brief" ? t("简报") : t("汇总")} · {relative(note.created_at)}</summary>
                <Markdown remarkPlugins={[remarkGfm]}>{note.text}</Markdown>
              </details>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
