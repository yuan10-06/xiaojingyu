import type { ParamMap } from '../live2d/ParamMap';
import { fbm2, channel } from '../idle/Noise';

const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

/**
 * 说话层：onSpeak 期间用噪声驱动嘴部开合（无音素时也像嘟囔），
 * 时长按字数估算；被戳/拖拽打断时 interrupt()，由情绪层接手惊愕。
 * speakVoice() 语音输出三级回退：
 *   1. 云端 MiniMax（window.Android.speakCloud，真人音色，真实音频时长回传驱动嘴型）
 *   2. 原生系统 TTS（window.Android.speak）
 *   3. Web Speech API（fire-and-forget，失败不阻塞嘴型和气泡）
 */
export class SpeakLayer {
  private active = false;
  private t = 0;
  private dur = 0;
  private volume = 1;
  private voiceOn = false;
  private cachedVoice: SpeechSynthesisVoice | null = null;
  private cloudBound = false;
  private cloudText = '';

  speaking(): boolean {
    return this.active;
  }

  /** 打开/关闭可爱语音模式（页面级开关）。 */
  setVoiceEnabled(on: boolean): void {
    this.voiceOn = !!on;
  }

  speak(text: string, volume = 1, mood?: { valence: number; arousal: number }): void {
    const t = String(text || '');
    this.active = true;
    this.t = 0;
    this.volume = clamp(volume, 0, 1);
    this.dur = Math.min(6, Math.max(1.2, t.length * 0.14));
    if (this.voiceOn && t) this.speakVoice(t, mood);
  }

  interrupt(): void {
    this.active = false;
    try { (window as any).Android?.stopSpeak?.(); } catch { /* ignore */ }
    try { (window as any).speechSynthesis?.cancel?.(); } catch { /* ignore */ }
  }

  /**
   * Fire-and-forget 语音：云端 MiniMax → 原生 TTS → Web Speech，逐级回退。
   * 失败直接吞掉——气泡照常显示，嘴型照常驱动，不依赖语音成功。
   */
  private speakVoice(text: string, mood?: { valence: number; arousal: number }): void {
    if (this.speakCloudVoice(text, mood)) return;
    if (this.speakNative(text)) return;
    try {
      const ss = (window as any).speechSynthesis as SpeechSynthesis | undefined;
      if (!ss) return;
      if (!this.cachedVoice) this.cachedVoice = this.pickVoice();
      const u = new SpeechSynthesisUtterance(text);
      if (this.cachedVoice) u.voice = this.cachedVoice;
      u.lang = this.cachedVoice?.lang || 'zh-CN';
      u.rate = 1.05;
      u.pitch = 1.1;
      u.volume = 0.9;
      ss.speak(u);
    } catch { /* 任何异常静默，不影响嘴型/气泡 */ }
  }

  /**
   * 云端 MiniMax 语音桥。原生侧合成是异步的：播放开始回调 onStart(真实时长ms)，
   * 用真实时长替换按字数的估算；onError 时退回原生系统 TTS 再试一次。
   * mood 把当前情绪翻成 MiniMax 的 emotion，让她带情绪说话，而不是一个字一个字念稿。
   */
  private speakCloudVoice(text: string, mood?: { valence: number; arousal: number }): boolean {
    const a = (window as any).Android;
    if (!a || typeof a.speakCloud !== 'function') return false;
    try {
      if (typeof a.hasCloudTts === 'function' && !a.hasCloudTts()) return false;
      this.bindCloudCallbacks();
      this.cloudText = text;
      if (a.speakCloud(text, SpeakLayer.emotionOf(mood))) return true;
    } catch { /* 落到下一级 */ }
    return false;
  }

  /** 情绪 → MiniMax emotion；没有情绪数据时给 neutral（正常语气）。 */
  private static emotionOf(mood?: { valence: number; arousal: number }): string {
    if (!mood) return 'neutral';
    const v = mood.valence;
    const a = mood.arousal;
    if (v > 0.3 && a > 0.25) return 'happy';
    if (v > 0.1) return 'happy';
    if (v < -0.28 && a > 0.45) return 'angry';
    if (v < -0.1) return 'sad';
    if (a > 0.65) return 'surprised';
    return 'neutral';
  }

  private bindCloudCallbacks(): void {
    if (this.cloudBound) return;
    this.cloudBound = true;
    (window as any).__whaleTts = {
      onStart: (durMs: number) => {
        this.active = true;
        this.t = 0;
        if (durMs > 0) this.dur = clamp(durMs / 1000, 0.8, 30);
      },
      onEnd: () => { this.active = false; },
      onError: () => {
        this.active = false;
        if (this.cloudText) this.speakNative(this.cloudText); // 云端失败，退回系统语音
      }
    };
  }

  /** App 侧原生 TTS 桥；引擎未就绪时 Java 会先缓存这句，初始化完再念。 */
  private speakNative(text: string): boolean {
    const a = (window as any).Android;
    if (!a || typeof a.speak !== 'function') return false;
    try {
      a.speak(text, 1.05, 1.15);
      return true;
    } catch {
      return false;
    }
  }

  /** 优先选中文女声（voiceURI 含 female / 女声 / girl / woman），否则回退 zh-CN。 */
  private pickVoice(): SpeechSynthesisVoice | null {
    const voices = (window as any).speechSynthesis?.getVoices?.() as SpeechSynthesisVoice[] | undefined;
    if (!voices || !voices.length) return null;
    const name = (v: SpeechSynthesisVoice) => (v.name || '').toLowerCase();
    const female = voices.filter(v =>
      /zh/i.test(v.lang || '') &&
      /female|woman|girl|女声|女性|yaoyao|xiaoxiao|tingting|yunxi/i.test(name(v))
    );
    if (female.length) return female[0];
    const zh = voices.filter(v => /zh/i.test(v.lang || ''));
    return zh[0] || null;
  }

  tick(dt: number, params: ParamMap): void {
    if (!this.active) return;
    this.t += dt;
    if (this.t >= this.dur) {
      this.active = false;
      return;
    }
    const open = Math.abs(fbm2(this.t * 6.5 + channel(9))) * 0.75 * this.volume;
    params.add('ParamMouthOpenY', open);
  }
}
