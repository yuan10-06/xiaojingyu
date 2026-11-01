import type { SoulAdapter, StateFrame, DayPhase } from './SoulAdapter';

/**
 * 本地假灵魂：随机漫步的情绪基线 + 简单关键词反应。
 * 只用于开发/验收；接真灵魂时新增 RealSoulAdapter，表现层一行不用改。
 */
export class MockSoulAdapter implements SoulAdapter {
  private valence = 0;
  private arousal = 0;
  private baseValence = 0;
  private baseArousal = 0;
  private wanderIn = 4;
  private hold = false;
  private affinityV = 0.5;
  private frameCb: ((frame: StateFrame) => void) | null = null;
  private speakCb: ((speak: { text: string; phoneme?: string[]; volume: number }) => void) | null = null;
  private memoryCb: ((memory: NonNullable<StateFrame['memoryCue']>) => void) | null = null;
  private readonly timer: ReturnType<typeof setInterval>;

  constructor() {
    this.timer = setInterval(() => this.step(0.5), 500);
  }

  onStateFrame(cb: (frame: StateFrame) => void): void {
    this.frameCb = cb;
  }
  onSpeak(cb: (speak: { text: string; phoneme?: string[]; volume: number }) => void): void {
    this.speakCb = cb;
  }
  onMemoryRecall(cb: (memory: NonNullable<StateFrame['memoryCue']>) => void): void {
    this.memoryCb = cb;
  }

  /** 验收钩子：亲密度 0..1。 */
  setAffinity(a: number): void {
    this.affinityV = Math.min(1, Math.max(0, a));
  }

  /** 验收钩子：模拟说话。 */
  mockSpeak(text: string, volume = 0.9): void {
    this.speakCb?.({ text, volume });
  }

  /** 验收钩子：模拟记忆闪回。 */
  mockRecall(salience: number): void {
    this.memoryCb?.({ id: 'mock-' + Date.now(), salience });
  }

  sendUserInput(text: string): void {
    const t = String(text || '');
    if (/喜欢|可爱|好吃|开心|棒|爱/.test(t)) {
      this.valence = clamp1(this.valence + 0.7);
      this.arousal = clamp1(this.arousal + 0.3);
    } else if (/走|出去|海|玩|游/.test(t)) {
      this.arousal = clamp1(this.arousal + 0.6);
      this.valence = clamp1(this.valence + 0.2);
    } else if (/难过|生气|讨厌|走开了/.test(t)) {
      this.valence = clamp1(this.valence - 0.7);
      this.arousal = clamp1(this.arousal + 0.3);
    } else {
      this.arousal = clamp1(this.arousal + 0.2);
    }
  }

  /** 验收脚本直接控制情绪目标，并暂停随机漫步。 */
  setState(valence: number, arousal: number): void {
    this.valence = clamp1(valence);
    this.arousal = clamp1(arousal);
    this.baseValence = this.valence;
    this.baseArousal = this.arousal;
    this.hold = true;
  }

  getState(): { valence: number; arousal: number } {
    return { valence: this.valence, arousal: this.arousal };
  }

  dispose(): void {
    clearInterval(this.timer);
    this.frameCb = null;
    this.speakCb = null;
    this.memoryCb = null;
  }

  private step(dt: number): void {
    // 情绪残留缓降回基线（tau≈8s），基线本身缓慢随机漫步。
    const decay = dt / 8;
    this.valence += (this.baseValence - this.valence) * decay;
    this.arousal += (this.baseArousal - this.arousal) * decay;

    this.wanderIn -= dt;
    if (this.wanderIn <= 0 && !this.hold) {
      this.wanderIn = 6 + Math.random() * 6;
      this.baseValence = clamp1(this.baseValence + (Math.random() * 2 - 1) * 0.4);
      this.baseArousal = clamp1(this.baseArousal + (Math.random() * 2 - 1) * 0.4);
    }

    this.frameCb?.({
      affect: { arousal: this.arousal, valence: this.valence, tension: 0, affinity: this.affinityV },
      residue: [],
      relation: { closeness: this.affinityV, power: 0, trust: 0 },
      gaze: { target: 'user', hold: 0 },
      time: { hour: new Date().getHours(), dayPhase: dayPhase() }
    });
  }
}

function clamp1(v: number): number {
  return Math.min(1, Math.max(-1, v));
}

function dayPhase(): DayPhase {
  const h = new Date().getHours();
  if (h < 6) return 'dawn';
  if (h < 12) return 'day';
  if (h < 18) return 'dusk';
  return 'night';
}
