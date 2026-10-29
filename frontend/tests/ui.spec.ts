import { test, expect, type Page } from "@playwright/test";

async function mockApp(page: Page, locale = "zh") {
  const sent: unknown[] = [];
  const models: string[] = [];
  await page.addInitScript(value => localStorage.setItem("relay.ui-language", value), locale);
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/me") return route.fulfill({ json: { id: "test", name: "Ellis", is_admin: false } });
    if (path === "/api/home") return route.fulfill({ json: { conversation: { id: "home" }, messages: [], status: { source_errors: 0 } } });
    if (path === "/api/board") return route.fulfill({ json: { me: [], others: [], relay: [] } });
    if (path === "/api/meetings") return route.fulfill({ json: { upcoming: [], recent: [] } });
    if (path === "/api/progress") return route.fulfill({ json: { days: [], notes: [] } });
    if (path === "/api/models") {
      models.push(path);
      return route.fulfill({ json: { models: ["test:gemini-4-argon", "test:other"], default: "test:gemini-4-argon" } });
    }
    if (route.request().method() === "POST" && path.includes("/messages")) {
      sent.push(route.request().postDataJSON());
      return route.fulfill({ contentType: "text/event-stream", body: 'data: {"type":"text","delta":"OK"}\n\n' });
    }
    return route.fulfill({ json: [] });
  });
  return { sent, models };
}

async function fits(page: Page) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect.poll(() => page.evaluate(() => ({ height: document.documentElement.scrollHeight, viewport: innerHeight, fits: document.documentElement.scrollHeight <= innerHeight + 1 }))).toMatchObject({ fits: true });
  const send = await page.locator(".send").boundingBox();
  expect(send).not.toBeNull();
  expect(send!.y + send!.height).toBeLessThanOrEqual(await page.evaluate(() => visualViewport!.height + 1));
}

test("composer focus has one rounded indicator and no model UI; IME never sends a candidate", async ({ page }, info) => {
  const { sent, models } = await mockApp(page);
  await page.goto("/");
  const input = page.locator(".composer textarea");
  await input.fill("准备会议");
  await expect(input).toHaveCSS("outline-style", "none");
  await expect(page.locator(".composer")).not.toHaveCSS("box-shadow", "none");
  await expect(page.locator(".composer select, .composer-hint")).toHaveCount(0);
  await expect(page.locator(".composer")).not.toContainText("gemini");
  expect(models).toEqual([]);
  await page.screenshot({ path: info.outputPath("desktop-composer.png") });
  await input.dispatchEvent("keydown", { key: "Enter", isComposing: true });
  await input.dispatchEvent("keydown", { key: "Enter", keyCode: 229 });
  await expect(input).toHaveValue("准备会议");
  expect(sent).toEqual([]);
  await input.press("Shift+Enter");
  await expect(input).toHaveValue("准备会议\n");
  await input.press("Enter");
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0]).toEqual({ text: "准备会议", model: null });
  await expect(input).toHaveValue("");
});

test("draft reflows on resize and long input scrolls without pushing send off screen", async ({ page }, info) => {
  await mockApp(page);
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto("/");
  await page.locator(".inspector-head button").last().click();
  const input = page.locator(".composer textarea");
  const draft = "Please prepare the meeting notes and follow up with the team. ".repeat(2);
  await input.fill(draft);
  const wide = (await input.boundingBox())!.height;
  await page.setViewportSize({ width: 320, height: 740 });
  await expect.poll(async () => (await input.boundingBox())!.height).toBeGreaterThan(wide);
  await expect(input).toHaveValue(draft);
  await input.fill("这是很长的输入内容，保留草稿。\n".repeat(80));
  expect(await input.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true);
  await input.press("End");
  await input.press("x");
  expect(await input.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(2);
  await fits(page);
  await page.screenshot({ path: info.outputPath("mobile-long-draft.png") });
  await input.fill("短句");
  await expect.poll(async () => (await input.boundingBox())!.height).toBeLessThan(60);
});

for (const locale of ["en", "zh", "id"]) {
  test(`mobile layout, touch inputs and closed navigation: ${locale}`, async ({ page }, info) => {
    await mockApp(page, locale);
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/");
    const input = page.locator(".composer textarea");
    await input.fill("检查输入 / Check input / Periksa masukan");
    await expect(input).toHaveCSS("font-size", "16px");
    for (const width of [320, 375, 820, 1024]) {
      await page.setViewportSize({ width, height: 812 });
      await fits(page);
    }
    await page.setViewportSize({ width: 375, height: 812 });
    await expect(page.locator(".sidebar")).toBeHidden();
    for (const tile of await page.locator(".dock-text").all()) {
      expect(await tile.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    }
    const menu = page.locator(".mobile-bar button");
    await menu.focus();
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => !!document.activeElement?.closest(".sidebar"))).toBe(false);
    await menu.click();
    await expect(page.locator(".sidebar-close")).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    expect(await page.evaluate(() => !!document.activeElement?.closest(".sidebar"))).toBe(true);
    await page.keyboard.press("Escape");
    await expect(menu).toBeFocused();
    await expect(page.locator(".sidebar")).toBeHidden();
    await page.screenshot({ path: info.outputPath(`mobile-${locale}.png`) });
    await menu.click();
    await page.setViewportSize({ width: 1024, height: 812 });
    await expect(page.locator(".sidebar-backdrop")).toHaveCount(0);
    await page.setViewportSize({ width: 375, height: 812 });
    await expect(page.locator(".sidebar")).toBeHidden();
    await page.setViewportSize({ width: 375, height: 360 });
    await input.fill("键盘弹出后仍可输入\n".repeat(30));
    await fits(page);
    await menu.click();
    await page.locator(".sidebar-foot button").last().scrollIntoViewIfNeeded();
    await expect(page.locator(".sidebar-foot button").last()).toBeInViewport();
  });
}

test("visual viewport keyboard shrink keeps input visible; pinch zoom does not shrink app layout", async ({ page }, info) => {
  await mockApp(page);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  const input = page.locator(".composer textarea");
  await input.fill("键盘场景\n".repeat(40));
  await page.evaluate(() => {
    Object.defineProperty(visualViewport, "height", { configurable: true, value: 360 });
    visualViewport!.dispatchEvent(new Event("resize"));
  });
  await expect.poll(async () => (await page.locator(".layout").boundingBox())!.height).toBe(360);
  await fits(page);
  await page.screenshot({ path: info.outputPath("mobile-keyboard.png") });
  await page.evaluate(() => {
    Object.defineProperty(visualViewport, "scale", { configurable: true, value: 2 });
    Object.defineProperty(visualViewport, "height", { configurable: true, value: 180 });
    visualViewport!.dispatchEvent(new Event("resize"));
  });
  expect((await page.locator(".layout").boundingBox())!.height).toBe(360);
  await page.evaluate(() => {
    delete (visualViewport as unknown as Record<string, unknown>).scale;
    delete (visualViewport as unknown as Record<string, unknown>).height;
    visualViewport!.dispatchEvent(new Event("resize"));
  });
  await expect.poll(async () => (await page.locator(".layout").boundingBox())!.height).toBe(812);
  await expect(input).toHaveValue("键盘场景\n".repeat(40));
});
