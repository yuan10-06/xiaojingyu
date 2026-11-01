import puppeteer from 'puppeteer-core';
import path from 'node:path';
import fs from 'node:fs';

const edge = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const out = path.join(process.env.TEMP || '.', 'p3-check');
fs.mkdirSync(out, { recursive: true });
const browser = await puppeteer.launch({
  executablePath: edge,
  headless: 'new',
  args: ['--no-sandbox', '--enable-webgl', '--use-gl=angle', '--use-angle=swiftshader',
    '--no-first-run', '--no-default-browser-check', '--js-flags=--expose-gc'],
  defaultViewport: { width: 768, height: 1024, deviceScaleFactor: 1 }
});
const page = await browser.newPage();
page.on('pageerror', (e) => console.log('pageerror:', e.message));

await page.goto('http://127.0.0.1:5173/', { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForFunction('window.__live2dInfo && window.__live2dInfo.parameterCount > 0', { timeout: 30000 });
console.log('model ready');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sample = (ms, keys, step = 60) => new Promise(async (resolve) => {
  const arr = [];
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const s = await page.evaluate((ks) => {
      const d = window.__avatar.debugSample?.() || {};
      const o = {};
      for (const k of ks) o[k] = d[k];
      return o;
    }, keys);
    arr.push({ t: Date.now() - t0, ...s });
    await new Promise((r) => setTimeout(r, step));
  }
  resolve(arr);
});
const tapHead = () => page.evaluate(() => window.__simulateTap(window.innerWidth * 0.46, window.innerHeight * 0.17));
const setState = (v, a) => page.evaluate(({ v, a }) => window.__mockSoul.setState(v, a), { v, a });
const setAffinity = (x) => page.evaluate((k) => window.__mockSoul.setAffinity(k), x);

// ---- A：affinity 差异 ----
await setState(0, 0);
await setAffinity(0.05);
await sleep(4500);
await tapHead();
const lowAff = await sample(1100, ['ParamAngleY']);
const peakLow = Math.min(...lowAff.map((p) => p.ParamAngleY)); // headY kick 为负（躲闪）
await page.screenshot({ path: path.join(out, 'affinity-low.png') });

await setAffinity(0.95);
await sleep(5000);
await tapHead();
const highAff = await sample(1100, ['ParamAngleY']);
const peakHigh = Math.min(...highAff.map((p) => p.ParamAngleY));
await page.screenshot({ path: path.join(out, 'affinity-high.png') });

// ---- B：记忆微表情 ----
await sleep(2000);
await page.evaluate(() => window.__mockSoul.mockRecall(0.95));
const rec = await sample(4500, ['ParamBrowLY']);
const recPeak = Math.max(...rec.map((p) => p.ParamBrowLY));
const recTail = rec.filter((p) => p.t > 3800).map((p) => p.ParamBrowLY);
const recTailMean = recTail.length ? recTail.reduce((a, b) => a + b, 0) / recTail.length : 0;

// ---- C：说话 + 打断惊愕 ----
await page.evaluate(() => window.__mockSoul.mockSpeak('今天天气真好我们一起去海边散步吧'));
const talking = await sample(1000, ['ParamMouthOpenY']);
const mouthMax = Math.max(...talking.map((p) => p.ParamMouthOpenY));

await page.evaluate(() => window.__mockSoul.mockSpeak('再陪我多说一会儿话嘛好不好'));
await sleep(400);
await tapHead();
const startle = await sample(1600, ['ParamBrowLY']);
await page.screenshot({ path: path.join(out, 'startle.png') });
const startlePeak = Math.max(...startle.map((p) => p.ParamBrowLY));

// ---- D：mount/destroy 内存 ----
await page.evaluate(() => window.__mockSoul.setAffinity(0.5));
const heaps = [];
for (let i = 0; i < 8; i++) {
  await page.evaluate(() => window.__remount());
  await page.evaluate(() => { window.gc?.(); });
  await sleep(300);
  await page.evaluate(() => { window.gc?.(); });
  const m = await page.metrics();
  heaps.push(Math.round(m.JSHeapUsedSize / 1048576 * 10) / 10);
}
const heapGrow = heaps[7] - heaps[1];

const report = {
  A_affinity: {
    lowAffinityDodge: Number(peakLow.toFixed(2)),
    highAffinityDodge: Number(peakHigh.toFixed(2)),
    pass: Math.abs(peakLow) > Math.abs(peakHigh) * 1.15
  },
  B_recall: {
    browPeak: Number(recPeak.toFixed(3)),
    tailMean: Number(recTailMean.toFixed(3)),
    pass: recPeak > 0.12 && recTailMean < recPeak * 0.5
  },
  C_startle: {
    mouthWhileSpeaking: Number(mouthMax.toFixed(3)),
    startleBrowPeak: Number(startlePeak.toFixed(3)),
    pass: mouthMax > 0.15 && startlePeak > 0.2
  },
  D_memory: {
    heapsMB: heaps,
    growFrom2ndMB: Number(heapGrow.toFixed(1)),
    pass: heapGrow < 25
  }
};
console.log(JSON.stringify(report, null, 2));
await browser.close();
