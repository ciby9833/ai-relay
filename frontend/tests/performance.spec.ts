import { test, expect, type Page } from "@playwright/test";

const now = Math.floor(Date.now() / 1000);
const series = (value: number | null, labels: Record<string, string> = {}) => ({ labels, points: [[now, value]] });
const snapshot = () => ({
  status: "ok", gpu: "not_configured", window: "1h", collected_at: now, start: now - 3600, end: now, step: 30, errors: [],
  targets: { node: "up", cadvisor: "up", api: "up", worker: "up", feishu: "up" },
  current: {
    cpu: [series(27.4)], cores: [series(8)], cpu_core: [series(19, { cpu: "0" }), series(36, { cpu: "1" })], load: [series(1.3)],
    memory: [series(41)], memory_total: [series(16 * 1024 ** 3)], memory_available: [series(9.4 * 1024 ** 3)],
    swap_used: [series(0)], swap_total: [series(0)], host_sample: [series(now - 8)],
    disk_total: [series(200 * 1024 ** 3, { mountpoint: "/", device: "/dev/vda1" })],
    disk_free: [series(82 * 1024 ** 3, { mountpoint: "/", device: "/dev/vda1" })], disk_latency: [series(.012, { device: "vda" }), series(.021, { device: "dm-0" })],
    service_cpu: [series(.35, { service: "api" })], service_memory: [series(240 * 1024 ** 2, { service: "api" })],
    service_seen: [series(now - 5, { service: "api" })], heartbeat_age: ["api", "worker", "feishu"].map(job => series(4, { job })),
    worker_cycle_age: [series(40)], inflight: [series(2, { kind: "turn" }), series(3, { kind: "llm" })],
    turn_p95: [series(18)], tool_p95: [series(1.5)], llm_p95: [series(12, { provider: "gemini" })], llm_first: [series(2, { provider: "gemini" })],
    llm_calls: [series(38, { provider: "gemini", outcome: "success" }), series(2, { provider: "gemini", outcome: "limited" })],
    tokens: [series(15000, { provider: "gemini", direction: "input" }), series(2000, { provider: "gemini", direction: "output" })],
  },
  history: Object.fromEntries(["cpu", "memory", "disk_read", "disk_write", "network_rx", "network_tx"].map(key => [key, (key.startsWith("disk_") ? ["vda", "dm-0"] : [""]).map(device => ({ labels: device ? { device } : {}, points: Array.from({ length: 121 }, (_, i) => [now - 3600 + i * 30, i > 40 && i < 45 ? null : 25 + Math.sin(i / 6) * 10]) }))])),
  queue: { scheduled: { due: 1, oldest_seconds: 45 }, missions: { due: 2, oldest_seconds: 180 } },
});

async function setup(page: Page, language = "zh", admin = true) {
  const requests: string[] = [];
  let state: "ok" | "disabled" | "error" | "partial" | "warming" = "ok";
  await page.addInitScript(language => localStorage.setItem("relay.ui-language", language), language);
  await page.route("**/api/**", route => {
    const url = new URL(route.request().url()), path = url.pathname;
    if (path === "/api/auth/me") return route.fulfill({ json: { id: "u", name: "Ellis", is_admin: admin } });
    if (path === "/api/conversations") return route.fulfill({ json: [] });
    if (path === "/api/home") return route.fulfill({ json: { conversation: { id: "home" }, messages: [], status: { source_errors: 0 } } });
    if (path === "/api/board") return route.fulfill({ json: { me: [], others: [], relay: [] } });
    if (path === "/api/meetings") return route.fulfill({ json: { upcoming: [], recent: [] } });
    if (path === "/api/progress") return route.fulfill({ json: { days: [], notes: [] } });
    if (path === "/api/models") return route.fulfill({ json: { models: [] } });
    if (path === "/api/admin/performance") {
      requests.push(url.search);
      if (state === "error") return route.fulfill({ status: 503, json: { detail: "temporary failure" } });
      const data = snapshot();
      if (state === "warming") return route.fulfill({ json: { ...data, current: { ...data.current, llm_calls: [], llm_p95: [series(null, { provider: "gemini" })], llm_first: [], tokens: [] } } });
      if (state === "disabled") return route.fulfill({ json: { ...data, status: "disabled", current: {}, history: {} } });
      if (state === "partial") return route.fulfill({ json: { ...data, status: "partial", targets: { ...data.targets, worker: "down" }, current: { ...data.current, cpu: [], service_seen: [] } } });
      return route.fulfill({ json: data });
    }
    return route.fulfill({ status: 503, json: { detail: "quality fixture unavailable" } });
  });
  await page.goto("/");
  const adminLabel = language === "en" ? "Operations quality" : language === "id" ? "Kualitas operasional" : "运行质量";
  const perfLabel = language === "en" ? "System performance" : language === "id" ? "Kinerja sistem" : "系统性能";
  if (admin) {
    await page.getByRole("button", { name: adminLabel, exact: true }).click();
    await page.getByRole("button", { name: perfLabel, exact: true }).click();
  }
  return { requests, setState: (value: typeof state) => { state = value; } };
}

test("admin resources, bounded ranges, missing data and retry", async ({ page }) => {
  const { requests, setState } = await setup(page);
  await expect(page.getByRole("heading", { name: "系统性能" })).toBeVisible();
  await expect(page.getByText("27.4%", { exact: true })).toBeVisible();
  await expect(page.getByText("82 GiB", { exact: true })).toBeVisible();
  await page.getByLabel("读写设备", { exact: true }).selectOption("vda");
  await expect(page.getByText("平均读写延迟: 12 ms", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "主机磁盘读取 · vda", exact: true })).toBeVisible();
  await expect(page.getByText("未配置本地 GPU 监控", { exact: false })).toBeVisible();
  await page.getByLabel("趋势时间范围").selectOption("7d");
  await expect.poll(() => requests.includes("?window=7d")).toBe(true);
  setState("partial");
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("部分采集");
  await expect(page.locator(".admin-metric").filter({ has: page.getByRole("heading", { name: "CPU", exact: true }) }).locator("strong")).toHaveText("—");
  await expect(page.getByText("部分业务进程采集缺失", { exact: false })).toBeVisible();
  setState("error");
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("temporary failure");
  await expect(page.locator(".perf-trend")).toHaveCount(0);
  setState("ok");
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByText("27.4%", { exact: true })).toBeVisible();
});

test("disabled monitoring is explicit and ordinary users cannot see the entry", async ({ page }) => {
  const { setState } = await setup(page);
  setState("disabled");
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.getByText("系统性能监控尚未启用。")).toBeVisible();
  await expect(page.locator(".admin-metric")).toHaveCount(0);
  await page.unroute("**/api/**");
  const { requests } = await setup(page, "zh", false);
  await expect(page.getByRole("button", { name: "系统性能", exact: true })).toHaveCount(0);
  expect(requests).toHaveLength(0);
});

test("polling stops when leaving performance", async ({ page }) => {
  await page.clock.install();
  const { requests } = await setup(page);
  await expect(page.getByText("27.4%", { exact: true })).toBeVisible();
  await page.clock.fastForward(30001);
  await expect.poll(() => requests.length).toBe(2);
  await page.getByRole("button", { name: "任务质量", exact: true }).click();
  await expect(page.getByRole("heading", { name: "系统性能", exact: true })).toHaveCount(0);
  const before = requests.length;
  await page.clock.fastForward(90000);
  expect(requests).toHaveLength(before);
});

test("model counters without enough samples are unknown rather than zero", async ({ page }) => {
  const { setState } = await setup(page);
  await expect(page.getByText("27.4%", { exact: true })).toBeVisible();
  setState("warming");
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  const cells = page.getByRole("row").filter({ has: page.getByRole("rowheader", { name: "gemini", exact: true }) }).getByRole("cell");
  await expect(cells).toHaveText(["—", "—", "—", "—", "—", "—", "—", "— / —"]);
});

for (const language of ["zh", "en", "id"]) {
  test(`performance responsive and dark layout ${language}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await setup(page, language);
    await expect(page.locator(".perf-trend svg")).toHaveCount(6);
    await page.screenshot({ path: `/tmp/relay-performance-${language}-desktop.png`, fullPage: true });
    await page.emulateMedia({ colorScheme: "dark" });
    await page.setViewportSize({ width: 375, height: 812 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(await page.locator(".perf-page").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await expect.poll(() => page.locator(".sidebar").evaluate(el => el.getBoundingClientRect().right)).toBeLessThanOrEqual(0);
    expect(await page.locator(".admin-metric").evaluateAll(cards => cards.every(card => card.getBoundingClientRect().right <= innerWidth))).toBe(true);
    await page.screenshot({ path: `/tmp/relay-performance-${language}-mobile.png`, fullPage: true });
    await page.locator(".perf-page section").last().scrollIntoViewIfNeeded();
    await page.screenshot({ path: `/tmp/relay-performance-${language}-models.png`, fullPage: true });
  });
}
