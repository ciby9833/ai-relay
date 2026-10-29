import { t } from "../i18n";
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import Icon from "./Icon";

export default function Composer({
  busy,
  placeholder,
  onSend,
  context,
  onClearContext,
}: {
  /** 从详情栏“带着它问 Relay”：输入框上方显示可移除的标签，发送时附上；不会自动发送，原来的草稿保留 */
  context?: { label: string; ref: string; n: number } | null;
  onClearContext?: () => void;
  busy: boolean;
  placeholder: string;
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (context) area.current?.focus();
  }, [context]);

  useLayoutEffect(() => {
    const element = area.current!;
    const resize = () => {
      const scrollTop = element.scrollTop;
      const caretAtEnd = document.activeElement === element && element.selectionStart === element.value.length
        && element.selectionEnd === element.value.length;
      element.style.height = "auto";
      element.style.height = `${Math.min(element.scrollHeight, 220)}px`;
      // Measuring with height:auto can reset the scroll position of long drafts.
      element.scrollTop = caretAtEnd ? element.scrollHeight : scrollTop;
    };
    resize();
    // Reflow existing drafts and translated placeholders when the available
    // width changes (rotation, browser zoom, or opening the inspector).
    let width = element.clientWidth;
    const observer = new ResizeObserver(() => {
      if (element.clientWidth === width) return;
      width = element.clientWidth;
      resize();
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [text, placeholder]);

  const submit = () => {
    const value = text.trim();
    if (!value || busy) return;
    onSend(context ? `${context.ref}${value}` : value);
    setText("");
    onClearContext?.();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // 输入法组字时的回车是在选词，不是发送
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <div className="composer">
      {context && (
        <div className="composer-context">
          <span className="context-chip" title={context.label}>
            <Icon name="doc" size={12} /> <span>{context.label}</span>
            <button className="icon-button" onClick={onClearContext} aria-label={t("移除")}><Icon name="x" size={12} /></button>
          </span>
        </div>
      )}
      <textarea
        ref={area}
        value={text}
        rows={1}
        placeholder={placeholder}
        aria-label={placeholder}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
      />
      <div className="composer-bar">
        <button className="send" disabled={busy || !text.trim()} onClick={submit} aria-label={t("发送")}>
          <Icon name="arrowUp" size={18} />
        </button>
      </div>
    </div>
  );
}
