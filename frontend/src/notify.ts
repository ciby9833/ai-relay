import { t } from "./i18n";
import type { ThreadMessage } from "./api";

/** 浏览器通知：Relay 主动告诉他的事（打断式提醒、简报）在浏览器里弹一下。开关只存在这台浏览器上。 */
const KEY = "relay.notifications";

export function notificationsOn(): boolean {
  try {
    return typeof Notification !== "undefined" && Notification.permission === "granted" && localStorage.getItem(KEY) === "on";
  } catch {
    return false;
  }
}

export async function setNotifications(on: boolean): Promise<boolean> {
  if (typeof Notification === "undefined") return false;
  if (on && Notification.permission !== "granted") {
    if ((await Notification.requestPermission()) !== "granted") return false;
  }
  try {
    localStorage.setItem(KEY, on ? "on" : "off");
  } catch {
    /* 存不了就只在这次有效 */
  }
  return on;
}

let seen: Set<string> | null = null;

/** 首页消息刷新时调用：第一次只记下已有的，之后新出现的主动提醒才通知（标签页在后台时）。 */
export function notifyNew(messages: ThreadMessage[] | undefined) {
  const proactive = (messages ?? []).filter((m) => m.role === "assistant" && m.proactive && (m.notice === "interrupt" || m.notice === "brief"));
  if (seen === null) {
    seen = new Set(proactive.map((m) => String(m.id)));
    return;
  }
  const fresh = proactive.filter((m) => !seen!.has(String(m.id)));
  fresh.forEach((m) => seen!.add(String(m.id)));
  if (!fresh.length || !notificationsOn() || !document.hidden) return;
  const latest = fresh[fresh.length - 1];
  const body = latest.notice === "brief" ? t("今天的简报好了") : (latest.text || "").trim().slice(0, 140) || t("有事需要你看一下");
  try {
    const note = new Notification("Relay", { body, tag: "relay-proactive" });
    note.onclick = () => { window.focus(); note.close(); };
  } catch {
    /* 有的浏览器只允许在 Service Worker 里弹通知：不影响别的 */
  }
}
