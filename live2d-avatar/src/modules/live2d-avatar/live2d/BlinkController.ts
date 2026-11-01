import type { ParamMap } from './ParamMap';

export interface BlinkConfig {
  minInterval: number;
  maxInterval: number;
  doubleChance: number;
  halfChance: number;
  halfAmount: number;
  closeTime: number;
  holdTime: number;
  openTime: number;
  doubleGap: number;
}

type Phase = 'idle' | 'closing' | 'closed' | 'opening';

const ease = (value: number): number => {
  const t = Math.min(Math.max(value, 0), 1);
  return t * t * (3 - 2 * t);
};

export class BlinkController {
  private phase: Phase = 'idle';
  private phaseTime = 0;
  private targetAmount = 1;
  private nextAt = 0;
  private queuedDouble = false;
  private doubleDelay = 0;
  private currentAmount = 0;
  private rateMul = 1;

  constructor(private readonly params: ParamMap, private readonly cfg: BlinkConfig) {
    this.schedule();
  }

  /** 情绪层调制：>1 眨得更勤（高唤醒），<1 更慵懒。 */
  setRateMultiplier(mul: number): void {
    this.rateMul = Math.min(3, Math.max(0.2, mul));
  }

  trigger(scale = 1): void {
    if (this.phase !== 'idle') return;
    this.start(Math.min(1, Math.max(0.2, scale)), false);
  }

  tick(dt: number): void {
    this.phaseTime += dt;

    if (this.phase === 'idle') {
      if (this.doubleDelay > 0) {
        this.doubleDelay -= dt;
        if (this.doubleDelay <= 0) this.start(this.targetAmount, false);
      } else {
        this.nextAt -= dt;
        if (this.nextAt <= 0) this.start(this.randomAmount(), true);
      }
    } else if (this.phase === 'closing') {
      const t = this.phaseTime / this.cfg.closeTime;
      this.currentAmount = this.targetAmount * ease(t);
      if (t >= 1) {
        this.phase = 'closed';
        this.phaseTime = 0;
        this.currentAmount = this.targetAmount;
      }
    } else if (this.phase === 'closed') {
      this.currentAmount = this.targetAmount;
      if (this.phaseTime >= this.cfg.holdTime) {
        this.phase = 'opening';
        this.phaseTime = 0;
      }
    } else {
      const t = this.phaseTime / this.cfg.openTime;
      this.currentAmount = this.targetAmount * (1 - ease(t));
      if (t >= 1) {
        this.currentAmount = 0;
        this.phase = 'idle';
        this.phaseTime = 0;
        if (this.queuedDouble) {
          this.queuedDouble = false;
          this.doubleDelay = this.cfg.doubleGap;
        } else {
          this.schedule();
        }
      }
    }

    if (this.currentAmount > 0) {
      this.params.add('ParamEyeLOpen', -this.currentAmount);
      this.params.add('ParamEyeROpen', -this.currentAmount);
    }
  }

  private start(amount: number, allowDouble: boolean): void {
    this.phase = 'closing';
    this.phaseTime = 0;
    this.targetAmount = Math.min(1, Math.max(0.1, amount));
    this.currentAmount = 0;
    if (allowDouble && Math.random() < this.cfg.doubleChance) {
      this.queuedDouble = true;
    }
  }

  private randomAmount(): number {
    return Math.random() < this.cfg.halfChance ? this.cfg.halfAmount : 1;
  }

  private schedule(): void {
    const min = this.cfg.minInterval;
    const max = Math.max(min, this.cfg.maxInterval);
    this.nextAt = (min + Math.random() * (max - min)) / this.rateMul;
  }
}
