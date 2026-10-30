import { test, expect, type Page } from '@playwright/test';
import { EMOTIONS, SHAPES, resolveEmotion, resolveShape, renderRelaySvg } from '../src/mascot/engine.js';
import { messageEmotion } from '../src/mascot/state';
import type { Action, ThreadMessage } from '../src/api';
const assistant: ThreadMessage = { id: 1, role: 'assistant', text: '' };

test('state hints cannot override errors, approvals or claim completion', () => {
  expect(Object.keys(EMOTIONS)).toHaveLength(22);
  expect(Object.keys(SHAPES)).toEqual(['blob', 'wedge', 'gem']);
  for (const value of [null, undefined, '__proto__', '<script>', {}, 30]) expect(resolveEmotion(value)).toBe('idle');
  expect(resolveShape('unknown')).toBe('blob');
  expect(messageEmotion({ ...assistant, pending: true, emotionId: 'completed' })).toBe('thinking');
  expect(messageEmotion({ ...assistant, pending: true, activeTool: 'search_mail' })).toBe('searching');
  expect(messageEmotion({ ...assistant, pending: true, activeTool: 'create_file' })).toBe('working');
  expect(messageEmotion({ ...assistant, pending: true, toolFailed: true })).toBe('error');
  expect(messageEmotion({ ...assistant, pending: true, text: 'Answer' })).toBe('speaking');
  expect(messageEmotion({ ...assistant, error: 'Network', emotionId: 'happy' })).toBe('error');
  const action = { id: 1, status: 'pending' } as Action;
  expect(messageEmotion({ ...assistant, emotionId: 'completed', cards: [{ kind: 'draft', action_id: 1, action }] })).toBe('waiting_approval');
  expect(messageEmotion({ ...assistant, cards: [{ kind: 'action', action_id: 1, action: { ...action, status: 'done' } }] })).toBe('completed');
  expect(messageEmotion({ ...assistant, emotionId: 'completed' })).toBe('idle');
  for (const shape of Object.keys(SHAPES)) {
    const source = renderRelaySvg({ shape });
    expect(source).not.toMatch(/<image|<foreignObject|<script|data-part="(?:mouth|nose)"/);
    expect(source.match(/data-eye=/g)).toHaveLength(2);
  }
});
async function nativeFixture(page: Page) {
  await page.route('**/mascot-fixture', route => route.fulfill({ contentType: 'text/html', body: '<html><body><div id="native" style="width:96px;height:96px"></div></body></html>' }));
  await page.goto('/mascot-fixture');
  await page.evaluate(async () => {
    const { createRelayMascot } = await import('/src/mascot/engine.js');
    (window as any).mascot = createRelayMascot(document.querySelector('#native'));
  });
}
test('standalone native engine handles all expressions and shapes and malformed AI data', async ({ page }) => {
  await nativeFixture(page);
  for (const shape of Object.keys(SHAPES)) {
    await page.evaluate(value => (window as any).mascot.setShape(value), shape);
    for (const emotionId of Object.keys(EMOTIONS)) {
      await page.evaluate(value => (window as any).mascot.handleAIMessage(JSON.stringify({ emotionId: value })), emotionId);
      await expect(page.locator('#native svg')).toHaveAttribute('data-relay-mascot', emotionId);
      await expect(page.locator('#native svg')).toHaveAttribute('data-shape', shape);
    }
  }
  await page.evaluate(async () => {
    const { createRelayMascot } = await import('/src/mascot/engine.js');
    const second = document.createElement('div'); second.id = 'second'; document.body.append(second);
    (window as any).second = createRelayMascot(second, { emotionId: 'happy', animated: false });
    (window as any).mascot.handleAIMessage('{not-json');
  });
  await expect(page.locator('#native')).toHaveAttribute('data-emotion', 'idle');
  await expect(page.locator('#second')).toHaveAttribute('data-emotion', 'happy');
  await page.evaluate(() => (window as any).mascot.handleAIMessage({ emotionId: '<img src=x onerror=alert(1)>' }));
  await expect(page.locator('#native img')).toHaveCount(0);
  expect(await page.locator('#native .shell').evaluate(el => getComputedStyle(el).fill)).toBe('rgb(201, 100, 66)');
});
test('animations stop for reduced motion, offscreen content and destruction', async ({ page }) => {
  await nativeFixture(page);
  await expect.poll(() => page.evaluate(() => document.getAnimations().length)).toBeGreaterThan(0);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect.poll(() => page.evaluate(() => document.getAnimations().length)).toBe(0);
  await page.evaluate(() => (window as any).mascot.setEmotion('searching'));
  await expect(page.locator('#native')).toHaveAttribute('data-emotion', 'searching');
  expect(await page.evaluate(() => document.getAnimations().length)).toBe(0);
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await expect.poll(() => page.evaluate(() => document.getAnimations().length)).toBeGreaterThan(0);
  expect(await page.evaluate(() => {
    const gaze = document.querySelector('#native [data-part="gaze"]')!;
    const animation = gaze.getAnimations()[0];
    animation.pause(); animation.currentTime = 0;
    const before = getComputedStyle(gaze).transform;
    animation.currentTime = 1100;
    return before !== getComputedStyle(gaze).transform;
  })).toBe(true);
  await page.locator('#native').evaluate(el => { (el as HTMLElement).style.display = 'none'; });
  await expect.poll(() => page.evaluate(() => document.getAnimations().length)).toBe(0);
  await page.locator('#native').evaluate(el => { (el as HTMLElement).style.display = 'block'; });
  await expect.poll(() => page.evaluate(() => document.getAnimations().length)).toBeGreaterThan(0);
  await page.evaluate(() => { (window as any).mascot.destroy(); (window as any).mascot.setEmotion('happy'); });
  await expect(page.locator('#native svg')).toHaveCount(0);
  expect(await page.evaluate(() => document.getAnimations().length)).toBe(0);
});
for (const [locale, width, theme] of [['zh', 1440, 'light'], ['en', 375, 'dark'], ['id', 320, 'light']] as const) {
  test(`gallery at ${width}px in ${locale}/${theme}`, async ({ page }, info) => {
    await page.addInitScript(value => localStorage.setItem('relay.ui-language', value), locale);
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/mascot');
    await page.locator('.mascot-stage select').nth(1).selectOption(theme);
    await page.locator('.mascot-playback button').first().click();
    await expect(page.locator('.mascot-expression')).toHaveCount(22);
    for (const shape of ['blob', 'wedge', 'gem']) {
      await page.locator('.mascot-stage select').first().selectOption(shape);
      await expect(page.locator('.mascot-stage-avatar svg')).toHaveAttribute('data-shape', shape);
    }
    await page.locator('.mascot-stage select').first().selectOption('blob');
    await page.locator('.mascot-expression').filter({ hasText: 'waiting_approval' }).click();
    await expect(page.locator('.mascot-stage-avatar svg')).toHaveAttribute('data-relay-mascot', 'waiting_approval');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const fill = await page.locator('.mascot-stage-avatar .shell').evaluate(el => getComputedStyle(el).fill);
    expect(fill).toBe(theme === 'dark' ? 'rgb(223, 137, 107)' : 'rgb(201, 100, 66)');
    await page.screenshot({ path: info.outputPath(`gallery-${locale}-${theme}.png`), fullPage: true });
  });
}
async function mockApp(page: Page, signedIn = true) {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/me') return route.fulfill({ status: signedIn ? 200 : 401, json: signedIn ? { id: 'test', name: 'Ellis', is_admin: false } : {} });
    if (path === '/api/auth/config') return route.fulfill({ json: { dev_login: false } });
    if (path === '/api/home') return route.fulfill({ json: { conversation: { id: 'home' }, messages: [], status: { source_errors: 0 } } });
    if (path === '/api/board') return route.fulfill({ json: { me: [], others: [], relay: [] } });
    if (path === '/api/meetings') return route.fulfill({ json: { upcoming: [], recent: [] } });
    if (path === '/api/progress') return route.fulfill({ json: { days: [], notes: [] } });
    return route.fulfill({ json: [] });
  });
}
test('login, sidebar, mobile header and browser icons use the new identity', async ({ page }, info) => {
  await mockApp(page, false);
  await page.goto('/');
  await expect(page.locator('.login-card .relay-mark svg')).toHaveAttribute('data-shape', 'blob');
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.screenshot({ path: info.outputPath('login-dark-mobile.png'), fullPage: true });
  for (const url of ['/favicon.svg?v=pip1', '/favicon.ico?v=pip1', '/apple-touch-icon.png?v=pip1', '/relay-mark.svg']) {
    const result = await page.request.get(url); expect(result.ok()).toBe(true); expect((await result.body()).length).toBeGreaterThan(100);
  }
  const svg = await (await page.request.get('/favicon.svg')).text();
  expect(svg).toContain('data-relay-mascot="idle"'); expect(svg).toContain('prefers-color-scheme:dark');
  await mockApp(page);
  await page.goto('/');
  await expect(page.locator('.mobile-bar .relay-mark svg')).toHaveAttribute('data-shape', 'blob');
  await page.locator('.mobile-bar button').click();
  await expect(page.locator('.brand .relay-mark svg')).toHaveAttribute('data-shape', 'blob');
});
test('live tool events drive chat and sidebar; errors remain visible', async ({ page }) => {
  await mockApp(page);
  await page.addInitScript(() => {
    const original = window.fetch;
    window.fetch = async (input, options) => {
      if (String(input).endsWith('/messages') && options?.method === 'POST') {
        const body = new ReadableStream({ start(controller) {
          (window as any).emit = (event: unknown) => controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
          (window as any).finish = () => controller.close();
        } });
        return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } });
      }
      return original(input, options);
    };
  });
  await page.goto('/');
  await page.locator('.composer textarea').fill('Find my email');
  await page.locator('.send').click();
  const mark = page.locator('.msg.assistant .relay-mark').last();
  await expect(mark).toHaveAttribute('data-emotion', 'thinking');
  for (const [event, expected] of [
    [{ type: 'emotion', emotionId: 'completed' }, 'thinking'],
    [{ type: 'tool_start', name: 'search_mail' }, 'searching'],
    [{ type: 'tool_end', name: 'search_mail', ok: false }, 'error'],
    [{ type: 'tool_start', name: 'create_file' }, 'working'],
    [{ type: 'tool_end', name: 'create_file', ok: true }, 'thinking'],
    [{ type: 'text', delta: 'Here is what I found.' }, 'speaking'],
    [{ type: 'error', message: 'Network unavailable' }, 'error'],
  ] as const) {
    await page.evaluate(value => (window as any).emit(value), event);
    await expect(mark).toHaveAttribute('data-emotion', expected);
    await expect(page.locator('.brand .relay-mark')).toHaveAttribute('data-emotion', expected);
  }
  await page.evaluate(() => (window as any).finish());
  await expect(page.getByText('Network unavailable', { exact: true })).toBeVisible();
  await expect(mark).toHaveAttribute('data-emotion', 'error');
});
