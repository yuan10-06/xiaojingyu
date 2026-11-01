import puppeteer from 'puppeteer-core';
import path from 'node:path';
import fs from 'node:fs';

const edge = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const out = path.join(process.env.TEMP || '.', 'p1-check');
fs.mkdirSync(out, { recursive: true });
const browser = await puppeteer.launch({
  executablePath: edge,
  headless: 'new',
  args: ['--no-sandbox', '--enable-webgl', '--use-gl=angle', '--use-angle=swiftshader', '--no-first-run', '--no-default-browser-check'],
  defaultViewport: { width: 768, height: 1024, deviceScaleFactor: 1 }
});
const page = await browser.newPage();
const consoleLogs = [];
page.on('console', (m) => consoleLogs.push(m.type() + ': ' + m.text()));
page.on('pageerror', (e) => consoleLogs.push('pageerror: ' + e.message));

await page.goto('http://127.0.0.1:5173/', { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForFunction('window.__live2dInfo && window.__live2dInfo.parameterCount > 0', { timeout: 30000 });
console.log('model ready, sampling 65s...');

// 静置采样 65s（不交互，纯观察生命感）。
const DURATION = 65000;
const samples = [];
const t0 = Date.now();
let shotIdx = 0;
const shotAt = [0, 20000, 40000, 62000];
while (Date.now() - t0 < DURATION) {
  const elapsed = Date.now() - t0;
  const s = await page.evaluate(() => ({ t: performance.now(), ...(window.__avatar.debugSample?.() || {}) }));
  samples.push(s);
  if (shotIdx < shotAt.length && elapsed >= shotAt[shotIdx]) {
    await page.screenshot({ path: path.join(out, 'idle-' + shotAt[shotIdx] / 1000 + 's.png') });
    shotIdx++;
  }
  await new Promise((r) => setTimeout(r, 100));
}
console.log('samples:', samples.length);

// ---- 分析 ----
const series = (k) => samples.map((s) => s[k]).filter((v) => typeof v === 'number');
const stats = (arr) => {
  const mean = arr.reduce((a, b) => a + b, 0) / arr.length;
  const std = Math.sqrt(arr.reduce((a, b) => a + (b - mean) ** 2, 0) / arr.length);
  return { min: Math.min(...arr), max: Math.max(...arr), mean, std };
};
const cv = (arr) => {
  const m = arr.reduce((a, b) => a + b, 0) / arr.length;
  return m === 0 ? 0 : Math.sqrt(arr.reduce((a, b) => a + (b - m) ** 2, 0) / arr.length) / Math.abs(m);
};

// 1) 呼吸节奏：局部峰值间隔与峰值的变异系数（纯周期信号 CV≈0）。
const breath = series('ParamBreath');
const peaks = [];
for (let i = 2; i < breath.length - 2; i++) {
  if (breath[i] >= breath[i - 1] && breath[i] > breath[i + 1] && breath[i] > breath[i - 2] && breath[i] >= breath[i + 2]) {
    if (peaks.length === 0 || i - peaks[peaks.length - 1].i > 8) peaks.push({ i, v: breath[i] });
  }
}
const intervals = peaks.slice(1).map((p, k) => (p.i - peaks[k].i) / 10); // 秒
const breathIntervalCV = intervals.length > 3 ? cv(intervals) : 0;
const breathAmpCV = peaks.length > 3 ? cv(peaks.map((p) => p.v)) : 0;

// 2) 视线：saccade 次数（相邻样本 |ΔeyeX|>0.05 或 |ΔeyeY|>0.05，300ms 冷却合并）。
const eyeX = series('ParamEyeBallX');
const eyeY = series('ParamEyeBallY');
let saccades = 0;
let cooldown = 0;
for (let i = 1; i < eyeX.length; i++) {
  cooldown -= 1;
  if ((Math.abs(eyeX[i] - eyeX[i - 1]) > 0.05 || Math.abs(eyeY[i] - eyeY[i - 1]) > 0.05) && cooldown <= 0) {
    saccades++;
    cooldown = 3;
  }
}

// 3) 各通道活跃度。
const angleZ = series('ParamAngleZ');

const report = {
  durationSec: (samples[samples.length - 1].t - samples[0].t) / 1000,
  sampleCount: samples.length,
  breath: {
    ...stats(breath),
    peakCount: peaks.length,
    intervalCV: Number(breathIntervalCV.toFixed(3)),
    ampCV: Number(breathAmpCV.toFixed(3))
  },
  gaze: { saccades, ...stats(eyeX) },
  angleZ: { min: Number(Math.min(...angleZ).toFixed(3)), max: Number(Math.max(...angleZ).toFixed(3)) },
  verdict: {
    noPeriodBreath: breathIntervalCV > 0.12 && breathAmpCV > 0.05,
    gazeAlive: saccades >= 6 && saccades <= 40,
    swayAlive: Math.max(...angleZ) - Math.min(...angleZ) > 0.3
  }
};
console.log(JSON.stringify(report, null, 2));
console.log('console errors:', consoleLogs.filter((l) => l.startsWith('error') || l.startsWith('pageerror')));
await browser.close();
