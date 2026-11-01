import puppeteer from 'puppeteer-core';
import path from 'node:path';
import fs from 'node:fs';

const edge = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const out = path.join(process.env.TEMP || '.', 'p2-check');
fs.mkdirSync(out, { recursive: true });
const browser = await puppeteer.launch({
  executablePath: edge,
  headless: 'new',
  args: ['--no-sandbox', '--enable-webgl', '--use-gl=angle', '--use-angle=swiftshader', '--no-first-run', '--no-default-browser-check'],
  defaultViewport: { width: 768, height: 1024, deviceScaleFactor: 1 }
});
const page = await browser.newPage();
page.on('pageerror', (e) => console.log('pageerror:', e.message));

await page.goto('http://127.0.0.1:5173/', { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForFunction('window.__live2dInfo && window.__live2dInfo.parameterCount > 0', { timeout: 30000 });
console.log('model ready');

const sample = (ms, key) => new Promise(async (resolve) => {
  const arr = [];
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const s = await page.evaluate((k) => window.__avatar.debugSample?.()[k], key);
    arr.push({ t: Date.now() - t0, v: s });
    await new Promise((r) => setTimeout(r, 100));
  }
  resolve(arr);
});
const setState = (v, a) => page.evaluate(({ v, a }) => window.__mockSoul.setState(v, a), { v, a });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- 场景 A：valence 跳变 → MouthForm 缓降无跳变 ----
await setState(0.9, 0);
await sleep(5000); // 稳定到 +0.5 左右
await page.screenshot({ path: path.join(out, 'valence-pos.png') });
const before = await page.evaluate(() => window.__avatar.debugSample?.().ParamMouthForm);
await setState(-0.9, 0);
const trackA = await sample(7000, 'ParamMouthForm');
await page.screenshot({ path: path.join(out, 'valence-neg.png') });

const deltas = trackA.slice(1).map((p, i) => Math.abs(p.v - trackA[i].v));
const maxDelta = Math.max(...deltas);
const crossUp = trackA.find((p) => p.v < 0.4 * 0.55 * 2 - 1); // 找 +0.44→-0.44 穿越
const i40p = trackA.findIndex((p) => p.v < 0.35);
const i40n = trackA.findIndex((p, i) => i > i40p && p.v < -0.35);
const crossMs = i40p >= 0 && i40n >= 0 ? trackA[i40n].t - trackA[i40p].t : -1;
const finalA = trackA[trackA.length - 1].v;

// ---- 场景 B：arousal → 呼吸快慢 ----
await setState(0, -0.8);
await sleep(3500);
const breathLow = await sample(22000, 'ParamBreath');
await setState(0, 0.9);
await sleep(3500);
const breathHigh = await sample(22000, 'ParamBreath');

const peakIntervals = (arr) => {
  const peaks = [];
  for (let i = 2; i < arr.length - 2; i++) {
    if (arr[i].v >= arr[i - 1].v && arr[i].v > arr[i + 1].v && arr[i].v > arr[i - 2].v && arr[i].v >= arr[i + 2].v) {
      if (!peaks.length || i - peaks[peaks.length - 1] > 8) peaks.push(i);
    }
  }
  return peaks.slice(1).map((p, k) => arr[p].t - arr[peaks[k]].t);
};
const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
const lowInt = mean(peakIntervals(breathLow));
const highInt = mean(peakIntervals(breathHigh));

// ---- 场景 C：sendUserInput → 情绪冲击 → 残留缓降 ----
await setState(0, 0);
await sleep(4000);
await page.evaluate(() => window.__avatar.sendUserInput('喜欢你，真可爱'));
const trackC = await sample(14000, 'ParamMouthForm');
const peakC = Math.max(...trackC.map((p) => p.v));
const peakIdx = trackC.findIndex((p) => p.v === peakC);
const at8s = trackC.find((p) => p.t >= trackC[peakIdx].t + 8000);

const report = {
  A: {
    mouthBefore: Number(before?.toFixed(3)),
    mouthFinal: Number(finalA?.toFixed(3)),
    maxFrameDelta: Number(maxDelta.toFixed(4)),
    crossMs,
    pass: before > 0.3 && finalA < -0.3 && maxDelta < 0.06 && crossMs > 1500 && crossMs < 7000
  },
  B: {
    lowArousalBreathMs: Math.round(lowInt),
    highArousalBreathMs: Math.round(highInt),
    pass: highInt > 0 && lowInt > 0 && highInt < lowInt * 0.88
  },
  C: {
    peak: Number(peakC.toFixed(3)),
    after8s: at8s ? Number(at8s.v.toFixed(3)) : null,
    pass: peakC > 0.15 && at8s && at8s.v < peakC * 0.55
  }
};
console.log(JSON.stringify(report, null, 2));
await browser.close();
