import { test, expect, type Page } from "@playwright/test";

const now = new Date().toISOString();
const incoming = {
  id: 7, title: "整理 9 月运单明细", brief: "客户对账要用", deliverable: "运单明细表", acceptance: null, due_at: null,
  materials: [{ title: "对账模板", url: "https://docs.example/t" }], status: "requested", status_text: "等你回应", version: 1, role: "assignee",
  proposal: null, submission: null, requester: { id: "u2", name: "Ana" }, assignee: { id: "u1", name: "Budi" },
  actions: ["accept", "decline", "counter"], created_at: now, updated_at: now,
  log: [{ kind: "request", who: "Ana", note: null, at: now }],
};
const collabItem = {
  id: 40, kind: "collab", owner: "me", title: "整理 9 月运单明细", summary: "客户对账要用", next_step: "Ana 请你：运单明细表。接受、拒绝，或提出修改",
  recommendation: null, waiting_on: "Ana", url: null, open_url: null, importance: "normal", status: "open", resolution: null, due_at: null,
  remind_at: null, updated_at: now, count: 0, action: null, ask: "Ana 请你：运单明细表。接受、拒绝，或提出修改", source: null, detail: [],
  quick_approve: false, attention: "now", announced: true, quieter: false,
  collab: { delegation_id: 7, role: "assignee", collab_status: "requested", counterpart: "Ana" },
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
    const body = request.method() !== "GET" ? request.postDataJSON() : null;
    if (body !== null) writes.push({ path, body });
    if (path === "/api/auth/me") return route.fulfill({ json: { id: "u1", name: "Budi", is_admin: false, email: null, avatar_url: null,
      role: "member", tenant: { id: "t1", name: "J&T", slug: "jt" }, workspaces: 1 } });
    if (path === "/api/auth/config") return route.fulfill({ json: { dev_login: false } });
    if (path === "/api/home") return route.fulfill({ json: { conversation: { id: "home" }, messages: [], status: { source_errors: 0 } } });
    if (path === "/api/board") return route.fulfill({ json: { me: [collabItem], others: [], relay: [] } });
    if (path === "/api/meetings") return route.fulfill({ json: { upcoming: [], recent: [] } });
    if (path === "/api/progress") return route.fulfill({ json: { days: [], notes: [] } });
    if (path === "/api/collab/members") return route.fulfill({ json: [{ id: "u2", name: "Ana", email: "ana@jt.id" }, { id: "u3", name: "Cici", email: null }] });
    if (path === "/api/collab" && request.method() === "POST") {
      return route.fulfill({ json: { ...incoming, id: 8, title: body.title, role: "requester", actions: ["revise", "cancel"],
        requester: { id: "u1", name: "Budi" }, assignee: { id: "u3", name: "Cici" } } });
    }
    if (path === "/api/collab") return route.fulfill({ json: [incoming] });
    if (path === "/api/collab/7") return route.fulfill({ json: incoming });
    if (path === "/api/collab/8") return route.fulfill({ json: { ...incoming, id: 8, title: "盘点报表", role: "requester", actions: ["revise", "cancel"],
      requester: { id: "u1", name: "Budi" }, assignee: { id: "u3", name: "Cici" } } });
    if (path === "/api/collab/7/act") return route.fulfill({ json: { ...incoming, status: "declined", status_text: "已拒绝", actions: [], version: 2 } });
    if (path.startsWith("/api/items/") && path.endsWith("/case")) return route.fulfill({ json: { refs: [], summary: null } });
    return route.fulfill({ json: [] });
  });
  return writes;
}

test("ask a colleague: only workspace members, no invented deadline, only what you write is shared", async ({ page }, testInfo) => {
  const writes = await mockApi(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "和同事协作" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("轮到你（1）")).toBeVisible();
  await dialog.getByRole("button", { name: "+ 请同事帮忙" }).click();
  await dialog.getByRole("combobox", { name: "请谁" }).selectOption("u3");
  await dialog.getByLabel("标题", { exact: true }).fill("盘点报表");
  await dialog.getByLabel("要做什么（背景、为什么）").fill("21 号的盘点");
  await dialog.getByLabel("交付什么", { exact: true }).fill("盘点表");
  await dialog.getByLabel(/共享给对方的材料/).fill("模板 https://docs.example/m");
  await dialog.screenshot({ path: testInfo.outputPath("collab-new.png") });
  await dialog.getByRole("button", { name: "发出请求" }).click();
  await expect(dialog.getByRole("heading", { name: "盘点报表" })).toBeVisible();
  expect(writes.find((w) => w.path === "/api/collab")?.body).toEqual({
    assignee_id: "u3", title: "盘点报表", brief: "21 号的盘点", deliverable: "盘点表", acceptance: null, due_at: null,
    materials: [{ title: "模板", url: "https://docs.example/m" }],
  });
});

test("a request in the to-do list opens the collaboration; declining needs a reason and carries the version", async ({ page }, testInfo) => {
  const writes = await mockApi(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: /待处理/ }).click();
  await page.getByRole("button", { name: /整理 9 月运单明细/ }).first().click();
  // 协作还没结束：“已处理 / 不用跟了”不出现，要到协作里处理
  await expect(page.getByRole("button", { name: "已处理" })).toHaveCount(0);
  await page.getByRole("button", { name: "打开协作" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Ana 请你")).toBeVisible();
  await expect(dialog.getByText("未约定")).toBeVisible();
  await expect(dialog.getByRole("link", { name: "对账模板" })).toHaveAttribute("href", "https://docs.example/t");
  await dialog.getByRole("button", { name: "拒绝" }).click();
  await dialog.getByLabel("拒绝的理由").fill("这周在外地");
  await dialog.screenshot({ path: testInfo.outputPath("collab-decline.png") });
  await dialog.getByRole("button", { name: "确定" }).click();
  await expect(dialog.getByText("这份协作已经结束。")).toBeVisible();
  expect(writes.find((w) => w.path === "/api/collab/7/act")?.body).toEqual({ action: "decline", version: 1, note: "这周在外地" });
});
