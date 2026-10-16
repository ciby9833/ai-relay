import { useCallback, useEffect, useRef, useState } from "react";
import { api, sendMessage, type Board as BoardData, type HomeStatus, type ThreadMessage } from "../api";
import { greeting } from "../format";
import Board from "./Board";
import Composer from "./Composer";
import { RelayMark } from "./Icon";
import Message from "./Message";

const SUGGESTIONS = ["今天有哪些会？", "有哪些邮件需要我回？", "我有什么待审批的？", "帮我搜一下报价相关的文档"];

/** home：主线（Relay 会主动发言）；否则是一段普通对话，conversationId 为空表示新对话 */
export default function Thread({
  home,
  conversationId,
  userName,
  onCreated,
  onTurnFinished,
}: {
  home: boolean;
  conversationId: string | null;
  userName: string;
  onCreated: (id: string) => void;
  onTurnFinished: () => void;
}) {
  const [messages, setMessages] = useState<ThreadMessage[]>([]);
  const [status, setStatus] = useState<HomeStatus | null>(null);
  const [board, setBoard] = useState<BoardData | null>(null);
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
      const [data, boardData] = await Promise.all([api.home(), api.board()]);
      setHomeId(data.conversation.id);
      setMessages(data.messages);
      setStatus(data.status);
      setBoard(boardData);
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
      updateLast((m) => ({ ...m, error: error instanceof Error ? error.message : "发送失败" }));
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
      {home && board && <Board board={board} status={status} onChanged={load} />}
      <div className="thread-scroll">
        <div className="thread-inner">
          {empty && (
            <div className="welcome">
              <RelayMark size={32} />
              <h1>
                {greeting()}，{userName}
              </h1>
              <p>
                {home
                  ? "我会替你留意邮件、日程、审批和考勤，有需要你知道或决定的事会直接在这里告诉你。也可以随时让我帮你做事。"
                  : "想让我帮你做什么？"}
              </p>
              <div className="suggestions">
                {SUGGESTIONS.map((text) => (
                  <button key={text} className="chip" disabled={busy} onClick={() => send(text)}>
                    {text}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((message) => (
            <Message key={message.id} message={message} onChanged={load} />
          ))}
          <div ref={bottom} />
        </div>
      </div>
      <div className="thread-composer">
        <Composer
          busy={busy}
          model={model}
          onModel={setModel}
          onSend={send}
          placeholder={home ? "回复 Relay，或让它帮你做点什么…" : "给 Relay 发消息…"}
        />
        <p className="composer-note">发邮件、回复会议邀请等操作都会先让你确认</p>
      </div>
    </main>
  );
}
