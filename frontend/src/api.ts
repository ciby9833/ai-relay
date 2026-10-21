import { t, type LocalizedText } from "./i18n";
export interface User {
  is_admin: boolean;
  id: string;
  name: string;
  email: string | null;
  avatar_url: string | null;
  missing_scopes?: string[]; // 应用新开通、他的登录还没包含的权限：需要重新登录一次
}

export interface Conversation {
  id: string;
  title: string | null;
  channel: "home" | "web" | "feishu" | "task";
  updated_at: string;
}

export interface Action {
  id: number;
  kind:
    | "send_mail"
    | "calendar_rsvp"
    | "approval_decision"
    | "cloud_write"
    | "send_chat"
    | "create_task"
    | "create_event"
    | "update_event"
    | "delete_event"
    | "add_attendees"
    | "base_record";
  summary: string;
  status: "pending" | "done" | "cancelled" | "failed";
  result: string | null;
  to: string | null;
  subject: string | null;
  body: string | null;
  rsvp: string | null;
  references?: string[];
  reply_all?: boolean;
  others?: string[];
  start?: string | null;
  due?: string | null;
  link?: string | null;
  mission_id?: number | null;
  cells?: { cell: string; before: string; after: string | number }[] | null;
  notes?: string[] | null;
  auto?: boolean; // 按授权自动执行的
  undoable?: boolean; // 能撤销（删除提交的记录、撤回消息……）
  undone_at?: string | null;
  grantable?: boolean; // 定时任务里准备的：确认时可以顺带授权以后直接办
  shown?: Record<string, string> | null; // 多维表格：要提交的字段和值
}

export interface AutomationGrant {
  source: "mission" | "task";
  source_id: number;
  source_title: string;
  kind: string;
  index?: number;
  label: string;
  granted_at: string | null;
}

export interface AutomationRun {
  action_id: number;
  kind: string;
  summary: string;
  status: Action["status"];
  result: string | null;
  at: string;
  source: "mission" | "task" | null;
  source_title: string | null;
  undoable: boolean;
  undone_at: string | null;
}

export interface MissionData {
  id: number;
  title: string;
  goal: string;
  instruction?: string | null;
  due_at?: string | null;
  status: "active" | "waiting" | "asking" | "done" | "failed" | "cancelled";
  plan: { step: string; status: "todo" | "done" }[];
  notes: string | null;
  grants: string[];
  question: string | null;
  result: string | null;
  runs: number;
  waiting_for: string | null;
  next_run_at: string | null;
  updated_at: string;
  pending_actions: Action[];
  logs?: { kind: string; text: string; at: string }[];
}

export type Card =
  | {
      kind: "mail";
      signal_id: number;
      from: string | null;
      from_address: string | null;
      subject: string;
      summary: string;
      importance: "urgent" | "normal" | "low" | null;
      needs_reply: boolean;
      time: string | null;
    }
  | { kind: "draft"; action_id: number; action?: Action }
  | {
      kind: "event";
      signal_id: number;
      title: string;
      start: string | null;
      end: string | null;
      all_day: boolean | null;
      location: string | null;
      organizer: string | null;
      attendees: string[];
      meeting_url: string | null;
      app_link: string | null;
      rsvp: string | null;
      conflicts: string[];
      action_id: number | null;
      action?: Action;
    }
  | { kind: "approval"; title: string; detail: string | null; url: string | null }
  | {
      kind: "alert";
      source: string;
      title: string;
      detail: string | null;
      context: string | null;
      url: string | null;
      level: "urgent" | "normal";
    }
  | { kind: "doc"; title: string; summary: string; url: string | null; updated: string | null }
  | { kind: "item"; item_id: number; item?: FollowUp }
  | { kind: "mission"; mission_id: number; mission?: MissionData }
  | { kind: "action"; action_id: number; action?: Action };

export interface FollowUp {
  id: number;
  kind: "reply" | "review" | "invitation" | "approval" | "attendance" | "mention" | "request" | "waiting" | "biz";
  owner: "me" | "others";
  title: string;
  summary: string | null;
  next_step: string | null;
  recommendation: string | null;
  waiting_on: string | null;
  url: string | null;
  open_url?: string | null; // 经 Relay 跳转到原文（会记下他打开了原文）
  importance: "urgent" | "normal";
  status: "open" | "done" | "dismissed";
  resolution: string | null;
  due_at: string | null;
  remind_at: string | null;
  updated_at: string | null;
  count: number;
  action: Action | null;
  ask: string;
  ask_ui?: LocalizedText | null;
  source: Card | null;
  detail: { name: string; value: string }[];
  quick_approve: boolean;
  attention?: AttentionLevel | null;
  announced?: boolean;
  quieter?: boolean;
}

export interface CaseRef {
  ref: string;
  kind: "mail" | "sent" | "attachment" | "doc" | "approval" | "chat" | "meeting" | "history";
  title: string;
  why: string;
  why_ui?: LocalizedText | null;
  who: string | null;
  at: string | null;
  note: string | null;
  weak: boolean;
}

export interface CaseContent {
  ref: CaseRef;
  content: string;
  truncated: boolean;
  url: string | null;
}

export type AttentionLevel = "now" | "batch" | "brief" | "mute";

export interface NotifyRule {
  id: number;
  match: { group?: string; person?: string; approval?: string; chat?: string; system?: string };
  level: AttentionLevel;
  label: string;
  source: "chat" | "card" | "web" | "memory";
  status: "active" | "proposed";
  evidence: string | null;
  hits: number;
  last_hit_at: string | null;
}

export interface RelayTask {
  kind: "meeting_prep" | "watch";
  title: string;
  detail: string;
  at: string | null;
  title_ui?: LocalizedText;
  detail_ui?: LocalizedText;
}

export interface Integration {
  id: number;
  key: string;
  name: string;
  description: string | null;
  enabled: boolean;
  endpoint: string;
  secret: string | null;
}

export interface IntegrationEvent {
  event_id: string;
  title: string;
  status: string;
  detail: string | null;
  received_at: string;
}

export interface Board {
  me: FollowUp[];
  others: FollowUp[];
  relay: RelayTask[];
}

export interface ThreadMessage {
  id: number | string;
  role: "user" | "assistant";
  text: string;
  steps?: string[];
  cards?: Card[];
  proactive?: boolean;
  created_at?: string;
  error?: string;
  pending?: boolean;
}

export interface HomeStatus {
  meetings_left_today: number;
  approvals_pending: number;
  mails_today: number;
  actions_pending: number;
  last_synced_at: string | null;
  source_errors: number;
}

export interface Memory {
  id: number;
  kind: "profile" | "episodic";
  content: string;
  created_at: string;
}

export interface Task {
  id: number;
  title: string;
  prompt: string;
  cron: string | null;
  enabled: boolean;
  next_run_at: string | null;
}

export interface Settings {
  proactive: boolean;
  brief_enabled: boolean;
  sources: Record<string, boolean>;
  quiet_start: string;
  quiet_end: string;
  brief_time: string;
  meeting_brief_minutes: number;
  max_interrupts_per_hour: number;
  digest_times: string[];
  language: "auto" | "zh" | "en" | "id";
}

export interface SourceStatus {
  last_synced_at: string | null;
  error: string | null;
}

export type StreamEvent =
  | { type: "text"; delta: string }
  | { type: "tool_start"; name: string }
  | { type: "tool_end"; name: string; ok: boolean }
  | { type: "cards"; cards: Card[] }
  | { type: "error"; message: string }
  | { type: "done" };

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// 后端的 detail 可能是字符串，也可能是校验错误列表（[{msg, loc}, ...]）：都转成能读的一句话
function errorText(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => (typeof d === "string" ? d : (d as { msg?: string })?.msg)).filter(Boolean);
    if (parts.length) return parts.join("；");
  }
  return t("请求失败 ({p0})", { p0: status });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { credentials: "same-origin", ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(response.status, errorText(body, response.status));
  }
  return response.json();
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export const api = {
  authConfig: () => request<{ dev_login: boolean }>("/auth/config"),
  me: () => request<User>("/auth/me"),
  devLogin: () => request<User>("/auth/dev-login", { method: "POST" }),
  logout: () => request("/auth/logout", { method: "POST" }),
  models: () => request<{ models: string[]; default: string | null }>("/models"),
  home: () =>
    request<{ conversation: Conversation; messages: ThreadMessage[]; status: HomeStatus }>("/home"),
  conversations: () => request<Conversation[]>("/conversations"),
  createConversation: () => request<Conversation>("/conversations", { method: "POST" }),
  deleteConversation: (id: string) => request(`/conversations/${id}`, { method: "DELETE" }),
  messages: (id: string) => request<ThreadMessage[]>(`/conversations/${id}/messages`),
  memories: () => request<Memory[]>("/memories"),
  deleteMemory: (id: number) => request(`/memories/${id}`, { method: "DELETE" }),
  tasks: () => request<Task[]>("/tasks"),
  deleteTask: (id: number) => request(`/tasks/${id}`, { method: "DELETE" }),
  automations: () => request<{ grants: AutomationGrant[]; history: AutomationRun[] }>("/automations"),
  revokeAutomation: (grant: AutomationGrant) =>
    request<{ message: string }>("/automations/revoke", json("POST", {
      source: grant.source, source_id: grant.source_id, kind: grant.kind, index: grant.index ?? null,
    })),
  decide: (id: number, decision: "confirm" | "cancel" | "grant" | "undo") =>
    request<{ message: string; status: Action["status"] }>(`/actions/${id}/${decision}`, { method: "POST" }),
  editDraft: (id: number, body: string) => request(`/actions/${id}`, json("PATCH", { body })),
  setReplyAll: (id: number, replyAll: boolean) => request(`/actions/${id}`, json("PATCH", { reply_all: replyAll })),
  draftReply: (signalId: number) =>
    request<{ action_id: number }>(`/signals/${signalId}/draft-reply`, { method: "POST" }),
  rsvp: (signalId: number, status: "accept" | "tentative" | "decline") =>
    request<{ message: string; status: Action["status"] }>(`/signals/${signalId}/rsvp`, json("POST", { status })),
  board: () => request<Board>("/board"),
  integrations: () => request<Integration[]>("/integrations"),
  createIntegration: (name: string, description: string | null) =>
    request<Integration>("/integrations", json("POST", { name, description })),
  rotateIntegration: (id: number) => request<Integration>(`/integrations/${id}/rotate`, { method: "POST" }),
  deleteIntegration: (id: number) => request(`/integrations/${id}`, { method: "DELETE" }),
  integrationEvents: (id: number) => request<IntegrationEvent[]>(`/integrations/${id}/events`),
  missions: () => request<{ missions: MissionData[]; grantable: Record<string, string> }>("/missions"),
  mission: (id: number) => request<MissionData>(`/missions/${id}`),
  setGrants: (id: number, grants: string[]) => request(`/missions/${id}/grants`, json("PUT", { grants })),
  answerMission: (id: number, text: string) => request(`/missions/${id}/answer`, json("POST", { text })),
  wakeMission: (id: number) => request(`/missions/${id}/wake`, { method: "POST" }),
  cancelMission: (id: number) => request(`/missions/${id}/cancel`, { method: "POST" }),
  decideApproval: (id: number, approve: boolean) =>
    request<{ message: string }>(`/items/${id}/approval`, json("POST", { approve })),
  itemCase: (id: number) => request<{ refs: CaseRef[] }>(`/items/${id}/case`),
  openCaseRef: (id: number, ref: string) => request<CaseContent>(`/items/${id}/case/open`, json("POST", { ref })),
  closeItem: (id: number, decision: "done" | "dismiss") => request(`/items/${id}/${decision}`, { method: "POST" }),
  settings: () => request<{ settings: Settings; sources: Record<string, SourceStatus> }>("/settings"),
  saveSettings: (settings: Settings) => request("/settings", json("PUT", settings)),
  notifyRules: () => request<NotifyRule[]>("/notify-rules"),
  updateRule: (id: number, level: AttentionLevel) => request(`/notify-rules/${id}`, json("PUT", { level })),
  decideRule: (id: number, decision: "accept" | "reject") => request(`/notify-rules/${id}/${decision}`, { method: "POST" }),
  deleteRule: (id: number) => request(`/notify-rules/${id}`, { method: "DELETE" }),
  quieter: (itemId: number, level: AttentionLevel = "brief") => request<{ message: string }>(`/items/${itemId}/quieter`, json("POST", { level })),
  syncNow: () => request("/sync", { method: "POST" }),
  briefNow: () => request("/brief", { method: "POST" }),
};

/** 发送一条消息并逐个回调服务端推来的事件（SSE over fetch）。 */
export async function sendMessage(
  conversationId: string,
  text: string,
  model: string | null,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const response = await fetch(`/api/conversations/${conversationId}/messages`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, model }),
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => null);
    throw new ApiError(response.status, errorText(body, response.status));
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      for (const line of frame.split("\n")) {
        if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)));
      }
    }
  }
}
