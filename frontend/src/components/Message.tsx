import { t } from "../i18n";
import { useState, type ReactNode } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ThreadMessage } from "../api";
import { relative, stepActive, stepDone } from "../format";
import InlineCard from "./cards";
import Icon, { RelayMark } from "./Icon";
import { messageEmotion } from '../mascot/state';

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // 非 HTTPS 部署时 clipboard API 不可用：退回到选中复制
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

function CopyButton({ text, label }: { text: () => string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="copy-btn"
      title={t("复制")}
      onClick={async () => {
        await copyText(text());
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
    >
      <Icon name={done ? "check" : "copy"} size={13} />
      {label && <span>{done ? t("已复制") : label}</span>}
    </button>
  );
}

function textOf(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (typeof node === "object" && "props" in node) return textOf((node as { props: { children?: ReactNode } }).props.children);
  return "";
}

// 代码块：自动换行 + 右上角复制按钮
function CodeBlock({ children }: { children?: ReactNode }) {
  return (
    <div className="code-block">
      <CopyButton text={() => textOf(children).replace(/\n$/, "")} />
      <pre>{children}</pre>
    </div>
  );
}

// 过程默认收起：做的时候显示进度，做完只留一行“查了 N 项”，需要时再展开
function Steps({ steps, active }: { steps: string[]; active: boolean }) {
  const [open, setOpen] = useState(false);
  if (!steps.length) return null;
  const unique = [...new Set(steps)];
  const last = steps[steps.length - 1];
  if (!active && !open) {
    return (
      <button type="button" className="steps-toggle" onClick={() => setOpen(true)}>
        <Icon name="check" size={12} /> {t("查了 {count} 项", { count: unique.length })}
        <Icon name="chevron" size={12} />
      </button>
    );
  }
  return (
    <div className="steps">
      {unique.map((name) => {
        const running = active && name === last;
        return (
          <span key={name} className={`step ${running ? "running" : ""}`}>
            {running ? <span className="spinner" /> : <Icon name="check" size={12} />}
            {running ? `${stepActive(name)}…` : stepDone(name)}
          </span>
        );
      })}
      {!active && (
        <button type="button" className="steps-toggle" onClick={() => setOpen(false)}>
          {t("收起")}
        </button>
      )}
    </div>
  );
}

export default function Message({ message, onChanged, active = false }: { message: ThreadMessage; onChanged: () => void; active?: boolean }) {
  if (message.role === "user") {
    return (
      <div className="msg user">
        <div className="bubble">{message.text}</div>
      </div>
    );
  }
  const working = message.pending && !message.text && !(message.cards?.length);
  return (
    <div className={`msg assistant ${message.proactive ? "proactive" : ""}`}>
      <div className="msg-head">
        <RelayMark size={32} emotionId={messageEmotion(message)} animated={active || !!message.pending} />
        <span className="msg-name">Relay</span>
        {message.proactive && <span className="msg-tag">{t("主动告诉你")}</span>}
        {message.created_at && <span className="msg-time">{relative(message.created_at)}</span>}
      </div>
      <Steps steps={message.steps ?? []} active={!!message.pending} />
      {working && !(message.steps?.length) && (
        <div className="thinking">
          <span className="spinner" /> {t("正在想…")} </div>
      )}
      {message.text && (
        <div className="prose">
          <Markdown remarkPlugins={[remarkGfm]} components={{ pre: CodeBlock }}>{message.text}</Markdown>
        </div>
      )}
      {message.text && !message.pending && (
        <div className="msg-actions">
          <CopyButton text={() => message.text ?? ""} label={t("复制全文")} />
        </div>
      )}
      {message.cards && message.cards.length > 0 && (
        <div className="cards">
          {message.cards.map((card, index) => (
            <InlineCard
              key={`${card.kind}-${index}`}
              card={card}
              onChanged={onChanged}
              // 同一条消息里已经附了草稿，邮件卡片上就不再提供“起草回复”
              hasDraft={message.cards!.some((c) => c.kind === "draft")}
            />
          ))}
        </div>
      )}
      {message.error && <div className="msg-error">{message.error}</div>}
    </div>
  );
}
