import { test, expect, type Page } from "@playwright/test";

const overview = {
  departments: [
    { id: "d1", name: "运营中心", parent_id: null, lead_id: "u1", source: "feishu", locks: [] },
    { id: "d2", name: "Medan 站", parent_id: "d1", lead_id: null, source: "manual", locks: [] },
  ],
  members: [
    { id: "u1", name: "Ana", email: "ana@jt.id", title: "运营总监", responsibilities: null, department_id: "d1", manager_id: null, role: "owner", status: "active", feishu: true, locks: [] },
    { id: "u2", name: "Budi", email: "budi@jt.id", title: null, responsibilities: null, department_id: null, manager_id: null, role: "member", status: "active", feishu: true, locks: [] },
  ],
  teams: [{ id: "t1", name: "Medan 项目组", lead_id: "u1", member_ids: ["u2"] }],
  me: "u1", can_edit: true,
};

async function mockApi(page: Page, user: Record<string, unknown>) {
  const writes: { path: string; method: string; body: unknown }[] = [];
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "language", { configurable: true, get: () => "zh-CN" });
    Object.defineProperty(navigator, "languages", { configurable: true, get: () => ["zh-CN"] });
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const body = ["POST", "PATCH", "PUT"].includes(request.method()) ? request.postDataJSON() : null;
    if (request.method() !== "GET") writes.push({ path, method: request.method(), body });
    if (path === "/api/auth/me") return route.fulfill({ json: user });
    if (path === "/api/auth/config") return route.fulfill({ json: { dev_login: false } });
    if (path === "/api/org") return route.fulfill({ json: { ...overview, me: user.id, can_edit: user.is_admin } });
    if (path === "/api/org/me") return route.fulfill({ json: { department: "运营中心 / Medan 站", manager: "Ana", title: null, responsibilities: null } });
    if (path === "/api/org/teams/t1/summary") return route.fulfill({ json: [{ id: "u2", name: "Budi", open: 3, overdue: 1, waiting: 2 }] });
    if (path === "/api/org/sync-feishu") return route.fulfill({ json: { departments: 2, members: 2, skipped_locked: 0 } });
    if (path.startsWith("/api/org/")) return route.fulfill({ json: { ok: true } });
    if (path === "/api/auth/workspaces" && request.method() === "POST") return route.fulfill({ json: user });
    if (path === "/api/tenant/connections/feishu") return route.fulfill({ json: { provider: "feishu", configured: true, status: "ok", config: {}, secrets: {}, managed: true } });
    if (path === "/api/home") return route.fulfill({ json: { conversation: { id: "home" }, messages: [], status: { source_errors: 0 } } });
    if (path === "/api/board") return route.fulfill({ json: { me: [], others: [], relay: [] } });
    if (path === "/api/meetings") return route.fulfill({ json: { upcoming: [], recent: [] } });
    if (path === "/api/progress") return route.fulfill({ json: { days: [], notes: [] } });
    return route.fulfill({ json: [] });
  });
  return writes;
}

const admin = { id: "u1", name: "Ana", is_admin: true, role: "owner", email: "ana@jt.id", avatar_url: null,
  tenant: { id: "t", name: "J&T", slug: "jt" }, has_password: true, login_email: "ana@jt.id", feishu_linked: true, workspaces: 1 };
const member = { ...admin, id: "u2", name: "Budi", is_admin: false, role: "member", login_email: "budi@jt.id" };

test("admins build the organisation: departments, managers, teams, Feishu sync", async ({ page }, testInfo) => {
  const writes = await mockApi(page, admin);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "工作区设置" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(".ws-members b", { hasText: "运营中心 / Medan 站" })).toBeVisible();
  // Budi 的部门和上级
  const budi = dialog.locator(".org-members li").filter({ has: page.locator("b", { hasText: /^Budi$/ }) });
  await budi.getByRole("combobox", { name: "部门", exact: true }).selectOption("d2");
  await budi.getByRole("combobox", { name: "直属上级", exact: true }).selectOption("u1");
  expect(writes).toContainEqual({ path: "/api/org/members/u2", method: "PATCH", body: { department_id: "d2" } });
  expect(writes).toContainEqual({ path: "/api/org/members/u2", method: "PATCH", body: { manager_id: "u1" } });
  // 新部门挂在运营中心下面
  await dialog.getByRole("textbox", { name: "部门名称" }).fill("Jakarta 站");
  await dialog.getByRole("combobox", { name: "上级部门" }).selectOption("d1");
  await dialog.getByRole("button", { name: "添加部门" }).click();
  await expect.poll(() => writes.find((w) => w.path === "/api/org/departments")?.body).toEqual({ name: "Jakarta 站", parent_id: "d1" });
  // 从飞书同步
  await dialog.getByRole("button", { name: "从飞书通讯录同步" }).click();
  await expect(dialog.getByText("已从飞书同步 2 个部门、2 位成员；手工改过的没有覆盖。")).toBeVisible();
  // 团队汇总只有数字
  await dialog.getByRole("button", { name: "看汇总" }).click();
  await expect(dialog.locator(".team-summary")).toContainText("Budi");
  await dialog.screenshot({ path: testInfo.outputPath("org-admin.png") });
});

test("members edit only their own title and responsibilities, and can start a new workspace", async ({ page }) => {
  const writes = await mockApi(page, member);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "账号与工作区" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("部门：运营中心 / Medan 站 · 直属上级：Ana")).toBeVisible();
  await expect(dialog.getByText("成员的部门与上级")).toHaveCount(0);  // 不是管理员：看不到组织管理
  await dialog.getByLabel("岗位").fill("Medan 站长");
  await dialog.getByLabel(/负责什么/).fill("Medan 线路");
  await dialog.getByRole("button", { name: "保存" }).first().click();
  await expect.poll(() => writes.find((w) => w.path === "/api/org/members/u2")?.body).toEqual({ title: "Medan 站长", responsibilities: "Medan 线路" });
  await dialog.getByRole("button", { name: "+ 新建一个工作区" }).click();
  await dialog.getByRole("textbox", { name: "工作区名称（公司或团队）" }).fill("Budi 的小组");
  await dialog.getByRole("button", { name: "创建" }).click();
  await expect.poll(() => writes.find((w) => w.path === "/api/auth/workspaces")?.body).toEqual({ name: "Budi 的小组" });
});
