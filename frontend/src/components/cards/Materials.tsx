import { localize, t } from "../../i18n";
import { useState } from "react";
import { api, type CaseContent, type CaseRef } from "../../api";
import { dayLabel, timeOf } from "../../format";
import Icon from "../Icon";

const KIND: Record<CaseRef["kind"], [string, string]> = {
  mail: ["mail", "邮件"],
  sent: ["mail", "你发的邮件"],
  attachment: ["doc", "附件"],
  doc: ["doc", "飞书文档"],
  approval: ["approval", "审批单"],
  chat: ["bell", "聊天"],
  meeting: ["calendar", "会议"],
  history: ["clock", "之前的事"],
};

function Row({ itemId, item }: { itemId: number; item: CaseRef }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<CaseContent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [icon, label] = KIND[item.kind];
  const toggle = async () => {
    if (open) return setOpen(false);
    setOpen(true);
    if (data) return;
    setBusy(true);
    setError(null);
    try {
      setData(await api.openCaseRef(itemId, item.ref));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className={`material ${item.weak ? "weak" : ""}`}>
      <div className="material-head">
        <Icon name={icon} size={14} />
        <span className="material-main">
          <span className="material-title">{item.title}</span>
          <span className="material-meta">
            {t(label)}
            {item.who && <> · {item.who}</>}
            {item.at && <> · {dayLabel(item.at)} {timeOf(item.at)}</>}
          </span>
          <span className="material-why">{t("关联依据：")}{localize(item.why_ui, item.why)}</span>
        </span>
        <button className="btn ghost small" aria-expanded={open} onClick={toggle}>
          {open ? t("收起") : t("查看原文")}
        </button>
      </div>
      {open && (
        <div className="material-body">
          {busy && <p className="muted small">{t("正在读取…")}</p>}
          {error && <p role="alert" className="error-text">{error}</p>}
          {data && (
            <>
              <pre className="material-text">{data.content}</pre>
              {data.truncated && <p className="muted small">{t("内容较长，只显示了前面一部分。")}</p>}
              {data.url && (
                <a className="btn ghost small" href={data.url} target="_blank" rel="noreferrer">
                  <Icon name="external" size={14} /> {t("在飞书打开")}
                </a>
              )}
            </>
          )}
        </div>
      )}
    </li>
  );
}

/** 事项详情里的“相关材料”：按规则关联的邮件、附件、文档、聊天、会议，每条写明关联依据；打开原文时后端会按你的权限重新校验。 */
export default function Materials({ itemId }: { itemId: number }) {
  const [refs, setRefs] = useState<CaseRef[] | null>(null);
  const [error, setError] = useState(false);
  const load = () => {
    if (refs || error) return;
    api.itemCase(itemId).then((data) => setRefs(data.refs)).catch(() => setError(true));
  };
  const strong = (refs ?? []).filter((ref) => !ref.weak);
  const weak = (refs ?? []).filter((ref) => ref.weak);
  return (
    <details className="materials" onToggle={(event) => (event.currentTarget.open ? load() : undefined)}>
      <summary>{t("相关材料")}{refs ? ` · ${strong.length}` : ""}</summary>
      {error && <p role="alert" className="error-text">{t("操作失败")}</p>}
      {refs === null && !error && <p className="muted small">{t("正在查找…")}</p>}
      {refs && refs.length === 0 && <p className="muted small">{t("没有找到相关材料。")}</p>}
      {strong.length > 0 && (
        <ul className="material-list">
          {strong.map((ref) => <Row key={ref.ref} itemId={itemId} item={ref} />)}
        </ul>
      )}
      {weak.length > 0 && (
        <>
          <p className="muted small material-weak-note">{t("只是同一个人，未必和这件事有关：")}</p>
          <ul className="material-list">
            {weak.map((ref) => <Row key={ref.ref} itemId={itemId} item={ref} />)}
          </ul>
        </>
      )}
      {refs && refs.length > 0 && (
        <p className="muted small">{t("这些材料是按规则关联的（同一邮件线程、链接、提到同样的内容……），是否真的相关请以原文为准。")}</p>
      )}
    </details>
  );
}
