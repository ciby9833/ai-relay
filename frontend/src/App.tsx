import { t } from "./i18n";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Conversation, type User } from "./api";
import Icon, { RelayMark } from "./components/Icon";
import { useLocale } from "./useLocale";
import Login from "./components/Login";
import Drawer from "./components/panels/Drawer";
import Evaluation from "./components/Evaluation";
import Sidebar, { type PanelKind, type View } from "./components/Sidebar";
import Tracker, { type TrackerFocus } from "./components/Tracker";
import Admin from "./components/Admin";
import Missions from "./components/Missions";
import Thread from "./components/Thread";

export default function App() {
  useLocale();
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [view, setView] = useState<View>({ type: "home" });
  // “Relay 在跟进”：宽屏时固定在对话右边；窄屏时是浮层，从对话顶部或提醒那一行打开
  const [focus, setFocus] = useState<TrackerFocus | null>(null);
  const [overlay, setOverlay] = useState(false);
  const [draft, setDraft] = useState<{ text: string; n: number } | null>(null);
  const [todoCount, setTodoCount] = useState(0);
  const openTracker = useCallback((next: TrackerFocus) => {
    setFocus(next);
    if (!window.matchMedia("(min-width: 1100px)").matches) setOverlay(true);
  }, []);
  const [panel, setPanel] = useState<PanelKind | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const loadUser = useCallback(() => {
    setLoadError(false);
    void api
      .me()
      .then(setUser)
      .catch((error) => {
        if (error instanceof ApiError && error.status === 401) setUser(null);
        else setLoadError(true);
      });
  }, []);
  useEffect(loadUser, [loadUser]);

  const refresh = useCallback(async () => setConversations(await api.conversations()), []);

  // 对话里的任务卡片点“查看进展”时跳到任务页
  useEffect(() => {
    const open = (event: Event) => setView({ type: "missions", id: (event as CustomEvent<number>).detail });
    window.addEventListener("relay:open-mission", open);
    return () => window.removeEventListener("relay:open-mission", open);
  }, []);
  useEffect(() => {
    if (user) void refresh();
  }, [user, refresh]);

  if (user === undefined) return (
    <div className="login"><div className="login-card">
      <RelayMark size={32} />
      <p role={loadError ? "alert" : "status"}>{t(loadError ? "loadError" : "loading")}</p>
      {loadError && <button className="btn primary" onClick={loadUser}>{t("retry")}</button>}
    </div></div>
  );
  if (user === null) return <Login onLogin={setUser} />;

  const navigate = (next: View) => {
    setView(next);
    setMenuOpen(false);
  };

  return (
    <div className="layout">
      <Sidebar
        user={user}
        conversations={conversations}
        view={view}
        open={menuOpen}
        onNavigate={navigate}
        onDelete={async (id) => {
          await api.deleteConversation(id);
          if (view.type === "chat" && view.id === id) setView({ type: "home" });
          await refresh();
        }}
        onPanel={(kind) => {
          setPanel(kind);
          setMenuOpen(false);
        }}
        onLogout={async () => {
          await api.logout();
          setUser(null);
        }}
      />
      {menuOpen && <div className="sidebar-backdrop" onClick={() => setMenuOpen(false)} />}
      <div className="main">
        <div className="mobile-bar">
          <button className="icon-button" onClick={() => setMenuOpen(true)} aria-label={t("菜单")}>
            <Icon name="menu" />
          </button>
          <RelayMark size={18} />
          <span>Relay</span>
        </div>
        {(user.missing_scopes?.length ?? 0) > 0 && (
          <div className="reauth-bar">
            {t("飞书后台开通了新功能，重新登录一次就能用上（例如看私聊里对方的回复）。")}
            <a className="btn primary" href="/api/auth/feishu/login">{t("重新登录")}</a>
          </div>
        )}
        {view.type === "admin" && user.is_admin ? (
          <Admin />
        ) : view.type === "eval" && user.is_admin ? (
          <Evaluation />
        ) : view.type === "missions" ? (
          <Missions selected={view.id} onSelect={(id) => setView({ type: "missions", id })} />
        ) : (
          <div className={`home-split ${view.type === "home" ? "with-tracker" : ""}`}>
          <Thread
            // 新对话拿到 id 时不能重新挂载（流式输出还在进行），所以只按视图类型区分
            key={view.type}
            draft={view.type === "home" ? draft : null}
            onOpenTracker={view.type === "home" ? openTracker : undefined}
            trackerCount={todoCount}
            home={view.type === "home"}
            conversationId={view.type === "chat" ? view.id : null}
            userName={user.name}
            onCreated={(id) => setView({ type: "chat", id })}
            onTurnFinished={refresh}
          />
          {view.type === "home" && (
            <div className={`tracker-wrap ${overlay ? "open" : ""}`}>
              <Tracker
                focus={focus}
                onCounts={setTodoCount}
                onClose={overlay ? () => setOverlay(false) : undefined}
                // 带着这件事回到对话：输入框里写上编号和标题，Relay 会读这件事的档案，不用重新解释
                onAsk={(item) => {
                  setDraft({ text: t("关于 #{id}《{title}》：", { id: item.id, title: item.title }), n: Date.now() });
                  setOverlay(false);
                }}
              />
            </div>
          )}
          </div>
        )}
      </div>
      {panel && <Drawer kind={panel} onClose={() => setPanel(null)} />}
    </div>
  );
}
