/** Deterministic exports from the same original SVG used by the live mascot.
 * Run: node scripts/build-icons.mjs (requires Playwright Chromium).
 * No downloaded artwork. PNG/ICO/ICNS only for OS formats without SVG support.
 */
import { chromium } from '@playwright/test';
import { writeFile, readFile, mkdir, mkdtemp, rm, access } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import os from 'node:os';
import { execFileSync } from 'node:child_process';
import { renderRelaySvg } from '../src/mascot/engine.js';
const root = fileURLToPath(new URL('../', import.meta.url));
const publicDir = path.join(root, 'public');
const desktop = path.resolve(root, '../desktop/build');
const svg = renderRelaySvg();
await writeFile(path.join(publicDir, 'favicon.svg'), svg);
await writeFile(path.join(publicDir, 'relay-mark.svg'), svg);
const navPath = path.join(publicDir, 'blog-navigation.js');
const nav = await readFile(navPath, 'utf8');
// Replace only the brand slot, not the navigation's functional icons.
const mark = svg.replace('<svg ', '<svg class="mark" ');
await writeFile(navPath, nav.replace(/<svg class="mark"[\s\S]*?<\/svg>/, mark));
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ deviceScaleFactor: 1, colorScheme: 'light', reducedMotion: 'reduce' });
  async function raster(size, { opaque = false, monochrome = false } = {}) {
    await page.setViewportSize({ width: size, height: size });
    const art = renderRelaySvg({ monochrome });
    await page.setContent(`<style>html,body{margin:0;width:100%;height:100%;background:${opaque ? '#faf9f5' : 'transparent'}}svg{width:100%;height:100%}</style>${art}`);
    return page.screenshot({ omitBackground: !opaque });
  }
  await writeFile(path.join(publicDir, 'apple-touch-icon.png'), await raster(180, { opaque: true }));
  const sizes = [16, 32, 48];
  const frames = [];
  for (const size of sizes) frames.push(await raster(size));
  const header = Buffer.alloc(6 + 16 * frames.length);
  header.writeUInt16LE(1, 2); header.writeUInt16LE(frames.length, 4);
  let offset = header.length;
  frames.forEach((frame, i) => {
    const entry = 6 + 16 * i;
    header[entry] = sizes[i]; header[entry + 1] = sizes[i];
    header.writeUInt16LE(1, entry + 4); header.writeUInt16LE(32, entry + 6);
    header.writeUInt32LE(frame.length, entry + 8); header.writeUInt32LE(offset, entry + 12);
    offset += frame.length;
  });
  await writeFile(path.join(publicDir, 'favicon.ico'), Buffer.concat([header, ...frames]));
  try { await access(desktop); } catch { await mkdir(desktop, { recursive: true }); }
  await writeFile(path.join(desktop, 'icon.png'), await raster(1024));
  await writeFile(path.join(desktop, 'trayTemplate.png'), await raster(18, { monochrome: true }));
  await writeFile(path.join(desktop, 'trayTemplate@2x.png'), await raster(36, { monochrome: true }));
  if (process.platform === 'darwin') {
    const temp = await mkdtemp(path.join(os.tmpdir(), 'relay-icons-'));
    const iconset = path.join(temp, 'Relay.iconset');
    await mkdir(iconset);
    try {
      for (const size of [16, 32, 128, 256, 512]) for (const scale of [1, 2]) {
        await writeFile(path.join(iconset, `icon_${size}x${size}${scale === 2 ? '@2x' : ''}.png`), await raster(size * scale));
      }
      execFileSync('iconutil', ['-c', 'icns', iconset, '-o', path.join(desktop, 'icon.icns')]);
    } finally { await rm(temp, { recursive: true, force: true }); }
  }
} finally { await browser.close(); }
console.log('Updated SVG, browser/touch icons and desktop icons from the Relay mascot.');
