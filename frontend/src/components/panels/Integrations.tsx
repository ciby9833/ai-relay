import { t } from "../../i18n";
import { useCallback, useEffect, useState } from "react";
import { api, type Integration, type IntegrationEvent } from "../../api";
import { relative } from "../../format";

const example = () => JSON.stringify({
  event_id: "order-JT123-exception-1",
  title: t("example.title"),
  content: t("example.content"),
  recipients: [{ email: "someone@company.com" }, { name: "Andrew" }],
  priority: "urgent",
  url: "https://tms.example.com/orders/JT123",
  group_key: "JT123",
  action_hint: t("example.action"),
  due_at: "2026-10-16T18:00:00+07:00",
  data: { order_no: "JT123", customer: t("example.customer") },
}, null, 2);

const SIGN = (endpoint: string) => `import hashlib, hmac, json, time, requests

body = json.dumps(event, ensure_ascii=False).encode()
ts = str(int(time.time()))
sig = hmac.new(SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
requests.post("${endpoint}", data=body, headers={
    "Content-Type": "application/json",
    "X-Relay-Timestamp": ts,
    "X-Relay-Signature": sig,
})`;

const STATUS: Record<string, string> = {
  delivered: "已送达",
  partial: "部分送达",
  unmatched: "没找到收件人",
  resolved: "已标记解决",
};

function Row({ integration, onChanged }: { integration: Integration; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [showSecret, setShowSecret] = useState(false);
  const [events, setEvents] = useState<IntegrationEvent[] | null>(null);

  useEffect(() => {
    if (open) api.integrationEvents(integration.id).then(setEvents);
  }, [open, integration.id]);

  return (
    <div className="row-card column">
      <div className="row-card-head">
        <strong>{integration.name}</strong>
        <button className="btn ghost small" onClick={() => setOpen(!open)}>
          {open ? t("收起") : t("接入信息")}
        </button>
      </div>
      {integration.description && <span className="muted small">{integration.description}</span>}
      {open && (
        <div className="integration-detail">
          <label>{t("推送地址")}</label>
          <code>{integration.endpoint}</code>
          <label>{t("签名密钥")}</label>
          <code>{showSecret ? integration.secret : "••••••••••••••••"}</code>
          <div className="inline-actions">
            <button className="btn ghost small" onClick={() => setShowSecret(!showSecret)}>
              {showSecret ? t("隐藏密钥") : t("显示密钥")}
            </button>
            <button className="btn ghost small" onClick={() => window.confirm(t("换一个新密钥？旧密钥会立即失效。")) && api.rotateIntegration(integration.id).then(onChanged)}>
              {t("更换密钥")}
            </button>
            <button className="btn ghost small" onClick={() => window.confirm(t("删除「{p0}」？", { p0: integration.name })) && api.deleteIntegration(integration.id).then(onChanged)}>
              {t("删除")}
            </button>
          </div>
          <label>{t("签名方式（Python 示例）")}</label>
          <pre>{SIGN(integration.endpoint)}</pre>
          <label>{t("最近收到的事件")}</label>
          {events && events.length === 0 && <span className="muted small">{t("还没有收到事件")}</span>}
          {events?.map((event, index) => (
            <div key={index} className="small">
              <span className="muted">{relative(event.received_at)}</span> · {STATUS[event.status] ? t(STATUS[event.status]) : event.status} · {event.title}
              {event.detail && <span className="error-text">（{event.detail}）</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Integrations() {
  const [list, setList] = useState<Integration[] | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const load = useCallback(() => api.integrations().then(setList), []);
  useEffect(() => void load(), [load]);

  return (
    <>
      <p className="muted">
        {t("业务系统（TMS、WMS、CRM……）有需要人处理的事时，推给 Relay：Relay 会通知到具体的人、放进他的跟进看板， 业务系统推送“已解决”时自动关闭。同一归并键（如订单号）的事件会更新同一件事。")}
      </p>
      <section>
        <h3>{t("登记一个业务系统")}</h3>
        <label className="field">
          <span>{t("名称")}</span>
          <input value={name} placeholder={t("例如 TMS")} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          <span>{t("说明")}</span>
          <input value={description} placeholder={t("推送哪些事件")} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <button
          className="btn primary"
          disabled={!name.trim()}
          onClick={() => api.createIntegration(name.trim(), description.trim() || null).then(() => { setName(""); setDescription(""); return load(); })}
        >
          {t("生成推送地址和密钥")}
        </button>
      </section>
      <section>
        <h3>{t("已接入")}</h3>
        {list?.length === 0 && <p className="empty-note">{t("还没有接入业务系统。")}</p>}
        {list?.map((integration) => <Row key={integration.id} integration={integration} onChanged={load} />)}
      </section>
      <section>
        <h3>{t("推送格式")}</h3>
        <pre>{example()}</pre>
        <p className="muted small">
          {t("priority：urgent 紧急（免打扰时段也会通知）、normal、low（只进简报）。status 传 resolved 时关闭对应的事。 recipients 支持 email、open_id 或名字。")}
        </p>
      </section>
    </>
  );
}
