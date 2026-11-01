import type { BlinkController } from '../live2d/BlinkController';
import type { ParamMap } from '../live2d/ParamMap';
import { SpringValue } from './PhysicsBoost';
import type { HitZone } from './HitTest';

const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

interface ReflexEntry {
  headX: number;
  headY: number;
  headZ: number;
  bodyZ: number;
  blink: number;
  gazeX: number;
  gazeY: number;
  gazeHold: number;
}

interface DragConfig {
  followStiffness: number;
  followDamping: number;
  releaseDamping: number;
  headX: number;
  headY: number;
  headZ: number;
  bodyZ: number;
  gazeX: number;
  gazeY: number;
  gazeStiffness: number;
  gazeDamping: number;
}

export interface ReflexConfig {
  drag: DragConfig;
  reflex: {
    head: ReflexEntry;
    body: ReflexEntry;
    tail: ReflexEntry;
  };
}

export class Reflex {
  private readonly headX = new SpringValue(120, 12);
  private readonly headY = new SpringValue(120, 12);
  private readonly headZ = new SpringValue(150, 10);
  private readonly bodyZ = new SpringValue(150, 12);
  private gazeX: SpringValue;
  private gazeY: SpringValue;
  private gazeHold = 0;
  private dragging = false;

  constructor(
    private readonly params: ParamMap,
    private readonly blink: BlinkController,
    private readonly cfg: ReflexConfig
  ) {
    this.gazeX = new SpringValue(cfg.drag.gazeStiffness, cfg.drag.gazeDamping);
    this.gazeY = new SpringValue(cfg.drag.gazeStiffness, cfg.drag.gazeDamping);
  }

  /**
   * affinity 0..1：陌生人被戳躲闪更猛、注视更短；熟人反应温和、注视更久。
   */
  tap(zone: HitZone, cx: number, cy: number, affinity = 0.5): void {
    if (zone === 'none') return;
    const cfg = this.cfg.reflex[zone];
    const imp = 1.25 - 0.5 * Math.min(1, Math.max(0, affinity));
    const holdScale = 0.6 + 1.2 * Math.min(1, Math.max(0, affinity));
    this.headX.kick(cfg.headX * imp);
    this.headY.kick(cfg.headY * imp);
    this.headZ.kick(cfg.headZ * imp);
    this.bodyZ.kick(cfg.bodyZ * imp);
    this.blink.trigger(cfg.blink);
    this.gazeX.setTarget(cx * 0.9);
    this.gazeY.setTarget(cy * 0.8);
    this.gazeHold = cfg.gazeHold * holdScale;
  }

  /** 摄像头人脸位置驱动：cx/cy 为 -1..1 的归一化坐标，不抢拖拽。 */
  lookAt(cx: number, cy: number, weight = 0.8): void {
    if (this.dragging) return;
    const w = clamp(weight, 0, 1);
    const gx = clamp(cx, -1, 1);
    const gy = clamp(cy, -1, 1);
    const cfg = this.cfg.drag;
    this.gazeX.setTarget(gx * 0.9 * w);
    this.gazeY.setTarget(gy * 0.8 * w);
    this.headX.setTarget(gx * cfg.headX * 0.55 * w);
    this.headY.setTarget(gy * cfg.headY * 0.55 * w);
    this.headZ.setTarget(gx * cfg.headZ * 0.35 * w);
    this.gazeHold = 0.2;
  }

  clearLook(): void {
    if (this.dragging) return;
    this.gazeX.setTarget(0);
    this.gazeY.setTarget(0);
    this.headX.setTarget(0);
    this.headY.setTarget(0);
    this.headZ.setTarget(0);
    this.gazeHold = 0;
  }

  startDrag(): void {
    this.dragging = true;
    this.headX.setDamping(this.cfg.drag.followDamping);
    this.headY.setDamping(this.cfg.drag.followDamping);
    this.headZ.setDamping(this.cfg.drag.followDamping);
    this.bodyZ.setDamping(this.cfg.drag.followDamping);
    this.gazeX.setDamping(this.cfg.drag.followDamping);
    this.gazeY.setDamping(this.cfg.drag.followDamping);
  }

  drag(cx: number, cy: number): void {
    const cfg = this.cfg.drag;
    this.headX.setTarget(cx * cfg.headX);
    this.headY.setTarget(cy * cfg.headY);
    this.headZ.setTarget(cx * cfg.headZ);
    this.bodyZ.setTarget(cx * cfg.bodyZ);
    this.gazeX.setTarget(cx * cfg.gazeX);
    this.gazeY.setTarget(cy * cfg.gazeY);
    this.gazeHold = 0.2;
  }

  endDrag(): void {
    this.dragging = false;
    this.headX.setTarget(0);
    this.headY.setTarget(0);
    this.headZ.setTarget(0);
    this.bodyZ.setTarget(0);
    this.gazeX.setTarget(0);
    this.gazeY.setTarget(0);
    this.headX.setDamping(this.cfg.drag.releaseDamping);
    this.headY.setDamping(this.cfg.drag.releaseDamping);
    this.headZ.setDamping(this.cfg.drag.releaseDamping);
    this.bodyZ.setDamping(this.cfg.drag.releaseDamping);
    this.gazeX.setDamping(this.cfg.drag.releaseDamping);
    this.gazeY.setDamping(this.cfg.drag.releaseDamping);
  }

  update(dt: number): void {
    this.headX.update(dt);
    this.headY.update(dt);
    this.headZ.update(dt);
    this.bodyZ.update(dt);
    this.gazeX.update(dt);
    this.gazeY.update(dt);

    if (this.gazeHold > 0) {
      this.gazeHold -= dt;
      if (this.gazeHold <= 0 && !this.dragging) {
        this.gazeX.setTarget(0);
        this.gazeY.setTarget(0);
      }
    }

    this.params.add('ParamAngleX', this.headX.value);
    this.params.add('ParamAngleY', this.headY.value);
    this.params.add('ParamAngleZ', this.headZ.value);
    this.params.add('ParamBodyAngleZ', this.bodyZ.value);
    this.params.add('ParamEyeBallX', this.gazeX.value);
    this.params.add('ParamEyeBallY', this.gazeY.value);
  }

  /** 0..1，供生命感层判断该让位多少：拖拽/注视中=1，弹簧余振按比例。 */
  attentionWeight(): number {
    if (this.dragging || this.gazeHold > 0) return 1;
    const motion =
      Math.abs(this.headX.value) + Math.abs(this.headY.value) +
      Math.abs(this.headZ.value) + Math.abs(this.bodyZ.value);
    return Math.min(1, motion / 8);
  }

  reset(): void {
    this.headX.reset();
    this.headY.reset();
    this.headZ.reset();
    this.bodyZ.reset();
    this.gazeX.reset();
    this.gazeY.reset();
    this.gazeHold = 0;
    this.dragging = false;
  }
}
