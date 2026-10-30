import { test, expect, type Page } from "@playwright/test";

/** 模拟 Mac 客户端注入的 window.relayDesktop（真实的由 Electron 预加载脚本提供）。 */
async function fakeDesktop(page: Page) {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "language", { configurable: true, get: () => "zh-CN" });
    Object.defineProperty(navigator, "languages", { configurable: true, get: () => ["zh-CN"] });
    const state = {
      paired: false, revoked: false, deviceId: null as string | null, notes: [] as string[], token: null as string | null,
      folders: [{ id: "f1", label: "报价", read: true, write: false, root: "/Users/ellis/Documents/报价" }],
    };
    (window as unknown as { __mac: typeof state }).__mac = state;
    (window as unknown as { relayDesktop: unknown }).relayDesktop = {
      status: async () => ({ paired: state.paired, revoked: state.revoked, deviceId: state.deviceId, name: "Ellis-MBP", platform: "darwin", version: "0.1.0" }),
      paired: async (info: { token: string; id: string }) => { state.paired = true; state.token = info.token; state.deviceId = info.id; return true; },
      unpair: async () => true,
      notify: async (_title: string, body: string) => { state.notes.push(body); return true; },
      folders: async () => state.folders,
      addFolder: async () => { state.folders = [...state.folders, { id: "f2", label: "成果", read: true, write: false, root: "/Users/ellis/成果" }]; return state.folders; },
      updateFolder: async (id: string, change: { read?: boolean; write?: boolean }) => {
        state.folders = state.folders.map((f) => (f.id === id ? { ...f, ...change } : f));
        return state.folders;
      },
      removeFolder: async (id: string) => { state.folders = state.folders.filter((f) => f.id !== id); return state.folders; },
      reveal: async () => "",
      onDeviceChanged: () => () => undefined,
    };
  });
}

async function mockApi(page: Page) {
  const writes: { path: string; body: unknown }[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const body = request.method() === "POST" || request.method() === "PUT" ? request.postDataJSON() : null;
    if (body !== null) writes.push({ path, body });
    if (path === "/api/auth/me") return route.fulfill({ json: { id: "u1", name: "Ellis", is_admin: false, email: null, avatar_url: null,
      role: "member", tenant: { id: "t1", name: "Co", slug: "co" }, workspaces: 1, feishu_linked: true } });
    if (path === "/api/auth/config") return route.fulfill({ json: { dev_login: false } });
    if (path === "/api/devices" && request.method() === "POST") return route.fulfill({ json: { id: "d1", token: "device-token", name: "Ellis-MBP",
      platform: "darwin", app_version: "0.1.0", online: true, folders: [], last_seen_at: null, created_at: null } });
    if (path === "/api/home") return route.fulfill({ json: { conversation: { id: "home" }, messages: [], status: { source_errors: 0 } } });
    if (path === "/api/board") return route.fulfill({ json: { me: [], others: [], relay: [] } });
    if (path === "/api/meetings") return route.fulfill({ json: { upcoming: [], recent: [] } });
    if (path === "/api/progress") return route.fulfill({ json: { days: [], notes: [] } });
    if (path === "/api/settings") return route.fulfill({ json: { settings: { proactive: true, sources: {}, language: "auto", brief_enabled: true,
      brief_time: "08:30", quiet_start: "21:00", quiet_end: "07:00", meeting_brief_minutes: 30, digest_times: ["12:00"], max_interrupts_per_hour: 3 }, sources: {} } });
    if (path === "/api/connections") return route.fulfill({ json: {
      imap: { provider: "imap", connected: false, status: "none", config: {}, secrets: { password: false } },
      ics: { provider: "ics", connected: false, status: "none", config: {}, secrets: { url: false } }, feishu: { linked: true } } });
    return route.fulfill({ json: [] });
  });
  return writes;
}

test("in the Mac client: pairs once after login, and folders are authorised with read and write kept separate", async ({ page }, testInfo) => {
  await fakeDesktop(page);
  const writes = await mockApi(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await expect.poll(() => page.evaluate(() => (window as unknown as { __mac: { token: string | null } }).__mac.token)).toBe("device-token");
  expect(writes.filter((w) => w.path === "/api/devices")).toEqual([{ path: "/api/devices", body: { name: "Ellis-MBP", platform: "darwin", app_version: "0.1.0" } }]);

  await page.getByRole("button", { name: "提醒设置" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("已连接到你的账号。")).toBeVisible();
  await expect(dialog.getByText("/Users/ellis/Documents/报价")).toBeVisible();
  const write = dialog.getByRole("checkbox", { name: "允许写入新文件" });
  await expect(write).not.toBeChecked();
  await write.check();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __mac: { folders: { write: boolean }[] } }).__mac.folders[0].write)).toBe(true);
  await dialog.getByRole("button", { name: "+ 授权一个文件夹" }).click();
  await expect(dialog.getByText("成果", { exact: true })).toBeVisible();
  await dialog.screenshot({ path: testInfo.outputPath("this-mac.png") });
});

test("in a normal browser there is no Mac section and nothing is paired", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "language", { configurable: true, get: () => "zh-CN" });
    Object.defineProperty(navigator, "languages", { configurable: true, get: () => ["zh-CN"] });
  });
  const writes = await mockApi(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "提醒设置" }).click();
  await expect(page.getByRole("dialog").getByText("这台 Mac")).toHaveCount(0);
  expect(writes.filter((w) => w.path === "/api/devices")).toEqual([]);
});
