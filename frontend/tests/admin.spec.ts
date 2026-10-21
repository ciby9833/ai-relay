import { test, expect, type Page } from "@playwright/test";
const rate = (n: number, d: number) => ({ numerator: n, denominator: d, rate: d ? n / d : null });
const days = Object.fromEntries(Array.from({ length: 7 }, (_, i) => [`2026-10-${15 + i}`, { pushes: i === 1 ? 2 : 0, interrupt: 0, digest: i === 1 ? 1 : 0, brief: i === 1 ? 1 : 0, meeting: 0, mission: 0, other: 0, items: 3, handled: 1 }]));
const rule = { spreadsheet_token: "sheetToken", sheet_id: "sheetId", cell: "B2", scope: "A 网点当前异常件数", operator: "decrease", target: null };
const criterion = { id: 1, text: "A 网点异常件数下降", requirement: "business", status: "met", evidence: "A 网点：回读 12；decrease 20", ref: null, rule, outcome: { ok: true, detail: "A 网点：回读 12；decrease 20", observation: { value: "12", at: "2026-10-20T00:00:00Z" } }, baseline: { value: "20", at: "2026-10-15T00:00:00Z" } };
const closure = { id: 1, title: "跟进 A 网点", user: "Hendri", instruction: "让 A 网点异常件数下降", result: "异常件 20 → 12", closed_at: "2026-10-20T00:00:00Z", criteria: [criterion] };
async function setup(page: Page, admin = true, failOnce = false, language = "zh") {
  const requests: string[] = [], writes: unknown[] = [];
  let review: null | { verdict: string; reason: string; at: string } = null, shouldFail = failOnce;
  await page.addInitScript(language => localStorage.setItem("relay.ui-language", language), language);
  await page.route("**/api/**", route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    requests.push(path + url.search);
    if (path === "/api/auth/me") return route.fulfill({ json: { id: "u", name: "Ellis", is_admin: admin } });
    if (path === "/api/conversations") return route.fulfill({ json: [] });
    if (path === "/api/home") return route.fulfill({ json: { conversation: { id: "home" }, messages: [], status: { source_errors: 0 } } });
    if (path === "/api/board") return route.fulfill({ json: { me: [], others: [], relay: [] } });
    if (path === "/api/models") return route.fulfill({ json: { models: [] } });
    if (path === "/api/insights/notifications") return route.fulfill({ json: [{ user_id: "h", user: "Hendri", timezone: "Asia/Jakarta", days, observed_days: 7, pushes_per_day: url.searchParams.get("offset") === "0" ? 0.29 : 4 }] });
    if (path === "/api/insights/quality") {
      if (shouldFail) { return route.fulfill({ status: 503, json: { detail: "暂时不可用" } }); }
      return route.fulfill({ json: { start: "2026-10-15T00:00:00Z", end: "2026-10-22T00:00:00Z", coverage_start: "2026-10-15T00:00:00Z", false_closure: review ? rate(1, 1) : rate(0, 0), review_coverage: review ? rate(1, 1) : rate(0, 1), completion_failure: rate(1, 4), verification_failure: rate(1, 10), verification_unknown: 2, human_takeover: rate(1, 5), closed_total: 1, closures: [{ ...closure, review }] } });
    }
    if (path === "/api/insights/missions/1/review") { writes.push(request.postDataJSON()); review = { ...request.postDataJSON(), at: new Date().toISOString() }; return route.fulfill({ json: { ok: true } }); }
    if (path === "/api/missions/1/criteria") { writes.push(request.postDataJSON()); return route.fulfill({ json: { criteria: [] } }); }
    if (path.startsWith("/api/missions")) {
      const mission = { ...closure, status: "active", goal: closure.instruction, plan: [], notes: null, pending_actions: [], logs: [], runs: 1, grants: [], updated_at: closure.closed_at };
      return route.fulfill({ json: path === "/api/missions" ? { missions: [mission], grantable: {} } : mission });
    }
    return route.fulfill({ status: 500, json: { detail: `Unexpected ${path}` } });
  });
  await page.goto("/");
  return { requests, writes, recover: () => { shouldFail = false; } };
}
test("admin baseline, daily detail, filters and review", async ({ page }) => {
  const { requests, writes } = await setup(page);
  await page.getByRole("button", { name: "运行质量", exact: true }).click();
  await expect(page.getByRole("heading", { name: "任务质量", exact: true })).toBeVisible();
  await expect(page.getByText("暂无样本", { exact: true })).toBeVisible();
  await page.locator(".admin-person summary").click();
  await expect(page.getByRole("table")).toBeVisible();
  await expect(page.getByText("7 天共 2 条推送", { exact: false })).toBeVisible();
  await page.getByLabel("查找用户").fill("nobody");
  await expect(page.getByText("没有匹配的用户数据。")).toBeVisible();
  await page.getByLabel("查找用户").fill("");
  await page.getByLabel("统计周期").selectOption("14");
  await expect.poll(() => requests.includes("/api/insights/quality?days=14&offset=14")).toBe(true);
  await page.locator(".admin-review summary").click();
  await expect(page.getByText("初始 20 → 回读 12 · 达标")).toBeVisible();
  await expect(page.getByRole("button", { name: "保存复盘" })).toBeDisabled();
  await page.getByLabel("复盘判断").selectOption("false_close");
  await page.getByLabel("复盘依据").fill("回查 A 网点系统，异常件仍为 20。");
  await page.getByRole("button", { name: "保存复盘" }).click();
  await expect(page.locator(".admin-review summary .badge")).toHaveText("确认误关闭");
  expect(writes).toEqual([{ verdict: "false_close", reason: "回查 A 网点系统，异常件仍为 20。" }]);
});
test("ordinary users have no admin entry", async ({ page }) => {
  const { requests } = await setup(page, false);
  await expect(page.getByRole("button", { name: "长期任务", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "运行质量", exact: true })).toHaveCount(0);
  expect(requests.some(p => p.startsWith("/api/insights"))).toBe(false);
});
test("admin error retries without stale metrics", async ({ page }) => {
  const { recover } = await setup(page, true, true);
  await page.getByRole("button", { name: "运行质量", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("暂时不可用");
  recover();
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByRole("heading", { name: "任务质量", exact: true })).toBeVisible();
});
test("admin desktop and phone layouts", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 }); await setup(page);
  await page.getByRole("button", { name: "运行质量", exact: true }).click();
  await expect(page.locator(".admin-metric")).toHaveCount(4);
  await page.screenshot({ path: "/tmp/relay-admin-overview.png", fullPage: true, animations: "disabled" });
  await page.locator(".admin-person summary").click();
  await page.screenshot({ path: "/tmp/relay-admin-desktop.png", fullPage: true, animations: "disabled" });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.locator(".admin-review summary").click();
  await expect(page.getByLabel("复盘依据")).toBeVisible();
  await page.locator(".admin-review").screenshot({ path: "/tmp/relay-admin-review-mobile.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect.poll(() => page.locator(".sidebar").evaluate(el => el.getBoundingClientRect().right)).toBeLessThanOrEqual(0);
  await page.locator(".thread-scroll").evaluate(el => { el.scrollTop = 0; });
  await page.screenshot({ path: "/tmp/relay-admin-mobile.png", fullPage: true, animations: "disabled" });
});
test("user can bind business verification from task detail", async ({ page }) => {
  const { writes } = await setup(page);
  await page.getByRole("button", { name: "长期任务", exact: true }).click();
  await page.getByRole("button", { name: "查看进展", exact: true }).click();
  await page.getByRole("button", { name: "设置核验来源", exact: true }).click();
  await expect(page.getByLabel("指标单元格")).toHaveValue("B2");
  await page.setViewportSize({ width: 375, height: 812 });
  await expect.poll(() => page.locator(".sidebar").evaluate(el => el.getBoundingClientRect().right)).toBeLessThanOrEqual(0);
  await page.locator(".proof-editor").screenshot({ path: "/tmp/relay-proof-mobile.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByLabel("指标单元格").fill("D9");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await page.getByRole("button", { name: "设置核验来源", exact: true }).click();
  await expect(page.getByLabel("指标单元格")).toHaveValue("B2");
  await page.getByLabel("指标单元格").fill("C2");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes).toEqual([{ criteria: [{ text: criterion.text, requirement: "business", rule: { ...rule, cell: "C2" } }] }]);
});

for (const [language, title] of [["en", "Operations quality"], ["id", "Kualitas operasional"]]) {
  test(`admin narrow dark layout and keyboard disclosures in ${language}`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 812 });
    await page.emulateMedia({ colorScheme: "dark" });
    await setup(page, true, false, language);
    // Navigate at desktop width, then check the existing mobile shell.
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.getByRole("button", { name: title, exact: true }).click();
    await expect(page.locator(".admin-metric")).toHaveCount(4);
    await expect(page.getByRole("button", { name: language === "en" ? "Refresh" : "Muat ulang", exact: true })).toBeVisible();
    await page.setViewportSize({ width: 320, height: 812 });
    const definitions = page.locator(".admin-definitions summary");
    await definitions.focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".admin-definitions")).toHaveAttribute("open", "");
    await page.keyboard.press("Enter");
    const person = page.locator(".admin-person summary");
    await person.focus();
    await page.keyboard.press("Space");
    await expect(page.getByRole("table")).toBeVisible();
    await page.locator(".admin-review summary").click();
    await expect(page.locator(".admin-review textarea")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(await page.locator(".admin-page").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await page.locator(".thread-scroll").evaluate(el => { el.scrollTop = 0; });
    await page.screenshot({ path: `/tmp/relay-admin-${language}-dark.png`, animations: "disabled" });
  });
}
