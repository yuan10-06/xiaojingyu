import puppeteer from 'puppeteer-core';
import path from 'node:path';
import fs from 'node:fs';

const edge = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const out = path.join(process.env.TEMP || '.', 'whale-e2e');
fs.mkdirSync(out, { recursive: true });

const results = { checks: {}, apiResponses: [] };
const browser = await puppeteer.launch({
  executablePath: edge,
  headless: 'new',
  args: ['--no-sandbox', '--enable-webgl', '--use-gl=angle', '--use-angle=swiftshader', '--no-first-run', '--no-default-browser-check'],
  defaultViewport: { width: 420, height: 860, deviceScaleFactor: 2, isMobile: true }
});
const page = await browser.newPage();
const consoleLogs = [];
page.on('console', (m) => consoleLogs.push(m.type() + ': ' + m.text()));
page.on('pageerror', (e) => consoleLogs.push('pageerror: ' + e.message));
page.on('response', async (r) => {
  if (r.url().includes('/api/whale/chat')) {
    try { results.apiResponses.push(await r.json()); } catch (e) { /* ignore */ }
  }
});

await page.goto('http://127.0.0.1:8765/whale.html', { waitUntil: 'domcontentloaded', timeout: 30000 });
await new Promise((r) => setTimeout(r, 2500));

// 1. 基础：WhaleAvatar 加载 + canvas 渲染
results.checks.libLoaded = await page.evaluate(() => !!window.WhaleAvatar && !!window.WhaleAvatar.mount);
results.checks.canvas = await page.evaluate(() => {
  const c = document.querySelector('#stage canvas');
  return c ? { w: c.width, h: c.height } : null;
});

// 2. 开场白气泡（1.2s 后 injectReply）
const greeting = await page.evaluate(() => document.getElementById('bubble').textContent);
results.checks.greeting = greeting;
await page.screenshot({ path: path.join(out, '1-loaded.png') });

// 3. 智能 OFF → 本地回复
await page.evaluate(() => {
  localStorage.setItem('whale.smart', '0');
  document.getElementById('smart').checked = false;
});
await page.type('#msg', '你好呀');
await page.click('#send');
await new Promise((r) => setTimeout(r, 1500));
results.checks.localReply = await page.evaluate(() => ({
  bubble: document.getElementById('bubble').textContent,
  shown: document.getElementById('bubble').classList.contains('show')
}));
await page.screenshot({ path: path.join(out, '2-local-reply.png') });

// 4. 智能 ON → API 回复（最多等 35s）
await page.evaluate(() => {
  document.getElementById('smart').checked = true;
  document.getElementById('smart').dispatchEvent(new Event('change'));
  document.getElementById('msg').value = '今天海里好玩吗';
});
await page.click('#send');
const before = results.apiResponses.length;
let apiOk = false;
for (let i = 0; i < 35; i++) {
  await new Promise((r) => setTimeout(r, 1000));
  if (results.apiResponses.length > before) { apiOk = true; break; }
}
await new Promise((r) => setTimeout(r, 800));
results.checks.smartApiCalled = apiOk;
results.checks.smartReply = await page.evaluate(() => ({
  bubble: document.getElementById('bubble').textContent,
  shown: document.getElementById('bubble').classList.contains('show')
}));
await page.screenshot({ path: path.join(out, '3-smart-reply.png') });

// 5. 触摸互动：点头部区域应有反应（气泡不报错即可，主要看 console 无异常）
await page.touchscreen.tap(210, 300);
await new Promise((r) => setTimeout(r, 500));
await page.screenshot({ path: path.join(out, '4-tap.png') });

results.consoleErrors = consoleLogs.filter((l) => l.startsWith('pageerror') || l.startsWith('error'));
results.consoleSample = consoleLogs.slice(0, 12);
console.log(JSON.stringify(results, null, 2));
await browser.close();
