import { test, expect, type Page } from "@playwright/test";

const me = (extra: Record<string, unknown> = {}) => ({
  id: "u1", name: "Xavier", is_admin: true, email: "xavier@jt.id", avatar_url: null, role: "owner",
  tenant: { id: "t1", name: "J&T Cargo Indonesia", slug: "jt" }, has_password: false, login_email: null, feishu_linked: true, workspaces: 1, ...extra,
});

async function zh(page: Page) {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "language", { configurable: true, get: () => "zh-CN" });
    Object.defineProperty(navigator, "languages", { configurable: true, get: () => ["zh-CN"] });
  });
}

async function mockApi(page: Page, signedIn: boolean, user = me()) {
  const writes: { path: string; body: unknown }[] = [];
  let loggedIn = signedIn;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const body = request.method() !== "GET" ? request.postDataJSON() : null;
    if (body !== null) writes.push({ path, body });
    if (path === "/api/auth/config") return route.fulfill({ json: { dev_login: false, signup: false, feishu: true } });
    if (path === "/api/auth/me") return loggedIn ? route.fulfill({ json: user }) : route.fulfill({ status: 401, json: { detail: "未登录" } });
    if (path === "/api/auth/login") {
      if (!body.tenant_id) return route.fulfill({ json: { choose: [{ tenant_id: "t1", name: "J&T Cargo Indonesia", slug: "jt" }, { tenant_id: "t2", name: "Demo", slug: "demo" }] } });
      loggedIn = true;
      return route.fulfill({ json: user });
    }
    if (path === "/api/auth/invitations/tok123") return route.fulfill({ json: { workspace: "J&T Cargo Indonesia", email: "budi@jt.id", role: "member", has_account: false } });
    if (path === "/api/auth/invitations/tok123/accept") return route.fulfill({ json: me({ id: "u9", name: "Budi", role: "member", is_admin: false }) });
    if (path === "/api/auth/workspaces") return route.fulfill({ json: [{ tenant_id: "t1", name: "J&T Cargo Indonesia", slug: "jt", current: true }] });
    if (path === "/api/tenant/members") return route.fulfill({ json: [
      { id: "u1", name: "Xavier", email: "xavier@jt.id", role: "owner", status: "active", feishu: true, password: false, last_login_at: null, me: true },
      { id: "u2", name: "Kange", email: "kange@jt.id", role: "member", status: "active", feishu: true, password: true, last_login_at: null, me: false }] });
    if (path === "/api/tenant/invitations" && request.method() === "POST") return route.fulfill({ json: { link: "https://relay.example/invite/abc" } });
    if (path === "/api/tenant/invitations") return route.fulfill({ json: [] });
    if (path === "/api/tenant/connections/feishu") {
      return route.fulfill({ json: { provider: "feishu", configured: true, status: "ok", config: { app_id: "cli_123", tenant_key: "tk" },
        secrets: { app_secret: true, verification_token: true, encrypt_key: false }, redirect_uri: "https://relay.example/api/auth/feishu/callback" } });
    }
    if (path.startsWith("/api/tenant/members/")) return route.fulfill({ json: { role: "admin", status: "active" } });
    if (path === "/api/home") return route.fulfill({ json: { conversation: { id: "home" }, messages: [], status: { source_errors: 0 } } });
    if (path === "/api/board") return route.fulfill({ json: { me: [], others: [], relay: [] } });
    if (path === "/api/meetings") return route.fulfill({ json: { upcoming: [], recent: [] } });
    if (path === "/api/progress") return route.fulfill({ json: { days: [], notes: [] } });
    return route.fulfill({ json: [] });
  });
  return writes;
}

test("email sign-in lets you pick a workspace; Feishu sign-in stays available", async ({ page }, testInfo) => {
  await zh(page);
  const writes = await mockApi(page, false);
  await page.goto("/");
  await expect(page.getByRole("link", { name: "使用飞书登录" })).toBeVisible();  // 原来的飞书登录照常可用
  await page.getByLabel("邮箱").fill("xavier@jt.id");
  await page.getByLabel("密码").fill("correct horse");
  await page.screenshot({ path: testInfo.outputPath("login.png") });
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByText("选择要进入的工作区")).toBeVisible();
  await page.getByRole("button", { name: "J&T Cargo Indonesia" }).click();
  expect(writes.at(-1)).toEqual({ path: "/api/auth/login", body: { email: "xavier@jt.id", password: "correct horse", tenant_id: "t1" } });
  await expect(page.locator(".brand-workspace")).toHaveText("J&T Cargo Indonesia");
});

test("an invitation link sets a password and joins the workspace", async ({ page }) => {
  await zh(page);
  const writes = await mockApi(page, false);
  await page.goto("/invite/tok123");
  await expect(page.getByText("你被邀请加入工作区「J&T Cargo Indonesia」")).toBeVisible();
  await page.getByLabel("你的名字").fill("Budi");
  await page.getByLabel("设置登录密码（至少 8 位）").fill("a-strong-pass");
  await page.getByRole("button", { name: "加入工作区" }).click();
  await expect.poll(() => writes.find((w) => w.path === "/api/auth/invitations/tok123/accept")?.body).toEqual({ password: "a-strong-pass", name: "Budi" });
});

test("workspace admins manage members, invites and the Feishu connection without ever seeing secrets", async ({ page }, testInfo) => {
  await zh(page);
  const writes = await mockApi(page, true);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "工作区设置" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Kange", { exact: true })).toBeVisible();
  await dialog.getByRole("combobox", { name: "角色" }).first().selectOption("admin");
  expect(writes).toContainEqual({ path: "/api/tenant/members/u2", body: { role: "admin" } });
  await dialog.getByRole("textbox", { name: "邮箱", exact: true }).fill("budi@jt.id");
  await dialog.getByRole("button", { name: "生成邀请链接" }).click();
  await expect(dialog.getByRole("textbox", { name: "邀请链接" })).toHaveValue("https://relay.example/invite/abc");
  // 飞书：App ID 回显；密钥只显示“已填写”，不回显原文；留空保存表示不改
  await expect(dialog.getByLabel("App ID")).toHaveValue("cli_123");
  await expect(dialog.getByLabel("App Secret")).toHaveValue("");
  await expect(dialog.getByLabel("App Secret")).toHaveAttribute("placeholder", "已填写（留空表示不改）");
  await expect(dialog.getByText("已连通")).toBeVisible();
  await dialog.screenshot({ path: testInfo.outputPath("workspace-admin.png") });
  await dialog.getByRole("button", { name: "保存" }).last().click();
  expect(writes.find((w) => w.path === "/api/tenant/connections/feishu")?.body).toEqual({ app_id: "cli_123", tenant_key: "tk" });
});

test("ordinary members only see their own account settings", async ({ page }) => {
  await zh(page);
  await mockApi(page, true, me({ role: "member", is_admin: false }));
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "账号与工作区" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("设置邮箱登录")).toBeVisible();
  await expect(dialog.getByText("飞书接入")).toHaveCount(0);
  await expect(dialog.getByText("邀请成员")).toHaveCount(0);
});
