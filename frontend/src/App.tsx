import { t } from "./i18n";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Conversation, type User } from "./api";
import Icon, { RelayMark } from "./components/Icon";
import { useLocale } from "./useLocale";
import { useViewport } from "./useViewport";
import Login from "./components/Login";
import Drawer from "./components/panels/Drawer";
import Evaluation from "./components/Evaluation";
import Sidebar, { type PanelKind, type View } from "./components/Sidebar";
import Inspector, { type AskContext } from "./components/Inspector";
import WorkDock, { type WorkView } from "./components/WorkDock";
import { useWork } from "./work";
import Admin from "./components/Admin";
import Missions from "./components/Missions";
import Thread from "./components/Thread";

export default function App() {
  useLocale();
  useViewport();
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [view, setView] = useState<View>({ type: "home" });
  // 工作区：顶部三个入口（待处理 / 会议 / 进展）打开右侧详情栏；宽屏时详情栏和对话并排，窄屏时盖在对话上
  const work = useWork(!!user);
  const wide = () => window.matchMedia("(min-width: 1100px)").matches;
  const [workView, setWorkView] = useState<WorkView>("todo");
  const [inspectorOpen, setInspectorOpen] = useState(() => wide());
  const [focus, setFocus] = useState<{ itemIds: number[]; n: number } | null>(null);
  const [context, setContext] = useState<(AskContext & { n: number }) | null>(null);
  const openWork = useCallback((next: WorkView) => {
    setWorkView(next);
    setInspectorOpen(true);
  }, []);
  const [panel, setPanel] = useState<PanelKind | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = useCallback(() => setMenuOpen(false), []);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 821px)");
    const closeOnDesktop = () => { if (desktop.matches) setMenuOpen(false); };
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, []);

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
        onClose={closeMenu}
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
          <button className="icon-button" onClick={(event) => { event.currentTarget.focus({ preventScroll: true }); setMenuOpen(true); }} aria-label={t("菜单")} aria-expanded={menuOpen} aria-controls="sidebar">
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
          <div className={`home-split ${view.type === "home" && inspectorOpen ? "with-inspector" : ""}`}>
            <Thread
              // 新对话拿到 id 时不能重新挂载（流式输出还在进行），所以只按视图类型区分
              key={view.type}
              home={view.type === "home"}
              conversationId={view.type === "chat" ? view.id : null}
              userName={user.name}
              onCreated={(id) => setView({ type: "chat", id })}
              onTurnFinished={refresh}
              header={view.type === "home" ? (
                <WorkDock work={work} active={workView} inspectorOpen={inspectorOpen} onOpen={openWork}
                  onToggle={() => setInspectorOpen((o) => !o)} onPreferences={() => setPanel("settings")} />
              ) : undefined}
              onOpenItems={(itemIds) => { setWorkView("todo"); setFocus({ itemIds, n: Date.now() }); setInspectorOpen(true); }}
              context={view.type === "home" ? context : null}
              onClearContext={() => setContext(null)}
            />
            {view.type === "home" && inspectorOpen && (
              <Inspector
                work={work}
                view={workView}
                focus={focus}
                onClose={() => setInspectorOpen(false)}
                // 带着它回到对话：输入框上方出现可移除的标签，不自动发送；窄屏时关掉详情栏回到对话
                onAsk={(ctx) => {
                  setContext({ ...ctx, n: Date.now() });
                  if (!wide()) setInspectorOpen(false);
                }}
              />
            )}
          </div>
        )}
      </div>
      {panel && <Drawer kind={panel} onClose={() => setPanel(null)} />}
    </div>
  );
}
