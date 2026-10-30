import { api } from "./api";

/** 在 Relay 的 Mac 客户端里打开时才有：系统通知、授权文件夹、设备配对。浏览器里是 null。 */
export interface LocalFolder { id: string; label: string; read: boolean; write: boolean; root: string }
export interface DesktopStatus { paired: boolean; revoked: boolean; deviceId: string | null; name: string; platform: string; version: string }
export interface DesktopBridge {
  status: () => Promise<DesktopStatus>;
  paired: (info: { token: string; id: string }) => Promise<boolean>;
  unpair: () => Promise<boolean>;
  notify: (title: string, body: string) => Promise<boolean>;
  folders: () => Promise<LocalFolder[]>;
  addFolder: () => Promise<LocalFolder[]>;
  updateFolder: (id: string, change: { read?: boolean; write?: boolean }) => Promise<LocalFolder[]>;
  removeFolder: (id: string) => Promise<LocalFolder[]>;
  reveal: (id: string) => Promise<string>;
  onDeviceChanged: (callback: () => void) => () => void;
}

export function desktop(): DesktopBridge | null {
  return (window as unknown as { relayDesktop?: DesktopBridge }).relayDesktop ?? null;
}

let pairing: Promise<DesktopStatus | null> | null = null;

/** 登录后把这台 Mac 和账号配对（第一次自动；被撤销过的要他自己点“重新连接”）。同时多次调用只配对一次。 */
export function pairIfNeeded(force = false): Promise<DesktopStatus | null> {
  pairing ??= pair(force).finally(() => { pairing = null; });
  return pairing;
}

/** 退出登录：这台 Mac 也和账号断开（下一个登录的人重新配对给他自己）。 */
export async function unpairOnLogout() {
  const bridge = desktop();
  if (!bridge) return;
  const status = await bridge.status();
  if (status.deviceId) await api.revokeDevice(status.deviceId).catch(() => undefined);
  await bridge.unpair();
}

async function pair(force: boolean): Promise<DesktopStatus | null> {
  const bridge = desktop();
  if (!bridge) return null;
  let status = await bridge.status();
  if (status.paired && status.deviceId) {
    // 已配对：确认配的是现在登录的这个人（换了人登录就重新配对给他，不能沿用上一个人的）
    const mine = await api.devices().catch(() => null);
    if (mine === null || mine.some((d) => d.id === status.deviceId)) return status;
    await bridge.unpair();
    status = await bridge.status();
  }
  if (status.paired || (status.revoked && !force)) return status;
  const device = await api.pairDevice(status.name, status.platform, status.version);
  await bridge.paired({ token: device.token, id: device.id });
  return bridge.status();
}
