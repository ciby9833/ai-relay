import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

// The stored article bundle is the source of truth; the API serves it plus the shared navigation.
const original = resolve(process.cwd(), "../backend/content/blog/relay-day");
const metadata = JSON.parse(await readFile(resolve(original, "post.json"), "utf8"));
const post = {
  ...metadata, slug: "relay-day", href: "/blog/relay-day/",
  cover: `/blog/relay-day/${metadata.cover}`,
};

test.beforeEach(async ({ context }) => {
  await context.route("https://fonts.googleapis.com/**", route => route.abort());
  await context.route("https://fonts.gstatic.com/**", route => route.abort());
  await context.route("**/api/blog", route => route.fulfill({ json: [post] }));
  for (const prefix of ["/blog/relay-day/", "/__original/"]) {
    await context.route(`**${prefix}**`, async route => {
      const relative = new URL(route.request().url()).pathname.slice(prefix.length) || "index.html";
      const contentType = relative.endsWith(".html") ? "text/html" : relative.endsWith(".mp4") ? "video/mp4" : "image/jpeg";
      let body = await readFile(resolve(original, relative));
      if (prefix === "/blog/relay-day/" && relative === "index.html") {
        body = Buffer.from(body.toString().replace("<body>", '<body><relay-blog-navigation full-bleed></relay-blog-navigation><script src="/blog-navigation.js" defer></script>'));
      }
      await route.fulfill({ body, contentType });
    });
  }
});

test("public cards open the original document without login and support back/refresh", async ({ page }) => {
  const authCalls: string[] = [];
  page.on("request", request => {
    if (new URL(request.url()).pathname.startsWith("/api/auth")) authCalls.push(request.url());
  });
  await page.goto("/blog/");
  await expect(page).toHaveTitle("Blog · Relay");
  await page.getByRole("link", { name: post.title, exact: true }).click();
  await expect(page).toHaveURL(/\/blog\/relay-day\/$/);
  await expect(page.locator(".moment")).toHaveCount(6);
  await expect(page.locator("relay-blog-navigation").getByRole("link", { name: "Articles", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.locator(".moment")).toHaveCount(6);
  await page.locator("relay-blog-navigation").getByRole("link", { name: "Articles", exact: true }).click();
  await expect(page.locator(".blog-card")).toHaveCount(1);
  expect(authCalls).toEqual([]);
});

test("language control is only in the footer and preserves the article language", async ({ page }) => {
  await page.goto("/blog/");
  await expect(page.locator("header select")).toHaveCount(0);
  const language = page.getByRole("contentinfo").getByRole("combobox");
  await language.selectOption("zh");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("文章");
  await language.selectOption("id");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Artikel");
  await expect(page.getByRole("heading", { level: 2 })).toHaveText(post.title);
  await page.reload();
  await expect(language).toHaveValue("id");
});

test("multiple articles use cards and API errors can be retried", async ({ page }) => {
  await page.route("**/api/blog", route => route.fulfill({ status: 503 }));
  await page.goto("/blog/");
  await expect(page.getByRole("alert")).toBeVisible();
  await page.route("**/api/blog", route => route.fulfill({ json: [
    post,
    { ...post, slug: "second", title: "Second article", href: "/blog/second/" },
    { ...post, slug: "third", title: "Third article", href: "/blog/third/" },
  ] }));
  await page.getByRole("alert").getByRole("button").click();
  await expect(page.locator(".blog-card")).toHaveCount(3);
  await expect(page.locator(".blog-grid .blog-card")).toHaveCount(2);
});

test("empty publications have an explicit empty state", async ({ page }) => {
  await page.route("**/api/blog", route => route.fulfill({ json: [] }));
  await page.goto("/blog/");
  await expect(page.locator(".blog-status")).toContainText("Articles are coming soon");
});

for (const width of [1440, 375, 320]) {
  test(`navigation remains visible and usable while scrolling at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 700 });
    for (const path of ["/blog/", "/blog/relay-day/"]) {
      await page.goto(path);
      const navigation = page.locator("relay-blog-navigation");
      await expect(navigation.getByRole("link", { name: "Articles", exact: true })).toBeVisible();
      for (const position of [0.5, 1]) {
        await page.evaluate(fraction => window.scrollTo(0, (document.documentElement.scrollHeight - innerHeight) * fraction), position);
        await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(0);
        await expect.poll(() => navigation.evaluate(node => node.getBoundingClientRect().top)).toBe(0);
        expect(await navigation.evaluate(node => {
          const box = node.getBoundingClientRect();
          return document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2) === node;
        })).toBe(true);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      }
      if (path === "/blog/relay-day/") {
        // Browser anchor scrolling must leave the destination below the sticky navigation.
        const section = page.locator(".moment").nth(2);
        await section.evaluate(node => node.scrollIntoView());
        await expect.poll(async () => {
          const header = await navigation.boundingBox();
          const target = await section.boundingBox();
          return target!.y >= header!.height;
        }).toBe(true);
        await page.screenshot({ path: testInfo.outputPath("article-sticky.png") });
        await navigation.getByRole("link", { name: "Articles", exact: true }).click();
        await expect(page).toHaveURL(/\/blog\/$/);
        await expect(page.locator(".blog-card")).toHaveCount(1);
      }
    }
  });
}

for (const width of [1440, 375]) {
  for (const colorScheme of ["light", "dark"] as const) {
    test(`original article and card layout at ${width}px in ${colorScheme} mode`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
      const screenshots: Buffer[] = [];
      for (const path of ["/blog/relay-day/", "/__original/index.html"]) {
        await page.goto(path);
        await page.locator("img").evaluateAll(images => images.forEach(image => { image.loading = "eager"; }));
        await expect.poll(() => page.locator("img").evaluateAll(images => images.every(image => image.complete && image.naturalWidth > 0))).toBe(true);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        // Normalize the new header's vertical offset to avoid fractional rasterization differences.
        // Compare the untouched article with its original; navigation is checked separately.
        await page.locator("relay-blog-navigation").evaluateAll(headers => headers.forEach(header => header.remove()));
        screenshots.push(await page.locator(".wrap").screenshot({ animations: "disabled", mask: [page.locator("video")] }));
      }
      expect(Buffer.compare(...screenshots as [Buffer, Buffer])).toBe(0);
      await page.goto("/blog/");
      await expect(page.locator(".blog-card img")).toBeVisible();
      await expect.poll(() => page.locator(".blog-card img").evaluate(image => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath("blog.png"), fullPage: true });
    });
  }
}
