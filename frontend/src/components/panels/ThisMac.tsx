import { t } from "../../i18n";
import { useCallback, useEffect, useState } from "react";
import { api, type Device } from "../../api";
import { relative } from "../../format";
import { desktop, pairIfNeeded, type DesktopStatus, type LocalFolder } from "../../desktop";

/** Mac 客户端里：这台 Mac 授权给 Relay 的文件夹（读写分开），以及它和账号的连接。 */
export function ThisMac() {
  const bridge = desktop();
  const [status, setStatus] = useState<DesktopStatus | null>(null);
  const [folders, setFolders] = useState<LocalFolder[]>([]);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    if (!bridge) return;
    setStatus(await bridge.status());
    setFolders(await bridge.folders());
  }, [bridge]);
  useEffect(() => {
    void load();
    return bridge?.onDeviceChanged(() => void load());
  }, [bridge, load]);
  if (!bridge || !status) return null;
  const run = async (task: () => Promise<LocalFolder[] | unknown>) => {
    setError(null);
    try {
      const result = await task();
      if (Array.isArray(result)) setFolders(result as LocalFolder[]);
      setStatus(await bridge.status());
    } catch (err) {
      setError(err instanceof Error ? err.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, "") : t("操作失败"));
    }
  };
  return (
    <section>
      <h3>{t("这台 Mac")}</h3>
      {status.revoked ? (
        <p className="small">
          <span className="badge urgent">{t("已断开")}</span> {t("这台 Mac 在网页上被撤销了，助理现在用不了它的文件夹。")}{" "}
          <button className="btn secondary small" onClick={() => run(() => pairIfNeeded(true))}>{t("重新连接")}</button>
        </p>
      ) : (
        <p className="muted small">{status.paired ? t("已连接到你的账号。") : t("正在连接到你的账号…")}{" "}
          {t("助理只能使用下面授权的文件夹：读取用来看资料，写入只会新建文件、不会覆盖。完整路径只留在这台 Mac 上。")}</p>
      )}
      {folders.length === 0 && <p className="empty-note">{t("还没有授权文件夹。")}</p>}
      {folders.map((folder) => (
        <div key={folder.id} className="row-card column">
          <div className="row-card-head">
            <strong>{folder.label}</strong>
            <span className="ws-inline">
              <button className="btn ghost small" onClick={() => run(() => bridge.reveal(folder.id))}>{t("在访达中显示")}</button>
              <button className="btn ghost small" onClick={() => window.confirm(t("取消授权「{name}」？", { name: folder.label })) && run(() => bridge.removeFolder(folder.id))}>
                {t("取消授权")}</button>
            </span>
          </div>
          <span className="muted small mac-path">{folder.root}</span>
          <span className="ws-inline">
            <label className="mac-toggle"><input type="checkbox" checked={folder.read} onChange={(e) => run(() => bridge.updateFolder(folder.id, { read: e.target.checked }))} /> {t("允许读取")}</label>
            <label className="mac-toggle"><input type="checkbox" checked={folder.write} onChange={(e) => run(() => bridge.updateFolder(folder.id, { write: e.target.checked }))} /> {t("允许写入新文件")}</label>
          </span>
        </div>
      ))}
      <button className="btn secondary" onClick={() => run(() => bridge.addFolder())}>+ {t("授权一个文件夹")}</button>
      {error && <p role="alert" className="error-text">{error}</p>}
    </section>
  );
}

/** 网页和客户端里都有：登录过 Relay 客户端的电脑，可以撤销。 */
export function MyDevices() {
  const [items, setItems] = useState<Device[] | null>(null);
  const load = useCallback(() => api.devices().then(setItems).catch(() => setItems([])), []);
  useEffect(() => void load(), [load]);
  if (!items || items.length === 0) return null;
  return (
    <section className="ws-section">
      <h3>{t("登录过的电脑")}</h3>
      <ul className="ws-members">
        {items.map((d) => (
          <li key={d.id}>
            <span className="ws-member-main">
              <b>{d.name}</b>
              <span className="muted small">{d.online ? t("在线") : d.last_seen_at ? t("上次在线 {time}", { time: relative(d.last_seen_at) }) : t("不在线")}
                {d.folders.length ? ` · ${t("授权了 {count} 个文件夹", { count: d.folders.length })}` : ""}{d.app_version ? ` · v${d.app_version}` : ""}</span>
            </span>
            <button className="btn ghost small" onClick={async () => {
              if (window.confirm(t("撤销「{name}」？它会立刻断开，助理不能再用它的文件夹。", { name: d.name }))) { await api.revokeDevice(d.id); void load(); }
            }}>{t("撤销")}</button>
          </li>
        ))}
      </ul>
    </section>
  );
}
