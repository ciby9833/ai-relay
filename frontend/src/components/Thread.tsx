import { t } from "../i18n";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, sendMessage, type ThreadMessage } from "../api";
import { greeting, relative } from "../format";
import Composer from "./Composer";
import type { TrackerFocus } from "./Tracker";
import Icon, { RelayMark } from "./Icon";
import Message from "./Message";

const SUGGESTIONS = ["今天有哪些会？", "有哪些邮件需要我回？", "我有什么待审批的？", "帮我搜一下报价相关的文档"];

/** home：主线（Relay 会主动发言）；否则是一段普通对话，conversationId 为空表示新对话 */
export default function Thread({
  home,
  conversationId,
  userName,
  onCreated,
  onTurnFinished,
  onOpenTracker,
  draft,
  trackerCount,
}: {
  onOpenTracker?: (focus: TrackerFocus) => void;
  draft?: { text: string; n: number } | null;
  trackerCount?: number;
  home: boolean;
  conversationId: string | null;
  userName: string;
  onCreated: (id: string) => void;
  onTurnFinished: () => void;
}) {
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [homeId, setHomeId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [model, setModel] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const streaming = useRef(false);
  const createdHere = useRef<string | null>(null);

  const load = useCallback(async () => {
    if (streaming.current) return;
    if (home) {
      const data = await api.home();
      setHomeId(data.conversation.id);
      setMessages(data.messages);
    } else if (conversationId) {
      setMessages(await api.messages(conversationId));
    } else {
      setMessages([]);
    }
    setLoaded(true);
  }, [home, conversationId]);

  useEffect(() => {
    if (!home && conversationId && conversationId === createdHere.current) return;
    setLoaded(false);
    void load();
  }, [home, conversationId, load]);

  // 主线里 Relay 会随时主动发言：定时拉取
  useEffect(() => {
    if (!home) return;
    const timer = window.setInterval(load, 15_000);
    return () => window.clearInterval(timer);
  }, [home, load]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages.length, messages[messages.length - 1]?.text]);

  const updateLast = (update: (message: ThreadMessage) => ThreadMessage) =>
    setMessages((current) => [...current.slice(0, -1), update(current[current.length - 1])]);

  const send = async (text: string) => {
    setBusy(true);
    streaming.current = true;
    const now = new Date().toISOString();
    setMessages((current) => [
      ...current,
      { id: `u${Date.now()}`, role: "user", text },
      { id: `a${Date.now()}`, role: "assistant", text: "", steps: [], cards: [], pending: true, created_at: now },
    ]);
    try {
      let id = home ? homeId : conversationId;
      if (!id) {
        id = (await api.createConversation()).id;
        createdHere.current = id;
        onCreated(id);
      }
      await sendMessage(id, text, model, (event) => {
        if (event.type === "text") updateLast((m) => ({ ...m, text: m.text + event.delta }));
        else if (event.type === "tool_start") updateLast((m) => ({ ...m, steps: [...(m.steps ?? []), event.name] }));
        else if (event.type === "cards") updateLast((m) => ({ ...m, cards: [...(m.cards ?? []), ...event.cards] }));
        else if (event.type === "error") updateLast((m) => ({ ...m, error: event.message }));
      });
    } catch (error) {
      updateLast((m) => ({ ...m, error: error instanceof Error ? error.message : t("发送失败") }));
    } finally {
      streaming.current = false;
      setBusy(false);
      // 用服务端的版本替换本地拼出来的消息（卡片里的操作状态等以服务端为准）
      await load();
      onTurnFinished();
    }
  };

  const empty = loaded && messages.length === 0;

  return (
    <main className="thread">
      {home && onOpenTracker && (
        // 窄屏时“Relay 在跟进”收起来：从这里打开
        <div className="tracker-toggle">
          <button className="btn secondary small" onClick={() => onOpenTracker({ tab: "todo", n: Date.now() })}>
            <Icon name="check" size={14} /> {t("跟进")} {trackerCount ? <b>{trackerCount}</b> : null}
          </button>
        </div>
      )}
      <div className="thread-scroll">
        <div className="thread-inner">
          {empty && (
            <div className="welcome">
              <RelayMark size={32} />
              <h1>
                {t("greetUser", { greeting: greeting(), name: userName })}
              </h1>
              <p>
                {home
                  ? t("我会替你留意邮件、日程、审批和考勤，有需要你知道或决定的事会直接在这里告诉你。也可以随时让我帮你做事。")
                  : t("想让我帮你做什么？")}
              </p>
              <div className="suggestions">
                {SUGGESTIONS.map((text) => (
                  <button key={text} className="chip" disabled={busy} onClick={() => send(t(text))}>
                    {t(text)}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((message) =>
            message.notice && message.role === "assistant" ? (
              // 主动提醒、汇总、简报：内容在待处理 / 进展里，对话里只留一行，追问时 Relay 仍然知道说过什么
              <div key={message.id} className="notice-line">
                <span className="muted small">
                  {message.notice === "brief" ? t("Relay 发了一份简报") : message.notice === "digest" ? t("Relay 发了一份汇总")
                    : t("Relay 提醒了你 {count} 件事", { count: (message.cards ?? []).filter((c) => c.kind === "item").length || 1 })}
                  {message.created_at && ` · ${relative(message.created_at)}`}
                </span>
                {message.notice === "interrupt" && (
                  <button className="btn ghost small" onClick={() => onOpenTracker?.({
                    tab: "todo", n: Date.now(),
                    itemIds: (message.cards ?? []).flatMap((c) => (c.kind === "item" ? [c.item_id] : [])),
                  })}>
                    {t("看这几件")}
                  </button>
                )}
              </div>
            ) : (
              <Message key={message.id} message={message} onChanged={load} />
            ),
          )}
          <div ref={bottom} />
        </div>
      </div>
      <div className="thread-composer">
        <Composer
          busy={busy}
          model={model}
          onModel={setModel}
          onSend={send}
          draft={draft}
          placeholder={home ? t("回复 Relay，或让它帮你做点什么…") : t("给 Relay 发消息…")}
        />
        <p className="composer-note">{t("发邮件、回复会议邀请等操作都会先让你确认")}</p>
      </div>
    </main>
  );
}
