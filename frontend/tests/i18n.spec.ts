import { test, expect, type Page } from "@playwright/test";
import { resolveLocale, setLanguagePreference, t } from "../src/i18n";
import { messages } from "../src/locales/messages";
import { common } from "../src/locales/common";
import { dayLabel, relative, stepActive, stepDone } from "../src/format";

const settings = { proactive: true, brief_enabled: false, sources: { mail: true, calendar: true }, quiet_start: "22:00", quiet_end: "08:00", brief_time: "09:00", meeting_brief_minutes: 15, max_interrupts_per_hour: 3, digest_times: ["11:30", "16:30"], language: "auto" };
const action = { id: 1, kind: "send_mail", status: "pending", summary: "Original summary", result: null, to: "person@example.com", subject: "Original subject", body: "邮件原文 — original email", reply_all: true, others: ["a@example.com", "b@example.com"], references: ["Reference"], rsvp: null };
const mission = { id: 1, title: "Original mission", goal: "Original goal", status: "asking", plan: [{ step: "Original step", status: "todo" }], notes: "Original notes", grants: [], question: "Original question", result: null, runs: 2, waiting_for: null, next_run_at: null, updated_at: new Date().toISOString(), pending_actions: [], logs: [] };
const cards = [
  { kind: "draft", action_id: 1, action },
  { kind: "event", signal_id: 2, title: "Original event", start: new Date().toISOString(), end: null, all_day: false, location: null, organizer: "Andrew", attendees: [], rsvp: "accept", conflicts: [], meeting_url: null, app_link: null, action_id: null },
  { kind: "mission", mission_id: 1, mission },
];

async function mockApi(page: Page, signedIn = true, withCards = false) {
  const writes: { path: string; body: unknown }[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() !== "GET") writes.push({ path, body: request.postDataJSON() });
    if (path === "/api/auth/me") return route.fulfill({ status: signedIn ? 200 : 401, json: signedIn ? { id: "test", name: "Ellis", is_admin: true, email: null, avatar_url: null } : { detail: "Unauthorized" } });
    if (path === "/api/auth/config") return route.fulfill({ json: { dev_login: false } });
    if (path === "/api/home") return route.fulfill({ json: { conversation: { id: "home" }, messages: withCards ? [{ id: 1, role: "assistant", text: "Original response", steps: ["read_mail"], cards }] : [], status: { source_errors: 0, last_synced_at: new Date().toISOString() } } });
    if (path === "/api/board") return route.fulfill({ json: { me: [], others: [], relay: [] } });
    if (path === "/api/meetings") return route.fulfill({ json: { upcoming: [], recent: [] } });
    if (path === "/api/progress") return route.fulfill({ json: { days: [], notes: [] } });
    if (path === "/api/models") return route.fulfill({ json: { models: ["test:model"], default: "test:model" } });
    if (path === "/api/settings") return route.fulfill({ json: { settings, sources: {} } });
    if (path === "/api/conversations") return route.fulfill({ json: [{ id: "chat", title: "Original conversation", channel: "web", updated_at: new Date().toISOString() }] });
    if (path === "/api/conversations/chat/messages") return route.fulfill({ json: [{ id: 2, role: "user", text: "Original history" }] });
    if (path === "/api/missions") return route.fulfill({ json: { missions: [mission], grantable: { send_mail: "发送邮件" } } });
    if (path === "/api/missions/1") return route.fulfill({ json: mission });
    if (path === "/api/notify-rules") return route.fulfill({ json: [{ id: 1, match: { group: "approval", approval: "Cuti" }, level: "brief", label: "x", source: "card", hits: 4, last_hit_at: null }] });
    if (["/api/integrations", "/api/tasks", "/api/memories"].includes(path)) return route.fulfill({ json: [] });
    return route.fulfill({ status: 500, json: { detail: `Unexpected test request: ${path}` } });
  });
  return writes;
}

async function systemLanguage(page: Page, language: string) {
  await page.addInitScript((value) => {
    Object.defineProperty(navigator, "language", { configurable: true, get: () => value });
    Object.defineProperty(navigator, "languages", { configurable: true, get: () => [value, "en-US"] });
  }, language);
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

test("regional language resolution and English fallback", () => {
  for (const value of ["zh-CN", "zh-TW", "zh-Hant-HK", "ZH_cn"]) expect(resolveLocale(value)).toBe("zh");
  expect(resolveLocale("id-ID")).toBe("id");
  expect(resolveLocale("en-GB")).toBe("en");
  for (const value of ["fr-FR", "ja", "", null, undefined]) expect(resolveLocale(value)).toBe("en");
});

test("catalogues have matching interpolation parameters and translated tool states", () => {
  const params = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort();
  for (const [source, variants] of Object.entries(messages)) for (const translated of variants) {
    expect(translated.trim(), source).not.toBe("");
    expect(params(translated), source).toEqual(params(source));
  }
  for (const [key, variants] of Object.entries(common)) for (const translated of variants) {
    expect(translated.trim(), key).not.toBe("");
    expect(params(translated), key).toEqual(params(variants[0]));
  }
  setLanguagePreference("en");
  expect(stepActive("read_mail")).toBe("Reading email");
  expect(stepDone("read_mail")).toBe("Read email");
  expect(t("pendingActions", { count: 1 })).toContain("1 action needs");
  expect(t("pendingActions", { count: 2 })).toContain("2 actions need");
  expect(dayLabel(new Date().toISOString())).toBe("Today");
  expect(relative(new Date(Date.now() - 5 * 60_000).toISOString())).toBe("5 minutes ago");
  setLanguagePreference("id");
  expect(dayLabel(new Date().toISOString())).toBe("Hari ini");
});

for (const [language, htmlLang, login] of [["en-GB", "en", "Sign in with Feishu"], ["zh-CN", "zh-CN", "使用飞书登录"], ["id-ID", "id", "Masuk dengan Feishu"], ["fr-FR", "en", "Sign in with Feishu"]]) {
  test(`login follows ${language}`, async ({ page }) => {
    await systemLanguage(page, language);
    await mockApi(page, false);
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("lang", htmlLang);
    await expect(page.getByRole("link", { name: login })).toBeVisible();
    await page.setViewportSize({ width: 375, height: 812 });
    await noOverflow(page);
  });
}

test("manual override persists, auto follows live system changes, and tabs sync", async ({ page, context }) => {
  await systemLanguage(page, "zh-CN");
  await mockApi(page, false);
  await page.goto("/");
  await page.getByRole("combobox").selectOption("id");
  await expect(page.getByRole("link", { name: "Masuk dengan Feishu" })).toBeVisible();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "id");
  const other = await context.newPage();
  await mockApi(other, false);
  await other.goto("/");
  await other.getByRole("combobox").selectOption("en");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await page.getByRole("combobox").selectOption("auto");
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await page.evaluate(() => {
    Object.defineProperty(navigator, "languages", { configurable: true, get: () => ["id-ID"] });
    dispatchEvent(new Event("languagechange"));
  });
  await expect(page.locator("html")).toHaveAttribute("lang", "id");
});

test("language still works when browser storage is unavailable", async ({ page }) => {
  await systemLanguage(page, "id-ID");
  await page.addInitScript(() => {
    Storage.prototype.getItem = () => { throw new Error("Blocked storage"); };
    Storage.prototype.setItem = () => { throw new Error("Blocked storage"); };
  });
  await mockApi(page, false);
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Masuk dengan Feishu" })).toBeVisible();
  await page.getByRole("combobox").selectOption("en");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
});

test("changing UI language preserves drafts and does not save assistant language", async ({ page }, testInfo) => {
  await systemLanguage(page, "en-US");
  const writes = await mockApi(page, true, true);
  await page.goto("/");
  await page.getByRole("textbox", { name: "Email draft body" }).fill("My unsent draft");
  await page.getByRole("textbox", { name: "Reply to Relay or ask for help…" }).fill("My unsent question");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await page.getByLabel("Interface language").selectOption("id");
  await expect(page.getByLabel("Bahasa balasan Relay")).toHaveValue("auto");
  await expect(page.getByRole("heading", { name: "Pengaturan", exact: true })).toBeVisible();
  expect(writes).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Pengaturan", exact: true })).toBeFocused();
  await expect(page.getByRole("textbox", { name: "Isi draf email" })).toHaveValue("My unsent draft");
  await expect(page.getByRole("textbox", { name: "Balas Relay atau minta bantuan…" })).toHaveValue("My unsent question");
  await expect(page.getByText("Diterima", { exact: true })).toBeVisible();
  await expect(page.getByText("Menunggu jawaban Anda", { exact: true })).toBeVisible();
  await page.locator(".steps-toggle").first().click();  // 过程默认收起，展开后看步骤名称
  await expect(page.getByText("Membaca email", { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("home-id.png"), fullPage: true });
});

for (const locale of ["en-US", "zh-CN", "id-ID"]) {
  test(`settings and secondary panels at mobile width: ${locale}`, async ({ page }, testInfo) => {
    await systemLanguage(page, locale);
    await page.setViewportSize({ width: 375, height: 812 });
    await mockApi(page);
    await page.goto("/");
    await page.locator(".mobile-bar button").click();
    await page.locator(".sidebar-foot > button").nth(3).click();  // 记忆、定时任务、自动办的事、提醒设置……
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.locator(".language-select select")).toHaveValue("auto");
    await noOverflow(page);
    expect(await page.locator(".drawer-body").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`settings-${locale}.png`), fullPage: true });
    await page.keyboard.press("Escape");
    for (const index of [0, 1, 2, 4]) {
      await page.locator(".mobile-bar button").click();
      await page.locator(".sidebar-foot > button").nth(index).click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await noOverflow(page);
      if (locale !== "zh-CN") {
        const content = await page.locator(".drawer-body").innerText();
        expect(content).not.toMatch(/[\u3400-\u9fff]/);
      }
      await page.keyboard.press("Escape");
    }
  });
}

test("auth failures offer retry and history is keyboard accessible", async ({ page }) => {
  await systemLanguage(page, "en-US");
  await mockApi(page);
  let fails = true;
  await page.route("**/api/auth/me", route => fails ? route.fulfill({ status: 503, json: {} }) : route.fallback());
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Unable to load");
  fails = false;
  await page.getByRole("button", { name: "Try again" }).click();
  const history = page.getByRole("button", { name: /Original conversation/ });
  await history.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Original history")).toBeVisible();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect.poll(() => page.evaluate(() => !!document.activeElement?.closest("dialog"))).toBe(true);
  await page.keyboard.press("Shift+Tab");
  expect(await page.evaluate(() => !!document.activeElement?.closest("dialog"))).toBe(true);
});

for (const language of ["en-US", "id-ID"]) {
  test(`translated cards fit a narrow dark screen: ${language}`, async ({ page }, testInfo) => {
    await systemLanguage(page, language);
    await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
    await page.setViewportSize({ width: 320, height: 740 });
    await mockApi(page, true, true);
    await page.goto("/");
      await expect(page.locator(".draft-body")).toBeVisible();
    await noOverflow(page);
    for (const card of await page.locator(".app-card").all()) {
      expect(await card.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    }
    await page.screenshot({ path: testInfo.outputPath(`mobile-cards-${language}.png`), fullPage: true });
  });
}

test("server UI descriptors translate while preserving original names", async () => {
  const { localize } = await import("../src/i18n");
  setLanguagePreference("en");
  expect(localize({ key: "ask.waiting", values: { person: "张三" } }, "legacy text")).toBe("No action needed. Relay is waiting for 张三");
  expect(localize({ key: "board.prepare", values: { title: "原始会议名" } }, "legacy text")).toBe("Prepare for “原始会议名”");
  expect(localize({ key: "future.key" }, "Original content")).toBe("Original content");
});
