import type { HitResult, HitTest } from './HitTest';

interface PointerCallbacks {
  onTap(hit: HitResult): void;
  onDragStart(): void;
  onDrag(cx: number, cy: number): void;
  onDragEnd(): void;
}

interface PointerStart {
  pointerId: number;
  x: number;
  y: number;
  hit: HitResult;
}

export class PointerController {
  private start: PointerStart | null = null;
  private moved = false;

  private readonly onDown = (event: PointerEvent): void => {
    if (event.button !== undefined && event.button !== 0) return;
    if (this.start) return;
    const hit = this.hitTest.hit(event.clientX, event.clientY);
    if (hit.zone === 'none') return;
    this.start = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, hit };
    this.moved = false;
    try {
      this.canvas.setPointerCapture(event.pointerId);
    } catch {
      // ignore
    }
    event.preventDefault();
  };

  private readonly onMove = (event: PointerEvent): void => {
    if (!this.start || event.pointerId !== this.start.pointerId) return;
    const dx = event.clientX - this.start.x;
    const dy = event.clientY - this.start.y;
    if (!this.moved && Math.hypot(dx, dy) >= this.threshold) {
      this.moved = true;
      this.callbacks.onDragStart();
    }
    if (!this.moved) return;
    const { cx, cy } = this.hitTest.normalize(event.clientX, event.clientY);
    this.callbacks.onDrag(cx, cy);
    event.preventDefault();
  };

  private readonly onUp = (event: PointerEvent): void => {
    if (!this.start || event.pointerId !== this.start.pointerId) return;
    const start = this.start;
    this.start = null;
    try {
      this.canvas.releasePointerCapture(event.pointerId);
    } catch {
      // ignore
    }
    if (this.moved) {
      this.moved = false;
      this.callbacks.onDragEnd();
      return;
    }
    this.callbacks.onTap(start.hit);
  };

  private readonly onCancel = (event: PointerEvent): void => {
    if (!this.start || event.pointerId !== this.start.pointerId) return;
    this.start = null;
    if (this.moved) {
      this.moved = false;
      this.callbacks.onDragEnd();
    }
  };

  constructor(
    private readonly canvas: HTMLElement,
    private readonly hitTest: HitTest,
    private readonly callbacks: PointerCallbacks,
    private readonly threshold: number
  ) {
    this.canvas.addEventListener('pointerdown', this.onDown, { passive: false });
    this.canvas.addEventListener('pointermove', this.onMove, { passive: false });
    this.canvas.addEventListener('pointerup', this.onUp);
    this.canvas.addEventListener('pointercancel', this.onCancel);
  }

  destroy(): void {
    this.canvas.removeEventListener('pointerdown', this.onDown);
    this.canvas.removeEventListener('pointermove', this.onMove);
    this.canvas.removeEventListener('pointerup', this.onUp);
    this.canvas.removeEventListener('pointercancel', this.onCancel);
    this.start = null;
  }
}
