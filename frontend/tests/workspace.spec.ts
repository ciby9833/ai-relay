import { test, expect, type Page } from "@playwright/test";

const now = new Date();
const later = new Date(now.getTime() + 3 * 3600_000).toISOString();
const item = (id: number, title: string, extra: Record<string, unknown> = {}) => ({
  id, kind: "request", owner: "me", title, summary: "「哥， 这个可以发给我吗？」", next_step: "完成后在私聊回复对方",
  recommendation: "Callesya 说要 21 号的盘点报表，今天下班前要", waiting_on: null, url: "https://applink.feishu.cn/client/chat/open?openChatId=oc_1",
  open_url: null, importance: "normal", status: "open", resolution: null, due_at: null, remind_at: null, updated_at: now.toISOString(),
  count: 1, action: null, ask: "把盘点报表发给 Callesya", source: null, detail: [], quick_approve: false, attention: "batch", announced: true, quieter: true,
  ...extra,
});
const board = {
  me: [item(1, "Callesya 让你：把 21 号盘点报表发给她", { due_at: later }), item(2, "看一下 客户A 的周报"),
    item(11, "Ricky：新功能申请", { kind: "approval", ask: "审批" }), item(12, "Gray：新功能申请", { kind: "approval", ask: "审批" })],
  others: [item(3, "等 Lavianna：吉利的沟通进展", { owner: "others", ask: "等 Lavianna 答复" })],
  relay: [],
};
const meetings = {
  upcoming: [{
    id: 9, title: "Medan 运营周会", start: later, all_day: false, location: "3F", meeting_url: "https://vc.feishu.cn/j/1", url: null,
    rsvp: "needs_action", organizer: "Sari", attendees: ["Budi"], minutes: null, minutes_missing: false, invitation_item_id: null,
    end: new Date(new Date(later).getTime() + 3600_000).toISOString(), prep: { text: "**为什么开这个会** 复盘 Medan 延误【议程】\n\n**还没解决的问题** Budi 的延误原因还没查完【行动项】", generated_at: now.toISOString(), worth_pushing: true,
      sources: [{ kind: "agenda", title: "会议描述 / 议程", url: null, why: "写在日程里的" }, { kind: "actions", title: "这个系列以前的会留下的行动项", url: null, why: "同一个系列的会" }] },
    actions: [{ id: 5, title: "等 Budi：查延误原因", owner: "others", status: "open", resolution: null }],
  }],
  recent: [{
    id: 8, title: "1:1", start: now.toISOString(), end: now.toISOString(), all_day: false, location: null, meeting_url: null, url: null, rsvp: "accept",
    organizer: null, attendees: [], prep: null, minutes: null, minutes_missing: true, actions: [], invitation_item_id: null,
  }],
};

async function mockApi(page: Page) {
  const writes: { path: string; body: unknown }[] = [];
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "language", { configurable: true, get: () => "zh-CN" });
    Object.defineProperty(navigator, "languages", { configurable: true, get: () => ["zh-CN"] });
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== "GET") writes.push({ path, body: request.postDataJSON() });
    if (path === "/api/auth/me") return route.fulfill({ json: { id: "test", name: "Ellis", is_admin: false, email: null, avatar_url: null } });
    if (path === "/api/auth/config") return route.fulfill({ json: { dev_login: false } });
    if (path === "/api/home") return route.fulfill({ json: { conversation: { id: "home" }, status: { source_errors: 0, last_synced_at: now.toISOString() }, messages: [
      { id: 1, role: "event", notice: "interrupt" },
      { id: 2, role: "assistant", text: "", notice: "interrupt", proactive: true, created_at: now.toISOString(), cards: [{ kind: "item", item_id: 1 }] },
      { id: 3, role: "user", text: "今天还有什么？" },
      { id: 4, role: "assistant", text: "还有一个会。", created_at: now.toISOString(), cards: [] },
    ] } });
    if (path === "/api/board") return route.fulfill({ json: board });
    if (path === "/api/meetings") return route.fulfill({ json: meetings });
    if (path === "/api/progress") return route.fulfill({ json: { days: [{ date: now.toISOString().slice(0, 10), items: [
      { id: 7, title: "Hendri 的补卡申请", kind: "approval", owner: "me", status: "done", resolution: "审批已处理", closed_at: now.toISOString() }] }], notes: [] } });
    if (path === "/api/models") return route.fulfill({ json: { models: ["test:model"], default: "test:model" } });
    if (path === "/api/conversations") return route.fulfill({ json: [] });
    if (path.startsWith("/api/items/") && path.endsWith("/case")) return route.fulfill({ json: { refs: [], summary: null } });
    if (path === "/api/items/1/feedback") return route.fulfill({ json: { ok: true, message: "提醒前你就处理了" } });
    if (path === "/api/items/1/undo") return route.fulfill({ json: { ok: true, message: "已撤销，这件事回到待处理" } });
    return route.fulfill({ json: [] });
  });
  return writes;
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

test("desktop: three entries above the chat open one inspector: list → detail → source, ask with a removable tag, undo", async ({ page }, testInfo) => {
  const writes = await mockApi(page);
  await page.setViewportSize({ width: 1400, height: 860 });
  await page.goto("/");
  const dock = page.getByRole("region", { name: "今天的工作" });
  await expect(dock.getByRole("button", { name: /待处理/ })).toContainText("需要你 4 · 在等对方 1");
  const inspector = page.getByRole("complementary", { name: "详情栏" });
  await expect(inspector).toBeVisible();  // 宽屏默认打开，和对话并排
  await expect(inspector.locator(".ws-group").nth(0)).toContainText("Callesya 让你");  // 今天到期：现在要处理
  // 同一种审批放在一起看，每张单独处理
  await inspector.getByRole("button", { name: /新功能申请/ }).click();
  await expect(inspector.getByRole("button", { name: /Ricky：新功能申请/ })).toBeVisible();
  await page.keyboard.press("Escape");  // 逐级返回
  await expect(inspector.getByRole("button", { name: /Callesya 让你/ })).toBeVisible();

  // 对话里的提醒只留一行；点“看这几件”直接打开那件事
  await page.getByRole("button", { name: "看这几件" }).click();
  await expect(inspector.getByText("Callesya 说要 21 号的盘点报表，今天下班前要")).toBeVisible();
  await inspector.getByRole("button", { name: "已处理" }).click();
  await expect(inspector.getByRole("group", { name: "什么时候处理的？" })).toBeVisible();  // 提醒过：问是提醒前还是提醒后
  await inspector.getByRole("button", { name: "提醒前就处理了" }).click();
  expect(writes).toContainEqual({ path: "/api/items/1/feedback", body: { outcome: "handled_before" } });
  await expect(inspector.getByRole("status")).toContainText("提醒前你就处理了");
  await inspector.getByRole("button", { name: "撤销" }).click();
  expect(writes.map((w) => w.path)).toContain("/api/items/1/undo");

  // 会议：列表 → 详情（会前简报 / 相关材料 / 会后行动）→ 材料 → 返回 → 带着会议问 Relay
  await dock.getByRole("button", { name: /会议/ }).click();
  await inspector.getByRole("button", { name: /Medan 运营周会/ }).click();
  await expect(inspector.getByText("Budi 的延误原因还没查完【行动项】")).toBeVisible();
  await inspector.getByRole("tab", { name: /相关材料/ }).click();
  await inspector.getByRole("button", { name: /这个系列以前的会留下的行动项/ }).click();
  await expect(inspector.getByText("为什么相关：同一个系列的会")).toBeVisible();
  await inspector.getByRole("button", { name: "返回" }).click();
  await page.screenshot({ path: testInfo.outputPath("workspace-desktop.png") });
  await inspector.getByRole("button", { name: "带着这场会议问 Relay" }).click();
  const composer = page.getByRole("textbox", { name: /问 Relay/ });
  await expect(page.locator(".context-chip")).toContainText("会议：Medan 运营周会");
  await expect(composer).toBeFocused();
  await expect(composer).toHaveValue("");  // 不自动发送，也不改他的草稿
  await page.locator(".context-chip").getByRole("button", { name: "移除" }).click();
  await expect(page.locator(".context-chip")).toHaveCount(0);

  // 进展：有结果的事
  await dock.getByRole("button", { name: /进展/ }).click();
  await expect(inspector.getByText("Hendri 的补卡申请")).toBeVisible();
});

test("mobile: entries stay above the chat; the inspector is full screen and asking returns to the chat", async ({ page }, testInfo) => {
  await mockApi(page);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  const inspector = page.getByRole("complementary", { name: "详情栏" });
  await expect(inspector).toBeHidden();
  await expect(page.locator(".app-card")).toHaveCount(0);  // 提醒的卡片不再堆在对话里
  await noOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("chat-mobile.png") });
  await page.getByRole("button", { name: /会议/ }).first().click();
  await expect(inspector).toBeVisible();
  await inspector.getByRole("button", { name: /Medan 运营周会/ }).click();
  await expect(inspector.getByText("没有找到", { exact: false })).toHaveCount(0);
  await noOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("meeting-mobile.png") });
  await inspector.getByRole("button", { name: "带着这场会议问 Relay" }).click();
  await expect(inspector).toBeHidden();  // 回到对话
  await expect(page.locator(".context-chip")).toContainText("Medan 运营周会");
  await page.getByRole("textbox", { name: /问 Relay/ }).fill("我需要准备什么？");
  await page.keyboard.press("Enter");
  await expect(page.getByText(/关于会议《Medan 运营周会》/)).toBeVisible();  // 发送时附上会议
});
