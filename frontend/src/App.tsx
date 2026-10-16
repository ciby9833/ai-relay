import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Conversation, type User } from "./api";
import Icon, { RelayMark } from "./components/Icon";
import Login from "./components/Login";
import Drawer from "./components/panels/Drawer";
import Sidebar, { type PanelKind, type View } from "./components/Sidebar";
import Missions from "./components/Missions";
import Thread from "./components/Thread";

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [view, setView] = useState<View>({ type: "home" });
  const [panel, setPanel] = useState<PanelKind | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch((error) => {
        if (error instanceof ApiError && error.status === 401) setUser(null);
        else throw error;
      });
  }, []);

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

  if (user === undefined) return null;
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
          <button className="icon-button" onClick={() => setMenuOpen(true)} aria-label="菜单">
            <Icon name="menu" />
          </button>
          <RelayMark size={18} />
          <span>Relay</span>
        </div>
        {view.type === "missions" ? (
          <Missions selected={view.id} onSelect={(id) => setView({ type: "missions", id })} />
        ) : (
          <Thread
            // 新对话拿到 id 时不能重新挂载（流式输出还在进行），所以只按视图类型区分
            key={view.type}
            home={view.type === "home"}
            conversationId={view.type === "chat" ? view.id : null}
            userName={user.name}
            onCreated={(id) => setView({ type: "chat", id })}
            onTurnFinished={refresh}
          />
        )}
      </div>
      {panel && <Drawer kind={panel} onClose={() => setPanel(null)} />}
    </div>
  );
}
