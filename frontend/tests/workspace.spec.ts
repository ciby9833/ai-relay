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
  me: [item(1, "Callesya 让你：把 21 号盘点报表发给她", { due_at: later }), item(2, "看一下 客户A 的周报")],
  others: [item(3, "等 Lavianna：吉利的沟通进展", { owner: "others", ask: "等 Lavianna 答复" })],
  relay: [],
};
const meetings = {
  upcoming: [{
    id: 9, title: "Medan 运营周会", start: later, end: null, all_day: false, location: "3F", meeting_url: "https://vc.feishu.cn/j/1", url: null,
    rsvp: "needs_action", organizer: "Sari", attendees: ["Budi"], minutes: null, minutes_missing: false, invitation_item_id: null,
    prep: { text: "**为什么开这个会** 复盘 Medan 延误【议程】\n\n**还没解决的问题** Budi 的延误原因还没查完【行动项】", generated_at: now.toISOString(), worth_pushing: true,
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
    return route.fulfill({ json: [] });
  });
  return writes;
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

test("to-do is the home page; items open into details with feedback and ask-Relay", async ({ page }, testInfo) => {
  const writes = await mockApi(page);
  await page.setViewportSize({ width: 1280, height: 820 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "待处理" })).toBeVisible();
  // 今天到期的在“现在要处理”，其余在“待处理”，等别人的单独一组
  const groups = page.locator(".ws-group-head");
  await expect(groups.nth(0)).toContainText("现在要处理");
  await expect(page.locator(".ws-group").nth(0)).toContainText("Callesya 让你");
  await expect(page.locator(".ws-group").nth(2)).toContainText("等 Lavianna");
  await page.getByRole("button", { name: /Callesya 让你/ }).click();
  await expect(page.getByText("Callesya 说要 21 号的盘点报表，今天下班前要")).toBeVisible();  // 为什么跟、依据
  await page.getByRole("button", { name: "不用跟了" }).click();
  await expect(page.getByRole("group", { name: "为什么不用跟了？" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("inbox-desktop.png") });
  await page.getByRole("button", { name: "提醒前就处理了" }).click();
  expect(writes).toContainEqual({ path: "/api/items/1/feedback", body: { outcome: "handled_before" } });

  await page.getByRole("button", { name: /看一下 客户A/ }).click();
  await page.getByRole("button", { name: "问 Relay" }).click();
  await expect(page.getByRole("textbox")).toHaveValue("关于 #2《看一下 客户A 的周报》：");  // 带着这件事进对话，不用重新解释
});

test("mobile: bottom tabs, list then full-screen detail, meetings with evidence, chat keeps notices to one line", async ({ page }, testInfo) => {
  await mockApi(page);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await expect(page.locator(".tabbar")).toBeVisible();
  await noOverflow(page);
  await page.getByRole("button", { name: /Callesya 让你/ }).click();
  await expect(page.locator(".ws-list")).toBeHidden();
  await expect(page.getByRole("button", { name: "返回列表" })).toBeVisible();
  await noOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("inbox-detail-mobile.png"), fullPage: true });
  await page.getByRole("button", { name: "返回列表" }).click();
  await expect(page.locator(".ws-list")).toBeVisible();

  await page.locator(".tabbar button").nth(1).click();
  await expect(page.getByRole("heading", { name: "会议" })).toBeVisible();
  await expect(page.getByText("未回复邀请")).toBeVisible();
  await expect(page.getByText("Budi 的延误原因还没查完【行动项】")).toBeVisible();
  await page.getByText("依据（2 份材料）").click();
  await expect(page.getByText("同一个系列的会").first()).toBeVisible();
  await expect(page.getByText("没有找到这次会的纪要，没有提取行动项。")).toBeVisible();  // 找不到就直说
  await noOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("meetings-mobile.png"), fullPage: true });

  await page.locator(".tabbar button").nth(2).click();
  await expect(page.getByText("Hendri 的补卡申请")).toBeVisible();

  await page.locator(".tabbar button").nth(3).click();
  await expect(page.getByText("Relay 提醒了你 1 件事")).toBeVisible();
  await expect(page.getByText("还有一个会。")).toBeVisible();
  await expect(page.locator(".app-card")).toHaveCount(0);  // 提醒的卡片不再堆在对话里
  await page.getByRole("button", { name: "去待处理" }).click();
  await expect(page.getByRole("heading", { name: "待处理" })).toBeVisible();
});
