import type { ParamMap } from '../live2d/ParamMap';
import type { BlinkController } from '../live2d/BlinkController';
import type { IdleBehavior } from '../idle/IdleBehavior';
import type { StateFrame } from './SoulAdapter';

export interface EmotionConfig {
  valenceTau: number;
  arousalTau: number;
  mouthForm: number;
  browYDown: number;
  browYUp: number;
  browAngle: number;
  browFormUp: number;
  browFormDown: number;
  eyeSmile: number;
  eyeAnger: number;
  eyePuff: number;
  sleepyEyeClose: number;
  surpriseEyeOpen: number;
  breathRateMul: number;
  breathAmpMul: number;
  motionAmpMul: number;
  blinkRateMul: number;
}

const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

/** attack → hold → release 包络，输出 0..1。 */
function envelope(t: number, attack: number, hold: number, release: number): number {
  if (t < 0) return 0;
  if (t < attack) return t / Math.max(0.01, attack);
  if (t < attack + hold) return 1;
  return clamp(1 - (t - attack - hold) / Math.max(0.01, release), 0, 1);
}

export interface SocialConfig {
  affinityTau: number;
  affinityValenceLift: number;
  recallEyeOpen: number;
  recallBrow: number;
  recallGazeDown: number;
  startleEyeOpen: number;
  startleBrow: number;
  startleMouth: number;
}

/**
 * 状态驱动层（P2）：把 StateFrame 的 arousal/valence 连续映射到表情与生命感。
 * 灵魂侧只推帧，表现层在这里做一阶低通——状态突变时情绪残留缓降，绝不跳变。
 * 映射全部加性，落在 ParamMap，不碰 motion/physics。
 */
export class EmotionMapper {
  private targetValence = 0;
  private targetArousal = 0;
  private valence = 0;
  private arousal = 0;
  private affinity = 0.5;
  private targetAffinity = 0.5;
  private recallT = -1;
  private recallSalience = 0;
  private startleT = -1;
  /** 外部情绪注入的保持期（秒）：期间拒绝 soul 的常规帧覆盖，让瞬时反应看得见。 */
  private holdUntil = 0;

  constructor(
    private readonly params: ParamMap,
    private readonly idle: IdleBehavior,
    private readonly blink: BlinkController,
    private readonly cfg: EmotionConfig,
    private readonly social: SocialConfig
  ) {}

  push(frame: StateFrame): void {
    if (!frame || !frame.affect) return;
    // 瞬时互动情绪还在保持期：先不被 soul 的常规帧覆盖。
    if (performance.now() / 1000 < this.holdUntil) return;
    this.targetValence = clamp(Number(frame.affect.valence) || 0, -1, 1);
    this.targetArousal = clamp(Number(frame.affect.arousal) || 0, -1, 1);
    const close = frame.relation && typeof frame.relation.closeness === 'number'
      ? frame.relation.closeness
      : (Number(frame.affect.affinity) + 1) / 2;
    if (Number.isFinite(close)) this.targetAffinity = clamp(close, 0, 1);
  }

  /** 互动瞬时情绪注入：短时间内覆盖 soul 帧，让害羞/生气/委屈看得见。 */
  nudge(valence: number, arousal: number, holdSec = 2.5): void {
    this.targetValence = clamp(this.targetValence + valence, -1, 1);
    this.targetArousal = clamp(this.targetArousal + arousal, -1, 1);
    this.holdUntil = performance.now() / 1000 + holdSec;
  }

  /** 记忆微表情：回忆泄露 3.3s，眼睛微睁、眉轻扬、视线下移。 */
  recall(salience: number): void {
    this.recallT = 0;
    this.recallSalience = clamp(salience, 0, 1);
  }

  /** 打断惊愕：说话中被戳，瞬间睁大眼 + 扬眉 + 张嘴，1.7s 缓释。 */
  startle(): void {
    this.startleT = 0;
  }

  getAffinity(): number {
    return this.affinity;
  }

  update(dt: number): void {
    // 一阶低通：情绪有惯性，残留缓降。
    this.valence = this.lowpass(this.valence, this.targetValence, this.cfg.valenceTau, dt);
    this.arousal = this.lowpass(this.arousal, this.targetArousal, this.cfg.arousalTau, dt);
    this.affinity = this.lowpass(this.affinity, this.targetAffinity, this.social.affinityTau, dt);
    // 亲密度抬高情绪基线：熟人面前更松弛温和。
    const v = this.valence + this.social.affinityValenceLift * (this.affinity - 0.5);
    const a = this.arousal;

    // valence → 嘴角 + 眉毛。
    this.params.add('ParamMouthForm', this.cfg.mouthForm * v);
    if (v < 0) {
      this.params.add('ParamBrowLY', this.cfg.browYDown * v); // v 负 → 眉毛下压
      this.params.add('ParamBrowRY', this.cfg.browYDown * v);
      this.params.add('ParamBrowLAngle', this.cfg.browAngle * -v); // 八字
      this.params.add('ParamBrowRAngle', this.cfg.browAngle * -v);
      this.params.add('ParamBrowLForm', this.cfg.browFormDown * -v);
      this.params.add('ParamBrowRForm', this.cfg.browFormDown * -v);
    } else {
      this.params.add('ParamBrowLY', this.cfg.browYUp * v);
      this.params.add('ParamBrowRY', this.cfg.browYUp * v);
      this.params.add('ParamBrowLForm', this.cfg.browFormUp * v);
      this.params.add('ParamBrowRForm', this.cfg.browFormUp * v);
    }

    // 眼睛差分：直接驱动眼睛参数，不再只靠模型表情的嘴脸红脸黑。
    // 阈值压低到 0.08，日常轻微开心也能看到弯眼笑，而不是只有强情绪才触发。
    if (v > 0.08) this.params.add('ParamEyeSmile', this.cfg.eyeSmile * Math.min(1, v * 3));
    if (v < -0.2 && a > 0.05) this.params.add('ParamEyeAnger', this.cfg.eyeAnger * Math.min(1, -v * 2));
    if (v < -0.05) this.params.add('ParamEyePuff', this.cfg.eyePuff * Math.min(1, -v * 2));
    if (a < -0.3) {
      this.params.add('ParamEyeLOpen', -this.cfg.sleepyEyeClose);
      this.params.add('ParamEyeROpen', -this.cfg.sleepyEyeClose);
    }
    if (a > 0.5 && v > -0.1) {
      this.params.add('ParamEyeLOpen', this.cfg.surpriseEyeOpen);
      this.params.add('ParamEyeROpen', this.cfg.surpriseEyeOpen);
    }

    // 嘴部细节：正向得意/歪嘴笑，负向撇嘴。
    if (v > 0.15) this.params.add('ParamMouthX', 0.26 * Math.min(1, v));
    else if (v < -0.15) this.params.add('ParamMouthX', 0.3 * Math.max(-1, v));

    // arousal → 呼吸快慢深浅、动作幅度、眨眼频率。
    this.idle.setModulation({
      breathRate: 1 + this.cfg.breathRateMul * a,
      breathAmp: 1 + this.cfg.breathAmpMul * a,
      motionAmp: 1 + this.cfg.motionAmpMul * a
    });
    this.blink.setRateMultiplier(1 + this.cfg.blinkRateMul * Math.max(0, a));

    // 记忆微表情（回忆泄露）。
    if (this.recallT >= 0) {
      this.recallT += dt;
      const e = envelope(this.recallT, 0.3, 1.0, 2.0) * this.recallSalience;
      if (this.recallT > 3.3) {
        this.recallT = -1;
      } else if (e > 0.001) {
        this.params.add('ParamEyeLOpen', this.social.recallEyeOpen * e);
        this.params.add('ParamEyeROpen', this.social.recallEyeOpen * e);
        this.params.add('ParamBrowLY', this.social.recallBrow * e);
        this.params.add('ParamBrowRY', this.social.recallBrow * e);
        this.params.add('ParamEyeBallY', this.social.recallGazeDown * e);
      }
    }

    // 打断惊愕。
    if (this.startleT >= 0) {
      this.startleT += dt;
      const e = envelope(this.startleT, 0.06, 0.25, 1.4);
      if (this.startleT > 1.8) {
        this.startleT = -1;
      } else if (e > 0.001) {
        this.params.add('ParamEyeLOpen', this.social.startleEyeOpen * e);
        this.params.add('ParamEyeROpen', this.social.startleEyeOpen * e);
        this.params.add('ParamBrowLY', this.social.startleBrow * e);
        this.params.add('ParamBrowRY', this.social.startleBrow * e);
        this.params.add('ParamMouthOpenY', this.social.startleMouth * e);
      }
    }
  }

  /** 验收/HUD 用：当前平滑后的情绪值。 */
  debugState(): { valence: number; arousal: number } {
    return { valence: this.valence, arousal: this.arousal };
  }

  /** ExpressionManager 读取 recall/startle 状态机进度：>=0 表示激活中（秒）。 */
  debugRecallT(): number { return this.recallT; }
  debugStartleT(): number { return this.startleT; }

  private lowpass(cur: number, target: number, tau: number, dt: number): number {
    const k = dt / Math.max(0.05, tau);
    return cur + (target - cur) * Math.min(1, k);
  }
}
