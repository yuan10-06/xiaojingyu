import type { ParamMap } from '../live2d/ParamMap';
import { SpringValue } from '../interact/PhysicsBoost';
import { fbm2, channel } from './Noise';

export interface IdleGazeConfig {
  minHold: number;
  maxHold: number;
  rangeNear: number;
  rangeFar: number;
  farChance: number;
  yScale: number;
  saccadeStiffness: number;
  saccadeDamping: number;
  dwellStiffness: number;
  dwellDamping: number;
  driftAmp: number;
  driftFreq: number;
}

export interface IdleConfig {
  breathBase: number;
  breathAmp: number;
  breathFreq: number;
  swayAmp: number;
  swayFreq: number;
  nodAmp: number;
  nodFreq: number;
  turnAmp: number;
  turnFreq: number;
  bodySwayAmp: number;
  bodySwayFreq: number;
  bodyNodAmp: number;
  bodyTurnAmp: number;
  gaze: IdleGazeConfig;
}

const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

/**
 * 生命感层：呼吸、微摇摆、头部微动、视线漂移。
 * 全部走 value-noise，无固定周期 → 60s 内无可察觉重复。
 * attention（0..1，来自 Reflex）高时 gaze/头部通道让位，呼吸不受影响。
 */
export class IdleBehavior {
  private t = 0;
  private breathPhase = 0;
  private readonly gazeX: SpringValue;
  private readonly gazeY: SpringValue;
  private gazeHold = 0;
  private saccading = false;
  private gazeBaseX = 0;
  private gazeBaseY = 0;
  private breathRateMul = 1;
  private breathAmpMul = 1;
  private motionAmpMul = 1;

  constructor(private readonly params: ParamMap, private readonly cfg: IdleConfig) {
    this.gazeX = new SpringValue(cfg.gaze.dwellStiffness, cfg.gaze.dwellDamping);
    this.gazeY = new SpringValue(cfg.gaze.dwellStiffness, cfg.gaze.dwellDamping);
    this.pickGazeTarget();
  }

  /** 情绪层调制：唤醒度驱动呼吸快慢/深浅与动作幅度。 */
  setModulation(mod: { breathRate?: number; breathAmp?: number; motionAmp?: number }): void {
    if (typeof mod.breathRate === 'number') this.breathRateMul = clamp(mod.breathRate, 0.5, 2);
    if (typeof mod.breathAmp === 'number') this.breathAmpMul = clamp(mod.breathAmp, 0.5, 1.8);
    if (typeof mod.motionAmp === 'number') this.motionAmpMul = clamp(mod.motionAmp, 0.4, 2);
  }

  update(dt: number, attention: number): void {
    this.t += dt;
    const t = this.t;

    // 呼吸：全程运行，交互不打断；频率/深度受情绪调制。
    // 频率用相位累加（而不是 t*freq*mul），避免调制突变造成波形跳变。
    this.breathPhase += dt * this.cfg.breathFreq * this.breathRateMul;
    const breath =
      this.cfg.breathBase +
      this.cfg.breathAmp * this.breathAmpMul * fbm2(this.breathPhase + channel(1));
    this.params.add('ParamBreath', clamp(breath, 0, 1));

    const headW = (1 - 0.85 * clamp(attention, 0, 1)) * this.motionAmpMul;
    const swayW = (1 - 0.6 * clamp(attention, 0, 1)) * this.motionAmpMul;

    // 微摇摆 + 头部微动：三个通道频率互不可约。
    this.params.add('ParamAngleZ', swayW * this.cfg.swayAmp * fbm2(t * this.cfg.swayFreq + channel(2)));
    this.params.add('ParamAngleX', headW * this.cfg.nodAmp * fbm2(t * this.cfg.nodFreq + channel(3)));
    this.params.add('ParamAngleY', headW * this.cfg.turnAmp * fbm2(t * this.cfg.turnFreq + channel(4)));

    // 身体九轴：比头慢、幅度更小、相位错开，头动完身体才跟上 → 有"柔软躯干"感。
    const bodyW = (1 - 0.5 * clamp(attention, 0, 1)) * this.motionAmpMul * 0.7;
    this.params.add('ParamBodyAngleZ', bodyW * this.cfg.bodySwayAmp * fbm2(t * this.cfg.bodySwayFreq + channel(7)));
    this.params.add('ParamBodyAngleX', bodyW * this.cfg.bodyNodAmp * fbm2(t * this.cfg.bodySwayFreq * 1.17 + channel(10)));
    this.params.add('ParamBodyAngleY', bodyW * this.cfg.bodyTurnAmp * fbm2(t * this.cfg.bodySwayFreq * 0.77 + channel(11)));

    // 视线漂移：saccade（快跳）→ dwell（慢漂 + 微抖）循环。
    const gazeW = 1 - clamp(attention, 0, 1);
    this.updateGaze(dt);
    this.params.add('ParamEyeBallX', gazeW * this.gazeX.value);
    this.params.add('ParamEyeBallY', gazeW * this.gazeY.value);
  }

  private updateGaze(dt: number): void {
    const g = this.cfg.gaze;

    if (this.saccading) {
      const settled =
        Math.abs(this.gazeX.target - this.gazeX.value) < 0.02 &&
        Math.abs(this.gazeY.target - this.gazeY.value) < 0.02 &&
        Math.abs(this.gazeX.velocity) < 0.05 &&
        Math.abs(this.gazeY.velocity) < 0.05;
      if (settled) {
        this.saccading = false;
        this.gazeX.setDamping(g.dwellDamping);
        this.gazeY.setDamping(g.dwellDamping);
        this.gazeX.stiffness = g.dwellStiffness;
        this.gazeY.stiffness = g.dwellStiffness;
      }
    } else {
      this.gazeHold -= dt;
      // dwell 期间凝视点微小漂移，不死盯。
      const driftX = g.driftAmp * fbm2(this.t * g.driftFreq + channel(5));
      const driftY = g.driftAmp * fbm2(this.t * g.driftFreq * 1.31 + channel(6));
      this.gazeX.setTarget(this.gazeBaseX + driftX);
      this.gazeY.setTarget(this.gazeBaseY + driftY);
      if (this.gazeHold <= 0) this.pickGazeTarget();
    }

    this.gazeX.update(dt);
    this.gazeY.update(dt);
  }

  private pickGazeTarget(): void {
    const g = this.cfg.gaze;
    const far = Math.random() < g.farChance;
    const range = far ? g.rangeFar : g.rangeNear;
    this.gazeBaseX = (Math.random() * 2 - 1) * range;
    this.gazeBaseY = (Math.random() * 2 - 1) * range * g.yScale;
    this.gazeX.setTarget(this.gazeBaseX);
    this.gazeY.setTarget(this.gazeBaseY);
    this.gazeX.stiffness = g.saccadeStiffness;
    this.gazeY.stiffness = g.saccadeStiffness;
    this.gazeX.setDamping(g.saccadeDamping);
    this.gazeY.setDamping(g.saccadeDamping);
    this.saccading = true;
    this.gazeHold = g.minHold + Math.random() * (g.maxHold - g.minHold);
  }

  reset(): void {
    this.t = 0;
    this.breathPhase = 0;
    this.breathRateMul = 1;
    this.breathAmpMul = 1;
    this.motionAmpMul = 1;
    this.gazeX.reset();
    this.gazeY.reset();
    this.gazeHold = 0;
    this.saccading = false;
    this.gazeBaseX = 0;
    this.gazeBaseY = 0;
  }
}
