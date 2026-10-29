import { t } from "../i18n";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { api } from "../api";
import Icon from "./Icon";

export default function Composer({
  busy,
  placeholder,
  onSend,
  model,
  onModel,
  context,
  onClearContext,
}: {
  /** 从详情栏“带着它问 Relay”：输入框上方显示可移除的标签，发送时附上；不会自动发送，原来的草稿保留 */
  context?: { label: string; ref: string; n: number } | null;
  onClearContext?: () => void;
  busy: boolean;
  placeholder: string;
  onSend: (text: string) => void;
  model: string | null;
  onModel: (model: string) => void;
}) {
  const [text, setText] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    api.models().then((result) => {
      setModels(result.models);
      if (!model && result.default) onModel(result.default);
    });
    // 只在挂载时取一次模型列表
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (context) area.current?.focus();
  }, [context]);

  useEffect(() => {
    if (area.current) {
      area.current.style.height = "auto";
      area.current.style.height = `${Math.min(area.current.scrollHeight, 220)}px`;
    }
  }, [text]);

  const submit = () => {
    const value = text.trim();
    if (!value || busy) return;
    onSend(context ? `${context.ref}${value}` : value);
    setText("");
    onClearContext?.();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // 输入法组字时的回车是在选词，不是发送
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
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
        {models.length > 1 ? (
          <select value={model ?? ""} onChange={(event) => onModel(event.target.value)} aria-label={t("模型")}>
            {models.map((id) => (
              <option key={id} value={id}>
                {id.split(":")[1]}
              </option>
            ))}
          </select>
        ) : (
          <span className="composer-hint">{models[0]?.split(":")[1] ?? t("未配置模型")}</span>
        )}
        <button className="send" disabled={busy || !text.trim()} onClick={submit} aria-label={t("发送")}>
          <Icon name="arrowUp" size={18} />
        </button>
      </div>
    </div>
  );
}
