import { t } from "../i18n";
import type { Conversation, User } from "../api";
import { relative } from "../format";
import Icon, { RelayMark } from "./Icon";

export type View = { type: "admin" } | { type: "eval" } | { type: "home" } | { type: "chat"; id: string | null } | { type: "missions"; id: number | null };
export type PanelKind = "memories" | "tasks" | "automations" | "settings" | "integrations";

const CHANNEL: Record<string, string | null> = { web: null, feishu: "飞书群", task: "定时", home: null };

export default function Sidebar({
  user,
  conversations,
  view,
  open,
  onNavigate,
  onDelete,
  onPanel,
  onLogout,
}: {
  user: User;
  conversations: Conversation[];
  view: View;
  open: boolean;
  onNavigate: (view: View) => void;
  onDelete: (id: string) => void;
  onPanel: (panel: PanelKind) => void;
  onLogout: () => void;
}) {
  return (
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <div className="brand">
        <RelayMark size={20} />
        <span>Relay</span>
      </div>

      <nav className="nav">
        <button className={`nav-item new-chat ${view.type === "chat" && view.id === null ? "active" : ""}`}
          onClick={() => onNavigate({ type: "chat", id: null })}>
          <Icon name="plus" /> {t("新对话")}
        </button>
        <button className={`nav-item ${view.type === "home" ? "active" : ""}`} aria-current={view.type === "home" ? "page" : undefined}
          onClick={() => onNavigate({ type: "home" })}>
          <Icon name="sun" /> {t("今天")}
        </button>
        <button className={`nav-item ${view.type === "missions" ? "active" : ""}`} onClick={() => onNavigate({ type: "missions", id: null })}>
          <Icon name="clock" /> {t("长期任务")}
        </button>
        {user.is_admin && <button className={`nav-item ${view.type === "eval" ? "active" : ""}`} onClick={() => onNavigate({ type: "eval" })}>
          <Icon name="check" /> {t("新旧链路对比")}
        </button>}
        {user.is_admin && <button className={`nav-item ${view.type === "admin" ? "active" : ""}`} onClick={() => onNavigate({ type: "admin" })}>
          <Icon name="chart" /> {t("adminTitle")}
        </button>}
      </nav>

      {conversations.length > 0 && <div className="nav-label">{t("最近")}</div>}
      <div className="history">
        {conversations.map((conversation) => (
          <div
            key={conversation.id}
            className={`history-item ${view.type === "chat" && view.id === conversation.id ? "active" : ""}`}
          >
            <button className="history-open" onClick={() => onNavigate({ type: "chat", id: conversation.id })}
              aria-current={view.type === "chat" && view.id === conversation.id ? "page" : undefined}>
              <span className="history-title">{conversation.title ?? t("新对话")}</span>
              {CHANNEL[conversation.channel] && <span className="history-tag">{t(CHANNEL[conversation.channel]!)}</span>}
              <span className="history-time">{relative(conversation.updated_at)}</span>
            </button>
            <button
              className="icon-button history-delete"
              title={t("删除")}
              onClick={(event) => {
                event.stopPropagation();
                if (window.confirm(t("删除这段对话？"))) onDelete(conversation.id);
              }}
            >
              <Icon name="trash" size={14} />
            </button>
          </div>
        ))}
      </div>

      <div className="sidebar-foot">
        <a className="nav-item blog-link" href="/blog/">
          <Icon name="doc" /> {t("blogTitle")}
        </a>
        <button className="nav-item" onClick={() => onPanel("memories")}>
          <Icon name="memory" /> {t("记忆")}
        </button>
        <button className="nav-item" onClick={() => onPanel("tasks")}>
          <Icon name="clock" /> {t("定时任务")}
        </button>
        <button className="nav-item" onClick={() => onPanel("automations")}>
          <Icon name="check" /> {t("自动办的事")}
        </button>
        <button className="nav-item" onClick={() => onPanel("settings")}>
          <Icon name="settings" /> {t("提醒设置")}
        </button>

        {user.is_admin && (
          <button className="nav-item" onClick={() => onPanel("integrations")}>
            <Icon name="external" /> {t("业务系统接入")}
          </button>
        )}
        <div className="me">
          {user.avatar_url ? <img src={user.avatar_url} alt="" /> : <span className="avatar">{user.name.slice(0, 1)}</span>}
          <span className="me-name">{user.name}</span>
          <button className="icon-button" title={t("退出登录")} onClick={onLogout}>
            <Icon name="logout" size={15} />
          </button>
        </div>
      </div>
    </aside>
  );
}
