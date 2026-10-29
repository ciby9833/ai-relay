import { intlLocale, t } from "../i18n";
import { timeOf } from "../format";
import { isMail, sameDay, type Work } from "../work";
import Icon from "./Icon";

export type WorkView = "todo" | "mail" | "meetings" | "progress";

/** 对话顶部的三个工作入口：点开右侧详情栏对应的列表；对话、输入框里的草稿都保留。 */
export default function WorkDock({
  work,
  active,
  inspectorOpen,
  onOpen,
  onToggle,
  onPreferences,
}: {
  work: Work;
  active: WorkView | null;
  inspectorOpen: boolean;
  onOpen: (view: WorkView) => void;
  onToggle: () => void;
  onPreferences: () => void;
}) {
  const today = new Date();
  // 待处理是跨渠道的完整清单（含邮件里要他推进的事）；邮件入口是同一批邮件事项的阅读和回复视图，不另算一份
  const me = work.board?.me.length ?? 0;
  const others = work.board?.others.length ?? 0;
  const mails = [...(work.board?.me ?? []), ...(work.board?.others ?? [])].filter(isMail);
  const toReply = mails.filter((i) => i.kind === "reply").length;
  const upcoming = work.meetings?.upcoming ?? [];
  const next = upcoming.find((m) => m.start && new Date(m.start).getTime() > Date.now() && m.rsvp !== "decline");
  const meetingsToday = upcoming.filter((m) => sameDay(m.start, today)).length;
  const changes = work.progress?.days.reduce((n, d) => n + d.items.length, 0) ?? 0;
  const loading = !work.board;
  const tiles: { view: WorkView; icon: "check" | "calendar" | "chart" | "mail"; label: string; count: number; sub: string }[] = [
    { view: "todo", icon: "check", label: t("待处理"), count: me + others,
      sub: t("需要你 {me} · 在等对方 {others}", { me, others }) },
    { view: "mail", icon: "mail", label: t("邮件"), count: mails.length,
      sub: mails.length ? t("要回 {reply} · 要看 {review}", { reply: toReply, review: mails.length - toReply }) : t("没有要处理的邮件") },
    { view: "meetings", icon: "calendar", label: t("会议"), count: meetingsToday,
      sub: next?.start ? t("下一场 {time}", { time: sameDay(next.start, today) ? timeOf(next.start) : `${new Date(next.start).toLocaleDateString(intlLocale(), { month: "numeric", day: "numeric" })} ${timeOf(next.start)}` }) : t("近期没有会") },
    { view: "progress", icon: "chart", label: t("进展"), count: changes, sub: t("安静汇总，不打扰") },
  ];
  return (
    <section className="dock" aria-label={t("今天的工作")}>
      <header className="dock-head">
        <h1>{t("今天")}</h1>
        <span className="muted">{today.toLocaleDateString(intlLocale(), { month: "long", day: "numeric", weekday: "short" })}</span>
        <span className="spacer" />
        <button className="icon-button" onClick={onToggle} aria-pressed={inspectorOpen} aria-label={inspectorOpen ? t("收起详情栏") : t("打开详情栏")}>
          <Icon name="panel" size={18} />
        </button>
      </header>
      <div className="dock-tiles">
        {tiles.map((tile) => (
          <button key={tile.view} className={`dock-tile ${active === tile.view && inspectorOpen ? "active" : ""}`}
            aria-pressed={active === tile.view && inspectorOpen} onClick={() => onOpen(tile.view)}>
            <Icon name={tile.icon} size={16} />
            <span className="dock-text">
              <span className="dock-label">{tile.label} <b>{loading ? "…" : tile.count}</b></span>
              <span className="dock-sub">{loading ? t("loading") : tile.sub}</span>
            </span>
            <Icon name="chevron" size={14} />
          </button>
        ))}
      </div>
      <div className="dock-status">
        {work.error ? (
          <span className="status-warn small">{t("同步失败，显示的是上次的结果")} · <button className="link" onClick={() => void work.refresh()}>{t("retry")}</button></span>
        ) : (
          <span className="muted small"><span className="status-dot" /> {work.loadedAt ? t("已同步 · {time}", { time: timeOf(work.loadedAt.toISOString()) }) : t("正在同步…")}
            {work.status?.source_errors ? <span className="status-warn"> · {t("sourceErrorCount", { count: work.status.source_errors })}</span> : null}</span>
        )}
        <button className="link muted small" onClick={onPreferences}>{t("只在需要你时提醒")}</button>
      </div>
    </section>
  );
}
