import puppeteer from 'puppeteer-core';
import path from 'node:path';
import fs from 'node:fs';

const edge = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const out = path.join(process.env.TEMP || '.', 'p0-check');
fs.mkdirSync(out, { recursive: true });
const browser = await puppeteer.launch({
  executablePath: edge,
  headless: 'new',
  args: ['--no-sandbox', '--enable-webgl', '--use-gl=angle', '--use-angle=swiftshader', '--no-first-run', '--no-default-browser-check'],
  defaultViewport: { width: 768, height: 1024, deviceScaleFactor: 1 }
});
const page = await browser.newPage();
const consoleLogs = [];
page.on('console', (message) => consoleLogs.push(message.type() + ': ' + message.text()));
page.on('pageerror', (error) => consoleLogs.push('pageerror: ' + error.message));
console.log('browser launched');

await page.goto('http://127.0.0.1:5173/', { waitUntil: 'domcontentloaded', timeout: 60000 });
console.log('page navigated');
await page.waitForFunction('window.__live2dInfo && window.__live2dInfo.parameterCount > 0', { timeout: 30000 });
const info = await page.evaluate(() => ({
  coreVersion: window.__live2dInfo.coreVersion,
  parameterCount: window.__live2dInfo.parameterCount,
  drawableCount: window.__live2dInfo.drawableCount,
  partCount: window.__live2dInfo.partCount
}));
const size = await page.evaluate(() => ({ w: window.innerWidth, h: window.innerHeight }));
await page.evaluate(() => { window.__avatarEvents.length = 0; });

const tap = async (x, y, wait = 120) => {
  await page.evaluate(({ x, y }) => window.__simulateTap(x, y), { x, y });
  await new Promise((resolve) => setTimeout(resolve, wait));
};

const spots = {
  head: [size.w * 0.46, size.h * 0.17],
  body: [size.w * 0.46, size.h * 0.49],
  tail: [size.w * 0.72, size.h * 0.49],
  legs: [size.w * 0.46, size.h * 0.72]
};

for (const [name, point] of Object.entries(spots)) {
  await page.evaluate(() => { window.__avatarEvents.length = 0; });
  await tap(point[0], point[1], 80);
  await page.screenshot({ path: path.join(out, name + '.png') });
  await new Promise((resolve) => setTimeout(resolve, 400));
}

await page.evaluate(() => { window.__avatarEvents.length = 0; });
await page.evaluate(({ w, h }) => {
  window.__simulateDrag(w * 0.46, h * 0.50, w * 0.62, h * 0.50);
}, size);
await new Promise((resolve) => setTimeout(resolve, 150));
await page.screenshot({ path: path.join(out, 'drag.png') });
await new Promise((resolve) => setTimeout(resolve, 600));

const events = await page.evaluate(() => window.__avatarEvents);
const hud = await page.evaluate(() => document.getElementById('hud')?.innerText);
console.log(JSON.stringify({ info, size, events, hud, consoleLogs }, null, 2));
await browser.close();
