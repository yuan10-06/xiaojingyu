import type { ParamMap } from './ParamMap';
import type { HitZone } from '../interact/HitTest';

export interface PoseConfig {
  poses: Record<string, Record<string, number>>;
  autoMin: number;
  autoMax: number;
  lerp: number;
  tapPose: Record<string, string>;
  tapHold: number;
}

const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

/**
 * 姿势控制器：用头部/身体多段/手臂参数组合出可识别的姿态。
 * 与 IdleBehavior 的微摇摆加性叠加：Idle 负责呼吸抖动，Pose 负责大姿态基线。
 * Reflex 激活时（被戳/拖拽），头部通道让位给躲闪，身体姿势保留。
 * 平滑用指数 lerp，避免切换跳变。
 */
export class PoseController {
  private current: Record<string, number> = {};
  private target: Record<string, number> = {};
  private currentName = 'idle';
  private nextAutoAt = 0;
  private tapUntil = 0;
  private readonly poseNames: string[];

  constructor(
    private readonly params: ParamMap,
    private readonly cfg: PoseConfig,
    now: number
  ) {
    this.poseNames = Object.keys(cfg.poses || {});
    if (!this.poseNames.includes('idle') && this.poseNames.length) {
      this.poseNames.unshift('idle');
    }
    this.scheduleNext(now);
  }

  /** 被点击触发临时姿势，持续 tapHold 秒后回到自动轮播。 */
  tap(zone: HitZone, now: number): void {
    const name = this.cfg.tapPose?.[zone];
    if (!name || !this.cfg.poses[name]) return;
    this.set(name);
    this.tapUntil = now / 1000 + this.cfg.tapHold;
  }

  set(name: string): void {
    if (!this.cfg.poses[name]) return;
    this.currentName = name;
    this.target = { ...this.cfg.poses[name] };
  }

  update(dt: number, nowSec: number, attention: number): void {
    // 交互姿势到期后回到自动轮播节奏。
    if (this.tapUntil > 0 && nowSec >= this.tapUntil) {
      this.tapUntil = 0;
      this.nextAutoAt = nowSec; // 立刻进入自动选择
    }

    // 自动轮播（仅在非交互姿势时）。
    if (this.tapUntil <= 0 && nowSec >= this.nextAutoAt) {
      this.pickAuto();
      this.scheduleNext(nowSec);
    }

    // 指数 lerp 平滑到目标姿势。
    const k = 1 - Math.exp(-this.cfg.lerp * dt);
    for (const id of new Set([...Object.keys(this.target), ...Object.keys(this.current)])) {
      const t = this.target[id] || 0;
      const c = this.current[id] || 0;
      const nv = c + (t - c) * k;
      if (Math.abs(nv) < 1e-4 && Math.abs(t) < 1e-4) {
        delete this.current[id];
      } else {
        this.current[id] = nv;
      }
    }

    // 输出到参数层：头部在交互时让位，身体/手臂始终输出。
    const headW = 1 - clamp(attention, 0, 1);
    for (const [id, val] of Object.entries(this.current)) {
      const isHead = id === 'ParamAngleX' || id === 'ParamAngleY' || id === 'ParamAngleZ';
      this.params.add(id, val * (isHead ? headW : 1));
    }
  }

  debugCurrent(): string {
    return this.currentName;
  }

  private pickAuto(): void {
    if (this.poseNames.length <= 1) return;
    // 不重复刚做的姿势。
    let name = this.poseNames[Math.floor(Math.random() * this.poseNames.length)];
    if (name === this.currentName && this.poseNames.length > 1) {
      name = this.poseNames[(this.poseNames.indexOf(name) + 1) % this.poseNames.length];
    }
    this.set(name);
  }

  private scheduleNext(nowSec: number): void {
    this.nextAutoAt = nowSec + this.cfg.autoMin + Math.random() * (this.cfg.autoMax - this.cfg.autoMin);
  }
}
