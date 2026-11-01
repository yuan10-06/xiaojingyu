/**
 * 整数 hash 版 1D value noise。
 * 不用 Math.sin 做 hash（大输入精度差且带周期隐患），
 * 全程 Math.imul，输出确定、非周期。
 */
function hash1(n: number): number {
  let x = (Math.imul(n | 0, 374761393) + 668265263) | 0;
  x = Math.imul(x ^ (x >>> 13), 1274126177);
  x ^= x >>> 16;
  return ((x >>> 0) / 4294967296) * 2 - 1;
}

const smooth = (t: number): number => t * t * (3 - 2 * t);
const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

/** 1D value noise，输入任意实数（通常=秒*频率），输出 [-1, 1]。 */
export function noise1(t: number): number {
  const i = Math.floor(t);
  const f = t - i;
  return lerp(hash1(i), hash1(i + 1), smooth(f));
}

/** 两倍频叠加（1 + 0.5），输出约 [-1, 1]，细节更丰富。 */
export function fbm2(t: number): number {
  return (noise1(t) + 0.5 * noise1(t * 2.03 + 31.7)) / 1.5;
}

/** 通道去相关：每个通道用不同的大偏移，避免所有通道同形。 */
export function channel(seed: number): number {
  return seed * 137.31 + 11.17;
}
