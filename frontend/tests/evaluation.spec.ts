import { test, expect, type Page } from "@playwright/test";

const now = new Date().toISOString();
const commitment = { key: "1:me:看盘点逻辑", matter_id: 1, matter: "盘点逻辑", summary: "Callesya 请他看盘点逻辑", owner: "me", party: "Callesya",
  what: "看一下盘点逻辑", due: null, status: "open", evidence: "Callesya @他请他看", last_at: now, materials: [], feedback: { label: "up", reason: null, note: null } };

async function mockApi(page: Page, initial: Record<string, unknown>) {
  let eval_ = { enrolled: false, status: "not_started", progress: null, processed_until: null, enrolled_at: null, days: 2, ledger: [], current: [], feedback: [], ...initial };
  const enrolls: unknown[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/auth/me") return route.fulfill({ json: { id: "test", name: "Ellis", is_admin: true, email: null, avatar_url: null } });
    if (path === "/api/auth/config") return route.fulfill({ json: { dev_login: false } });
    if (path === "/api/home") return route.fulfill({ json: { conversation: { id: "home" }, messages: [], status: { source_errors: 0, last_synced_at: now } } });
    if (path === "/api/board") return route.fulfill({ json: { me: [], others: [], relay: [] } });
    if (path === "/api/models") return route.fulfill({ json: { models: ["test:model"], default: "test:model" } });
    if (path === "/api/conversations") return route.fulfill({ json: [] });
    if (path === "/api/home") return route.fulfill({ json: { conversation: { id: "home" }, messages: [], status: { source_errors: 0, last_synced_at: now } } });
    if (path === "/api/eval/enroll") {
      enrolls.push(request.postDataJSON());
      await new Promise((r) => setTimeout(r, 300));
      eval_ = { ...eval_, enrolled: true, status: "queued", progress: 0, enrolled_at: now, days: (request.postDataJSON() as { days: number }).days };
      return route.fulfill({ json: { enrolled: true, since: now } });
    }
    if (path === "/api/eval") return route.fulfill({ json: eval_ });
    if (path === "/api/meetings") return route.fulfill({ json: { upcoming: [], recent: [] } });
    if (path === "/api/progress") return route.fulfill({ json: { days: [], notes: [] } });
    return route.fulfill({ json: [] });
  });
  return enrolls;
}

async function openEval(page: Page) {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "language", { configurable: true, get: () => "zh-CN" });
    Object.defineProperty(navigator, "languages", { configurable: true, get: () => ["zh-CN"] });
  });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await page.locator(".mobile-bar button").click();
  await page.getByRole("button", { name: /新旧链路对比/ }).click();
}

test("evaluation starts once with a fixed range", async ({ page }) => {
  const enrolls = await mockApi(page, {});
  await openEval(page);
  await page.getByRole("radio", { name: "最近 1 天" }).click();
  const start = page.getByRole("button", { name: "开始", exact: true });
  await start.click();
  await expect(page.getByRole("button", { name: "正在开始…" })).toBeDisabled();  // 不能连点
  await expect(page.getByText("整理范围：最近 1 天")).toBeVisible();
  await expect(page.getByRole("radio")).toHaveCount(0);  // 开始后不能再改范围
  await expect(page.getByText("排队中，马上开始…")).toBeVisible();
  expect(enrolls).toEqual([{ days: 1 }]);
});

test("a running evaluation shows progress and what is already ready", async ({ page }, testInfo) => {
  await mockApi(page, { enrolled: true, status: "running", progress: 0.4, enrolled_at: now, days: 2, ledger: [commitment] });
  await openEval(page);
  await expect(page.getByText("正在整理 40%，已整理出的结果可以先看")).toBeVisible();
  await expect(page.getByText("看一下盘点逻辑")).toBeVisible();
  await expect(page.getByRole("radio")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.waitForTimeout(500);  // 等侧栏收起
  await page.screenshot({ path: testInfo.outputPath("eval-running.png"), fullPage: true });
});
