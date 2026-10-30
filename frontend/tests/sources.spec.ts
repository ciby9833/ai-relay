import { test, expect, type Page } from "@playwright/test";

const none = (provider: string, secret: string) => ({ provider, connected: false, status: "none", config: {}, secrets: { [secret]: false } });

async function mockApi(page: Page, feishuLinked: boolean) {
  const writes: { path: string; body: unknown }[] = [];
  let mailbox: Record<string, unknown> = none("imap", "password");
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "language", { configurable: true, get: () => "zh-CN" });
    Object.defineProperty(navigator, "languages", { configurable: true, get: () => ["zh-CN"] });
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const body = request.method() !== "GET" && request.method() !== "DELETE" ? request.postDataJSON() : null;
    if (body !== null) writes.push({ path, body });
    if (path === "/api/auth/me") return route.fulfill({ json: { id: "u1", name: "Sari", is_admin: false, email: "sari@co.test", avatar_url: null,
      role: "member", tenant: { id: "t1", name: "Co", slug: "co" }, workspaces: 1, feishu_linked: feishuLinked } });
    if (path === "/api/auth/config") return route.fulfill({ json: { dev_login: false } });
    if (path === "/api/home") return route.fulfill({ json: { conversation: { id: "home" }, messages: [], status: { source_errors: 0 } } });
    if (path === "/api/board") return route.fulfill({ json: { me: [], others: [], relay: [] } });
    if (path === "/api/meetings") return route.fulfill({ json: { upcoming: [], recent: [] } });
    if (path === "/api/progress") return route.fulfill({ json: { days: [], notes: [] } });
    if (path === "/api/settings") return route.fulfill({ json: { settings: { proactive: true, sources: {}, language: "auto", brief_enabled: true,
      brief_time: "08:30", quiet_start: "21:00", quiet_end: "07:00", meeting_brief_minutes: 30, digest_times: ["12:00"], max_interrupts_per_hour: 3 }, sources: {} } });
    if (path === "/api/notify-rules" || path === "/api/rules") return route.fulfill({ json: [] });
    if (path === "/api/connections") return route.fulfill({ json: { imap: mailbox, ics: none("ics", "url"), feishu: { linked: feishuLinked } } });
    if (path === "/api/connections/imap/preset") return route.fulfill({ json: { imap_host: "imap.gmail.com", imap_port: 993, smtp_host: "smtp.gmail.com", smtp_port: 465, smtp_security: "ssl" } });
    if (path === "/api/connections/imap" && request.method() === "PUT") {
      mailbox = { provider: "imap", connected: true, status: "unverified", config: { ...body, password: undefined }, secrets: { password: true } };
      return route.fulfill({ json: mailbox });
    }
    if (path === "/api/connections/imap/test") return route.fulfill({ json: { ...mailbox, status: "ok", note: "收信、发信服务器都能登录" } });
    return route.fulfill({ json: [] });
  });
  return writes;
}

test("a member without Feishu connects their own mailbox; Feishu-only sources are not offered", async ({ page }, testInfo) => {
  const writes = await mockApi(page, false);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "提醒设置" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("接入你自己的工作邮箱和日历")).toBeVisible();
  // 审批、考勤、私聊这些只有飞书才有的来源不出现
  await expect(dialog.getByText("审批", { exact: true })).toHaveCount(0);
  await expect(dialog.getByText("私聊里的待办")).toHaveCount(0);
  await dialog.getByLabel("邮箱地址").fill("sari@gmail.com");
  await dialog.getByLabel(/^密码/).click();  // 离开邮箱输入框：常见邮箱自动带出服务器
  await expect(dialog.getByText("服务器设置：imap.gmail.com")).toBeVisible();
  await dialog.getByLabel(/^密码/).fill("app-pass-123");
  await dialog.screenshot({ path: testInfo.outputPath("sources.png") });
  await dialog.getByRole("button", { name: "接入" }).first().click();
  await expect(dialog.getByText("收信、发信服务器都能登录")).toBeVisible();
  const saved = writes.find((w) => w.path === "/api/connections/imap")?.body as Record<string, unknown>;
  expect(saved).toMatchObject({ email: "sari@gmail.com", password: "app-pass-123", imap_host: "imap.gmail.com", imap_port: 993, smtp_port: 465 });
  // 保存后密码框清空，只显示“已填写”
  await expect(dialog.getByLabel(/^密码/)).toHaveValue("");
});

test("Feishu members still see every source and can optionally connect a non-Feishu mailbox", async ({ page }) => {
  await mockApi(page, true);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "提醒设置" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("你在用飞书的邮箱和日历")).toBeVisible();
  await expect(dialog.getByText("审批", { exact: true })).toBeVisible();
  await expect(dialog.getByText("私聊里的待办")).toBeVisible();
});
