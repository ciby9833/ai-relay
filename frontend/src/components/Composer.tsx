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
  draft,
}: {
  /** 从“Relay 在跟进”里点“在对话里问”：把这件事带进输入框（n 变了就重新带入） */
  draft?: { text: string; n: number } | null;
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
    if (!draft) return;
    setText(draft.text);
    area.current?.focus();
  }, [draft]);

  useEffect(() => {
    if (area.current) {
      area.current.style.height = "auto";
      area.current.style.height = `${Math.min(area.current.scrollHeight, 220)}px`;
    }
  }, [text]);

  const submit = () => {
    const value = text.trim();
    if (!value || busy) return;
    onSend(value);
    setText("");
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
