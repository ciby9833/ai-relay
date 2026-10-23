import { test, expect, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

// Articles are served exactly as the API does: stored HTML plus the shared markup from blog_render.py.
const content = resolve(process.cwd(), "../backend/content/blog");
const renderSource = await readFile(resolve(process.cwd(), "../backend/app/blog_render.py"), "utf8");
const shared = [...renderSource.match(/NAVIGATION = \(([\s\S]*?)\n\)/)![1].matchAll(/b'([^']*)'/g)].map(m => m[1]).join("");

test.beforeEach(async ({ context }) => {
  await context.route("**/blog/*/**", async route => {
    const [, slug, ...rest] = new URL(route.request().url()).pathname.split("/").filter(Boolean);
    const relative = rest.join("/") || "index.html";
    let body = await readFile(resolve(content, slug, relative));
    if (relative === "index.html") body = Buffer.from(body.toString().replace(/<body\b[^>]*>/, match => match + shared));
    const type = relative.endsWith(".html") ? "text/html" : relative.endsWith(".mp4") ? "video/mp4" : "image/jpeg";
    await route.fulfill({ body, contentType: type });
  });
});

const toc = (page: Page) => page.locator("relay-blog-toc");
const sideLinks = (page: Page) => toc(page).locator(".side a");

test("wide screens show the contents in the left margin and follow the reader", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/blog/ai-in-business-systems/");
  await expect(toc(page)).toHaveAttribute("mode", "side");
  const headings = page.locator("article h2");
  await expect(sideLinks(page)).toHaveCount(await headings.count());
  await expect(sideLinks(page).first()).toHaveText(await headings.first().innerText());

  // The column sits left of the text and never overlaps it.
  const column = await toc(page).locator(".side").boundingBox();
  const text = await page.locator("article").boundingBox();
  expect(column!.x + column!.width).toBeLessThanOrEqual(text!.x + 40);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  // Clicking jumps (smoothly) to the section, below the sticky navigation, and highlights it.
  await sideLinks(page).nth(7).click();
  const navHeight = await page.locator("relay-blog-navigation").evaluate(node => node.getBoundingClientRect().height);
  await expect.poll(() => headings.nth(7).evaluate(node => Math.round(node.getBoundingClientRect().top)), { timeout: 5000 })
    .toBeGreaterThanOrEqual(navHeight);
  await expect.poll(() => headings.nth(7).evaluate(node => node.getBoundingClientRect().top)).toBeLessThan(navHeight + 80);
  await expect(sideLinks(page).nth(7)).toHaveAttribute("aria-current", "true");
  await expect(page).toHaveURL(/#section-8$/);

  // Plain scrolling moves the highlight too.
  await headings.nth(2).evaluate(node => node.scrollIntoView());
  await expect(sideLinks(page).nth(2)).toHaveAttribute("aria-current", "true");
  await expect(toc(page).locator(".side a[aria-current]")).toHaveCount(1);
});

for (const colorScheme of ["light", "dark"] as const) {
  test(`phones get a collapsible contents bar (${colorScheme})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    await page.goto("/blog/ai-in-business-systems/");
    await expect(toc(page)).toHaveAttribute("mode", "bar");
    const toggle = toc(page).getByRole("button");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(toc(page).locator(".panel")).toBeHidden();

    // The bar stays under the navigation while scrolling and names the current section.
    const headings = page.locator("article h2");
    await headings.nth(3).evaluate(node => node.scrollIntoView());
    const navHeight = await page.locator("relay-blog-navigation").evaluate(node => node.getBoundingClientRect().height);
    await expect.poll(() => toc(page).evaluate(node => Math.round(node.getBoundingClientRect().top))).toBe(Math.round(navHeight));
    await expect(toc(page).locator(".current")).toHaveText(await headings.nth(3).innerText());
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(toc(page).locator(".panel a")).toHaveCount(await headings.count());
    await page.screenshot({ path: testInfo.outputPath("toc-open.png") });
    await toc(page).locator(".panel a").nth(7).click();
    await expect(toc(page).locator(".panel")).toBeHidden();
    // The section lands below both the navigation and the bar.
    const barBottom = await toc(page).evaluate(node => node.getBoundingClientRect().bottom);
    await expect.poll(() => headings.nth(7).evaluate(node => node.getBoundingClientRect().top)).toBeGreaterThanOrEqual(barBottom);
    await expect(toc(page).locator(".current")).toHaveText(await headings.nth(7).innerText());

    // Escape and clicks outside close the panel.
    await toggle.click();
    await page.keyboard.press("Escape");
    await expect(toc(page).locator(".panel")).toBeHidden();
    await toggle.click();
    await page.locator("article p").first().click({ force: true });
    await expect(toc(page).locator(".panel")).toBeHidden();
  });
}

test("short or full-width pages get no contents", async ({ page }) => {
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/blog/relay-day/");
    await expect(page.locator("relay-blog-navigation").getByRole("link", { name: "Articles", exact: true })).toBeVisible();
    await expect(toc(page)).not.toHaveAttribute("mode", /.+/);
    await expect(toc(page).locator(".side")).toBeHidden();
    await expect(toc(page).locator(".bar")).toBeHidden();
  }
});

test("the column appears only when it fits beside the text; otherwise the bar is used", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.goto("/blog/relay-reliable-agent/");
  await expect(toc(page)).toHaveAttribute("mode", "bar");
  await page.setViewportSize({ width: 1280, height: 800 });
  await expect(toc(page)).toHaveAttribute("mode", "side");
  const column = await toc(page).locator(".side").boundingBox();
  const text = await page.locator("article h2").first().boundingBox();
  expect(column!.x).toBeGreaterThanOrEqual(0);
  expect(column!.x + column!.width).toBeLessThan(text!.x);
  await page.setViewportSize({ width: 900, height: 900 });
  await expect(toc(page)).toHaveAttribute("mode", "bar");
  await expect(toc(page).locator(".side")).toBeHidden();
});
