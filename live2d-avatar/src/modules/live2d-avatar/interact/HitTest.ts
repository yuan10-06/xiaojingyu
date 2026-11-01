export type HitZone = 'head' | 'body' | 'tail' | 'none';

export interface HitResult {
  zone: HitZone;
  cx: number;
  cy: number;
}

interface ZoneRect {
  x: number[];
  y: number[];
}

export interface HitZones {
  head: ZoneRect;
  body: ZoneRect;
  tail: ZoneRect;
}

const clamp = (value: number, min: number, max: number): number =>
  Math.min(max, Math.max(min, value));

const inside = (rect: ZoneRect, x: number, y: number): boolean =>
  x >= rect.x[0] && x <= rect.x[1] && y >= rect.y[0] && y <= rect.y[1];

export class HitTest {
  constructor(
    private readonly canvas: HTMLElement,
    private readonly model: any,
    private readonly zones: HitZones
  ) {}

  hit(clientX: number, clientY: number): HitResult {
    const { nx, ny, cx, cy } = this.normalize(clientX, clientY);
    if (nx < 0 || nx > 1 || ny < 0 || ny > 1) return { zone: 'none', cx, cy };
    // 尾巴优先，避免右下方和身体/裙摆重叠。
    if (inside(this.zones.tail, nx, ny)) return { zone: 'tail', cx, cy };
    if (inside(this.zones.head, nx, ny)) return { zone: 'head', cx, cy };
    if (inside(this.zones.body, nx, ny)) return { zone: 'body', cx, cy };
    return { zone: 'none', cx, cy };
  }

  normalize(clientX: number, clientY: number): { nx: number; ny: number; cx: number; cy: number } {
    const rect = this.canvas.getBoundingClientRect();
    const bounds = this.model.getBounds();
    if (!bounds || bounds.width <= 0 || bounds.height <= 0) {
      return { nx: 0, ny: 0, cx: 0, cy: 0 };
    }
    const nx = (clientX - rect.left - bounds.x) / bounds.width;
    const ny = (clientY - rect.top - bounds.y) / bounds.height;
    return {
      nx,
      ny,
      cx: clamp((nx - 0.5) * 2, -1, 1),
      cy: clamp((ny - 0.5) * 2, -1, 1)
    };
  }
}
