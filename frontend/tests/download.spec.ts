import { test, expect } from "@playwright/test";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import type { AddressInfo } from "node:net";

// A future release deliberately differs from today's build: publishing a new
// updater manifest must also move the website's download links without a deploy.
const manifest = `version: 0.2.3
files:
  - url: Relay-0.2.3-mac.zip
    size: 123000000
  - url: Relay-0.2.3.dmg
    size: 128000000
  - url: Relay-0.2.3-arm64.dmg
    size: 121000000
`;

test.beforeEach(async ({ page }) => {
  await page.route("**/desktop/latest-mac.yml", route => route.fulfill({ contentType: "text/yaml", body: manifest }));
});

test("public download follows the release manifest and switches the installer architecture", async ({ page, baseURL }) => {
  const apiCalls: string[] = [];
  page.on("request", request => { if (new URL(request.url()).pathname.startsWith("/api/")) apiCalls.push(request.url()); });
  // WebKit doesn't support downloads/redirects from route.fulfill(). Serve the
  // app via a real HTTP fixture, with the same artifact MIME type as production.
  await page.unroute("**/desktop/latest-mac.yml");
  const server = createServer(async (request, response) => {
    if (request.url === "/desktop/latest-mac.yml") {
      response.writeHead(200, { "Content-Type": "text/yaml", "Cache-Control": "no-cache" });
      response.end(manifest);
    } else if (request.url === "/desktop/Relay-0.2.3.dmg") {
      response.writeHead(200, { "Content-Type": "application/octet-stream" });
      response.end("test installer");
    } else {
      try {
        const upstream = await fetch(new URL(request.url!, baseURL));
        response.writeHead(upstream.status, { "Content-Type": upstream.headers.get("content-type") ?? "application/octet-stream" });
        response.end(Buffer.from(await upstream.arrayBuffer()));
      } catch { response.writeHead(502); response.end(); }
    }
  });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  try {
    await page.goto(`http://127.0.0.1:${(server.address() as AddressInfo).port}/download/`);
    await expect(page).toHaveTitle("Download for Mac · Relay");
    const download = page.getByRole("link", { name: "Download for Mac · Apple silicon", exact: true });
    await expect(download).toHaveAttribute("href", "/desktop/Relay-0.2.3-arm64.dmg");
    await expect(page.locator(".download-release")).toContainText("v0.2.3 · Apple silicon · 121 MB");
    await page.getByRole("radio", { name: "Intel", exact: true }).check();
    await expect(page.getByRole("link", { name: "Download for Mac · Intel", exact: true })).toHaveAttribute("href", "/desktop/Relay-0.2.3.dmg");
    const [file] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("link", { name: "Download for Mac · Intel", exact: true }).click(),
    ]);
    expect(file.suggestedFilename()).toBe("Relay-0.2.3.dmg");
    expect(await readFile((await file.path())!, "utf8")).toBe("test installer");
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
  expect(apiCalls).toEqual([]);
});

test("a missing manifest offers retry, never a guessed installer", async ({ page }) => {
  await page.route("**/desktop/latest-mac.yml", route => route.fulfill({ status: 503 }));
  await page.goto("/download");
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.locator('a[href$=".dmg"]')).toHaveCount(0);
  await page.route("**/desktop/latest-mac.yml", route => route.fulfill({ body: manifest }));
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("link", { name: "Download for Mac · Apple silicon" })).toBeVisible();
});

test("an incomplete or off-site manifest cannot supply a download link", async ({ page }) => {
  for (const body of [manifest.replace("Relay-0.2.3-arm64.dmg", "https://example.com/Relay-0.2.3-arm64.dmg"), "<!DOCTYPE html><html>not a release</html>"]) {
    await page.route("**/desktop/latest-mac.yml", route => route.fulfill({ body }));
    await page.goto("/download/");
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.locator('a[href$=".dmg"]')).toHaveCount(0);
  }
});

test("feature previews and locale preferences work on the simplified page", async ({ page }) => {
  await page.goto("/download/");
  await page.getByRole("button", { name: "Notifications", exact: true }).click();
  await expect(page.getByRole("region", { name: "Feature preview · Notifications" })).toContainText("Your meeting starts in 15 minutes.");
  await page.getByRole("button", { name: "Folder access", exact: true }).click();
  await expect(page.getByRole("region", { name: "Feature preview · Folder access" })).toContainText("Only the folders you choose");
  await page.getByRole("combobox").selectOption("zh");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("你的助理，就在桌面。");
  await expect(page.getByRole("link", { name: "下载 Mac 版 · Apple 芯片" })).toBeVisible();
  await page.getByRole("combobox").selectOption("id");
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Asisten Anda.Kini di desktop.");
  await expect(page.getByRole("combobox")).toHaveValue("id");
});

test("preview auto-plays in view, can pause, and stops for reduced motion", async ({ page }) => {
  await page.clock.install();
  await page.goto("/download/");
  await page.locator("#features").scrollIntoViewIfNeeded();
  await expect(page.locator("#features")).toHaveAttribute("data-preview-motion", "true");
  await page.clock.runFor(6600);
  await expect(page.getByRole("button", { name: "Notifications", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.locator("#features").getByRole("button", { name: "Pause animation" }).click();
  await page.clock.runFor(14000);
  await expect(page.getByRole("button", { name: "Notifications", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".download-orbit-mascot")).toHaveCSS("animation-play-state", "paused");
  await page.locator("#features").getByRole("button", { name: "Play animation" }).click();
  await page.clock.runFor(6600);
  await expect(page.getByRole("button", { name: "Folder access", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.locator("#features")).toHaveAttribute("data-preview-motion", "false");
  await page.clock.runFor(14000);
  await expect(page.getByRole("button", { name: "Folder access", exact: true })).toHaveAttribute("aria-pressed", "true");
});

for (const width of [1440, 375, 320]) {
  test(`download is usable at ${width}px with reduced motion`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/download/");
    await expect(page.getByRole("link", { name: "Download for Mac · Apple silicon" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.locator(".download-orbit-mascot")).toHaveCSS("animation-name", "none");
    await page.getByRole("radio", { name: "Intel", exact: true }).check();
    await expect(page.getByRole("link", { name: "Download for Mac · Intel" })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`download-${width}.png`), fullPage: true });
  });
}
