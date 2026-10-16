import type { ReactNode } from "react";
import Icon from "../Icon";

/** 对话里内嵌卡片的统一外壳：头部（图标 + 应用名 + 右侧信息）、内容、底部操作。 */
export default function AppCard({
  icon,
  app,
  meta,
  tone,
  children,
  footer,
}: {
  icon: string;
  app: string;
  meta?: ReactNode;
  tone?: "urgent" | "done" | "muted";
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <section className={`app-card ${tone ?? ""}`}>
      <header className="app-card-head">
        <span className="app-card-icon">
          <Icon name={icon} size={14} />
        </span>
        <span className="app-card-name">{app}</span>
        {meta && <span className="app-card-meta">{meta}</span>}
      </header>
      <div className="app-card-body">{children}</div>
      {footer && <footer className="app-card-foot">{footer}</footer>}
    </section>
  );
}

export function Badge({ tone, children }: { tone?: "urgent" | "ok" | "warn"; children: ReactNode }) {
  return <span className={`badge ${tone ?? ""}`}>{children}</span>;
}
