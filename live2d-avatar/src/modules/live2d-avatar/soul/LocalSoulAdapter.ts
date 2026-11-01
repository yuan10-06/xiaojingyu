import type { SoulAdapter, StateFrame, DayPhase } from './SoulAdapter';

/**
 * 小鲸鱼本地灵魂（阉割版 BrainN：情绪 + 模板回复 + 轻记忆，无社会神经网络）。
 * 智能开关关闭时全靠它自跑；开启时 API 回复经 injectReply 注入，
 * 状态机仍在前端，记忆命名空间 whale.* 与聊天 AI 完全隔离。
 */
export class LocalSoulAdapter implements SoulAdapter {
  private valence = 0.1;
  private arousal = 0;
  private affinity = loadAffinity();
  private frameCb: ((frame: StateFrame) => void) | null = null;
  private readonly speakCbs = new Set<(speak: { text: string; phoneme?: string[]; volume: number }) => void>();
  private memoryCb: ((memory: NonNullable<StateFrame['memoryCue']>) => void) | null = null;
  private readonly timer: ReturnType<typeof setInterval>;
  private readonly mem: string[] = loadFacts();

  constructor() {
    this.timer = setInterval(() => this.step(0.5), 500);
  }

  onStateFrame(cb: (frame: StateFrame) => void): void { this.frameCb = cb; }
  onSpeak(cb: (speak: { text: string; phoneme?: string[]; volume: number }) => void): void { this.speakCbs.add(cb); }
  onMemoryRecall(cb: (memory: NonNullable<StateFrame['memoryCue']>) => void): void { this.memoryCb = cb; }

  /** 本地规则回复：关键词 → 情绪冲击 + 模板句。 */
  sendUserInput(text: string): void {
    const t = String(text || '').trim();
    if (!t) return;
    let reply: string;
    if (/喜欢|可爱|好吃|开心|棒|爱|摸摸|摸头/.test(t)) {
      this.bump(0.6, 0.35);
      this.raiseAffinity(0.04);
      reply = pick(['嘿嘿……被夸了会害羞的咕', '喜欢你哟，只对你说咕', '再、再摸一下也不是不行啦……']);
      this.remember(t);
    } else if (/海|游|水|浪|沙滩/.test(t)) {
      this.bump(0.25, 0.6);
      reply = pick(['海！我想回家了咕……不是，是想带你去玩！', '浪花打在尾巴上痒痒的，很舒服哟', '下次一起去看真正的海吧！']);
    } else if (/饿|饭|吃/.test(t)) {
      this.bump(0.2, 0.3);
      reply = pick(['想吃点心了咕……有鱼干吗', '干饭时间！我也陪你吃一口']);
    } else if (/难过|累|烦|哭/.test(t)) {
      this.bump(-0.3, 0.2);
      reply = pick(['抱抱你……今天辛苦啦', '不开心的话，我把尾巴借你抱一会儿']);
    } else if (/再见|晚安|睡了/.test(t)) {
      this.bump(0.1, -0.3);
      reply = pick(['晚安咕……明天也要来看我哟', '会梦到你的，大概']);
    } else if (/名字|你是谁/.test(t)) {
      reply = pick(['本鱼就是本鱼咕！深海来的鲸鱼女仆', '叫本鱼就好啦']);
    } else if (this.mem.length && Math.random() < 0.25) {
      const m = pick(this.mem);
      this.memoryCb?.({ id: 'fact', salience: 0.6, text: m });
      reply = '对了，我还记得你说过「' + m + '」呢';
    } else {
      this.bump(0.05, 0.15);
      reply = pick(['嗯嗯，我在听咕', '然后呢然后呢？', '咕？继续说嘛', '原来如此……记下来了哟']);
      if (t.length >= 4 && Math.random() < 0.5) this.remember(t);
    }
    for (const cb of this.speakCbs) cb({ text: reply, volume: 0.9 });
  }

  /** 智能开关开启时：API 回复注入（嘴巴更聪明，情绪仍由本地冲击驱动）。 */
  injectReply(text: string, valence = 0.2, arousal = 0.3): void {
    this.bump(valence, arousal);
    for (const cb of this.speakCbs) cb({ text: String(text || ''), volume: 0.9 });
  }

  dispose(): void {
    clearInterval(this.timer);
    this.frameCb = null;
    this.speakCbs.clear();
    this.memoryCb = null;
  }

  private bump(dv: number, da: number): void {
    this.valence = clamp1(this.valence + dv);
    this.arousal = clamp1(this.arousal + da);
  }

  private raiseAffinity(d: number): void {
    this.affinity = Math.min(1, this.affinity + d);
    saveAffinity(this.affinity);
  }

  private remember(text: string): void {
    const t = text.slice(0, 24);
    if (this.mem.includes(t)) return;
    this.mem.push(t);
    if (this.mem.length > 30) this.mem.shift();
    try { localStorage.setItem('whale.facts', JSON.stringify(this.mem)); } catch { /* 存储满就算了 */ }
  }

  private step(dt: number): void {
    // 情绪缓降回温和基线；亲密度持久化。
    this.valence += (0.1 - this.valence) * (dt / 10);
    this.arousal += (0 - this.arousal) * (dt / 8);
    this.frameCb?.({
      affect: { arousal: this.arousal, valence: this.valence, tension: 0, affinity: this.affinity },
      residue: [],
      relation: { closeness: this.affinity, power: 0, trust: this.affinity },
      gaze: { target: 'user', hold: 0 },
      time: { hour: new Date().getHours(), dayPhase: dayPhase() }
    });
  }
}

function clamp1(v: number): number { return Math.min(1, Math.max(-1, v)); }
function pick<T>(arr: T[]): T { return arr[Math.floor(Math.random() * arr.length)]; }

function loadFacts(): string[] {
  try { return JSON.parse(localStorage.getItem('whale.facts') || '[]'); } catch { return []; }
}

function loadAffinity(): number {
  const v = Number(localStorage.getItem('whale.affinity'));
  return Number.isFinite(v) && v > 0 ? Math.min(1, v) : 0.3;
}

function saveAffinity(v: number): void {
  try { localStorage.setItem('whale.affinity', String(v)); } catch { /* ignore */ }
}

function dayPhase(): DayPhase {
  const h = new Date().getHours();
  if (h < 6) return 'dawn';
  if (h < 12) return 'day';
  if (h < 18) return 'dusk';
  return 'night';
}
