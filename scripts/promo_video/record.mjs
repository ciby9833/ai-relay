import { chromium } from 'playwright';
import fs from 'fs';

const D = JSON.parse(fs.readFileSync('durations.json'));
const L = JSON.parse(fs.readFileSync('lines.json'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const OVERLAY = `
(() => {
  const css = document.createElement('style');
  css.textContent = \`
    #rv-cursor{position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;
      transform:translate(-3px,-2px);transition:transform .08s}
    #rv-cursor.down{transform:translate(-3px,-2px) scale(.85)}
    .rv-ripple{position:fixed;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;
      border:3px solid #c96442;z-index:2147483646;pointer-events:none;animation:rvr .6s ease-out forwards}
    @keyframes rvr{from{opacity:.9;transform:scale(.3)}to{opacity:0;transform:scale(1.6)}}
    #rv-sub{position:fixed;left:50%;bottom:34px;transform:translateX(-50%) translateY(10px);max-width:1000px;
      padding:12px 26px;border-radius:14px;background:rgba(20,20,19,.82);color:#fff;
      font:500 22px/1.5 -apple-system,"PingFang SC",sans-serif;letter-spacing:.02em;text-align:center;
      z-index:2147483645;opacity:0;transition:opacity .35s,transform .35s;pointer-events:none;backdrop-filter:blur(6px)}
    #rv-sub.on{opacity:1;transform:translateX(-50%) translateY(0)}
    #rv-card{position:fixed;inset:0;z-index:2147483640;background:#faf9f5;display:flex;flex-direction:column;
      align-items:center;justify-content:center;gap:22px;opacity:0;transition:opacity .6s;pointer-events:none}
    #rv-card.on{opacity:1}
    #rv-card .mark{width:84px;height:84px;color:#c96442}
    #rv-card h1{font:600 92px/1 "Source Serif 4","Songti SC",Georgia,serif;color:#141413;margin:0;letter-spacing:-.01em}
    #rv-card p{font:400 30px/1.5 -apple-system,"PingFang SC",sans-serif;color:#3d3d3a;margin:0}
    /* 输入框下方的模型名是内部配置，不出现在宣传视频里 */
    .composer-bar select,.composer-bar .composer-hint{visibility:hidden}
    #rv-card small{font:400 20px/1.5 -apple-system,"PingFang SC",sans-serif;color:#73726c;letter-spacing:.06em}
  \`;
  const install = () => {
    if (document.getElementById('rv-cursor')) return;
    document.head.appendChild(css);
    const c = document.createElement('div'); c.id = 'rv-cursor';
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2l15 8.5-6.6 1.6L8.6 19z" fill="#141413" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.appendChild(c);
    const s = document.createElement('div'); s.id = 'rv-sub'; document.body.appendChild(s);
    const k = document.createElement('div'); k.id = 'rv-card'; document.body.appendChild(k);
    window.__rvPos = window.__rvPos || [720, 450];
    c.style.left = window.__rvPos[0] + 'px'; c.style.top = window.__rvPos[1] + 'px';
    document.addEventListener('mousemove', (e) => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    document.addEventListener('mousedown', (e) => { c.classList.add('down');
      const r = document.createElement('div'); r.className = 'rv-ripple'; r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
      document.body.appendChild(r); setTimeout(() => r.remove(), 700); }, true);
    document.addEventListener('mouseup', () => c.classList.remove('down'), true);
  };
  if (document.body) install(); else document.addEventListener('DOMContentLoaded', install);
  window.rvSub = (t) => { const s = document.getElementById('rv-sub'); if (!t) { s.classList.remove('on'); return; } s.textContent = t; s.classList.add('on'); };
  window.rvCard = (html) => { const k = document.getElementById('rv-card'); if (!html) { k.classList.remove('on'); return; } k.innerHTML = html; k.classList.add('on'); };
})();
`;

const MARK = '<svg class="mark" viewBox="0 0 24 24"><path d="M12 2c.6 4.8 2.6 8.8 10 10-7.4 1.2-9.4 5.2-10 10-.6-4.8-2.6-8.8-10-10 7.4-1.2 9.4-5.2 10-10z" fill="currentColor"/></svg>';

const browser = await chromium.launch({ channel: 'chrome', args: ['--headless=new', '--window-size=1440,900', '--force-device-scale-factor=2'] });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, locale: 'zh-CN' });
await ctx.addInitScript(OVERLAY);
const p = await ctx.newPage();
await p.goto('http://localhost:5173');
await p.waitForTimeout(800);
// 先登录好，录制从首页开始
await p.evaluate(() => window.rvCard('<div></div>'));
await p.getByText('本地调试登录').click();
await p.waitForTimeout(2500);
await p.evaluate((m) => window.rvCard(m), `${MARK}<h1>Relay</h1><p>你在公司里的 AI 助理</p>`);
await p.waitForTimeout(800);

// ---- 录制 ----
const cdp = await ctx.newCDPSession(p);
const frames = [];
cdp.on('Page.screencastFrame', async (f) => {
  frames.push({ t: f.metadata.timestamp, data: f.data });
  try { await cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }); } catch {}
});
await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 90, maxWidth: 2880, maxHeight: 1800 });
await sleep(300);
const marks = {}; // 各段起始时间（秒，wall clock）
const now = () => Date.now() / 1000;

let mouse = [720, 450];
async function moveTo(x, y, ms = 700) {
  const steps = Math.max(10, Math.round(ms / 16));
  const [x0, y0] = mouse;
  for (let i = 1; i <= steps; i++) {
    const k = i / steps, e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    await p.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e);
    await sleep(ms / steps);
  }
  mouse = [x, y];
}
async function moveToEl(loc, ms) {
  const b = await loc.boundingBox();
  await moveTo(b.x + Math.min(b.width / 2, 120), b.y + b.height / 2, ms);
}
async function click(loc, ms) { await loc.scrollIntoViewIfNeeded().catch(() => {}); await sleep(150); await moveToEl(loc, ms); await sleep(150); await p.mouse.down(); await sleep(90); await p.mouse.up(); }
async function smoothScroll(sel, dy, ms = 900) {
  await p.evaluate(([s, d, m]) => new Promise((res) => {
    const el = s ? document.querySelector(s) : document.scrollingElement; const start = el.scrollTop, t0 = performance.now();
    const step = (t) => { const k = Math.min(1, (t - t0) / m); const e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      el.scrollTop = start + d * e; if (k < 1) requestAnimationFrame(step); else res(); };
    requestAnimationFrame(step);
  }), [sel, dy, ms]);
}
async function scene(key, body, { pad = 0.7, sub = true } = {}) {
  const t0 = now(); marks[key] = t0;
  if (sub) await p.evaluate((t) => window.rvSub(t), L[key]);
  await body();
  const left = t0 + D[key] + pad - now();
  if (left > 0) await sleep(left * 1000);
}
const sub = (t) => p.evaluate((x) => window.rvSub(x), t);

// 找到主线滚动容器
const threadSel = await p.evaluate(() => {
  const els = [...document.querySelectorAll('*')].filter((e) => { const s = getComputedStyle(e); return /(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 20; });
  els.sort((a, b) => b.clientWidth * b.clientHeight - a.clientWidth * a.clientHeight);
  const el = els[0]; if (!el) return null; el.setAttribute('data-rv-thread', ''); return '[data-rv-thread]';
});

// 1. 片头
await scene('intro', async () => { await sleep(400); }, { sub: false, pad: 1.0 });
await p.evaluate(() => window.rvCard(null));
await sleep(700);

// 2. 看板
await scene('board', async () => {
  await sleep(600);
  await moveTo(560, 140, 900); await sleep(900);
  await moveTo(1080, 140, 900); await sleep(900);
  await moveTo(1300, 140, 800);
});

// 3. 紧急事项展开
await scene('urgent', async () => {
  await click(p.locator('.board-row').filter({ hasText: 'JT-SG2417' }).first(), 800);
  await sleep(1200);
  await moveTo(620, 360, 900);
});

// 4. 草稿 + 确认
await scene('confirm', async () => {
  const board = p.locator('.board');
  const sc = await p.evaluate(() => { const o = document.querySelector('.board-open'); const s = o && [...o.querySelectorAll('*')].concat([o]).find((e) => /(auto|scroll)/.test(getComputedStyle(e).overflowY) && e.scrollHeight > e.clientHeight + 10); if (s) { s.setAttribute('data-rv-open', ''); return '[data-rv-open]'; } const b = document.querySelector('.board-columns'); if (b && b.scrollHeight > b.clientHeight + 10) { b.setAttribute('data-rv-open',''); return '[data-rv-open]'; } return null; });
  if (sc) await smoothScroll(sc, 420, 1200);
  await sleep(500);
  const btn = p.locator('.board button').filter({ hasText: '确认发送' }).first();
  if (await btn.count()) await moveToEl(btn, 900);
  await sleep(1200);
});

// 5. 压价建议
await scene('advice', async () => {
  await click(p.locator('.board-collapse').first(), 700);
  await sleep(300);
  await p.evaluate(() => document.querySelectorAll('[data-rv-open]').forEach((e) => (e.scrollTop = 0)));
  await sleep(300);
  await click(p.locator('.board-row').filter({ hasText: 'Rudi' }).first(), 800);
  await sleep(400);
  await p.locator('.board-open').first().scrollIntoViewIfNeeded().catch(() => {});
  await sleep(600);
  const rec = p.getByText('按历史毛利').first();
  if (await rec.count()) await moveToEl(rec, 800);
});

// 6. 直接问
let sentAt, doneAt;
await scene('ask', async () => {
  await click(p.locator('.board-collapse').first(), 600);
  await sleep(300);
  await click(p.locator('.board-toggle'), 700);
  await sleep(500);
  const ta = p.locator('textarea').last();
  await click(ta, 700);
  await ta.pressSequentially('今天最要紧的三件事是什么？按优先级说，简短一点。', { delay: 70 });
  await sleep(300);
});
const copies = await p.getByText('复制全文').count();
await p.keyboard.press('Enter');
await p.evaluate(() => document.activeElement && document.activeElement.blur());
await moveTo(1250, 620, 600);
sentAt = now() + 2.5;
await p.waitForFunction((n) => [...document.querySelectorAll('button')].filter((b) => b.textContent.includes('复制全文')).length > n, copies, { timeout: 120000, polling: 300 });
// 等流式输出稳定 1.5 秒
let last = -1, stable = 0;
while (stable < 5) { const n = await p.evaluate(() => document.body.innerText.length); stable = n === last ? stable + 1 : 0; last = n; await sleep(300); }
doneAt = now() - 1.0;
await sleep(600);

// 7. 多语言
await scene('lang', async () => {
  if (threadSel) await smoothScroll(threadSel, 2000, 800);
  await sleep(800);
  await moveTo(900, 700, 1200);
}, { pad: 1.6 });

// 8. 长期任务
await scene('mission', async () => {
  await click(p.locator('nav, aside').getByText('长期任务').first(), 900);
  await sleep(1000);
  await click(p.getByText('查看进展').first(), 800);
  await sleep(1200);
  await moveTo(760, 560, 900);
  await sleep(600);
  await moveTo(820, 600, 700);
});

// 9. 记忆
await scene('memory', async () => {
  await click(p.getByText('记忆').first(), 900);
  await sleep(800);
  await moveTo(1180, 230, 900);
});

// 10. 片尾
await p.evaluate(() => window.rvSub(null));
await p.keyboard.press('Escape');
await sleep(500);
await scene('outro', async () => {
  await p.evaluate((m) => window.rvCard(m), `${MARK}<h1>Relay</h1><p>让每件事，都有人跟进</p><small>网页端 · 飞书机器人 · 中文 / English / Bahasa Indonesia</small>`);
}, { sub: false, pad: 2.0 });
const endAt = now();
await cdp.send('Page.stopScreencast');
await browser.close();

fs.mkdirSync('frames', { recursive: true });
for (const f of fs.readdirSync('frames')) fs.unlinkSync('frames/' + f);
frames.forEach((f, i) => fs.writeFileSync(`frames/${String(i).padStart(5, '0')}.jpg`, Buffer.from(f.data, 'base64')));
fs.writeFileSync('timeline.json', JSON.stringify({ frames: frames.map((f) => f.t), marks, sentAt, doneAt, endAt }));
console.log('frames', frames.length, 'wait', (doneAt - sentAt).toFixed(1), 's');
