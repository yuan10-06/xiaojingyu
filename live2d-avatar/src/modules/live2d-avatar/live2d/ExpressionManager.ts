/**
 * 表情差分（Exp3）管理器：根据情绪/说话状态挑对应表情并平滑切换。
 * 调用 Pixi Cubism4 ExpressionManager.setExpression(index)。
 * 索引与 model3.json 的 Expressions 定义一一对应：
 *   0=口型切换 1=3嘴 2=龇牙 3=脸黑 4=脸红 5=OO 6=》《 7=XX 8=流口水
 *   9=O嘴 10=担心嘴 11=栗子嘴 12=尾巴消失 13=耳朵消失 14=水印消除
 * 索引 14 不参与情绪切换，水印消除由 ModelRuntime 每帧写 Paramcol_3 完成。
 */
const IDX = {
  MOUTH: 0,        // 口型切换
  THREE: 1,        // 3嘴（可爱笑）
  GRIN: 2,         // 龇牙（开心）
  DARK: 3,         // 脸黑（低落/无语）
  BLUSH: 4,        // 脸红（害羞）
  O: 5,            // OO（惊讶）
  ARROW: 6,        // 》《（不满/生气）
  XX: 7,           // XX（晕倒/无语）
  DROOL: 8,        // 流口水（馋）
  O2: 9,           // O嘴（轻惊讶）
  WORRY: 10,       // 担心嘴
  CHESTNUT: 11,    // 栗子嘴（委屈/回忆）
};

/** 空闲微表情池：只放轻量、不夸张的几个，避免像抽风。 */
const MICRO_POOL = [IDX.THREE, IDX.GRIN, IDX.O2, IDX.MOUTH];

export interface EmotionSnapshot {
  valence: number;       // -1..1
  arousal: number;       // -1..1
  affinity: number;      // 0..1
  recallT: number;       // -1=未触发，>=0=回忆进行中（秒）
  startleT: number;      // -1=未触发，>=0=惊愕进行中（秒）
  speaking: boolean;
}

export class ExpressionManager {
  private mgr: any = null;
  private currentIdx: number | null = null;
  private nextAt = 0;  // ms
  // 空闲微表情：没有真实情绪时也偶尔换个轻表情，避免全程一张脸。
  private microIdx: number | null = null;
  private microUntil = 0;
  private nextMicroAt = 0;

  constructor(model: any) {
    const internal = model?.internalModel;
    // 表达式由 motionManager 持有并在 internalModel.update 里结算；
    // internalModel.expressionManager 在部分版本为空，取错对象会导致表情永远不切换。
    this.mgr = internal?.motionManager?.expressionManager ?? internal?.expressionManager;
  }

  update(nowMs: number, snap: EmotionSnapshot): void {
    if (!this.mgr || typeof this.mgr.setExpression !== 'function') return;
    if (nowMs < this.nextAt) return;

    let idx = this.pickIndex(snap);
    if (idx === IDX.MOUTH) {
      // 无强情绪：微表情保持中，或到点挑一个新的轻表情。
      if (this.microIdx !== null && nowMs < this.microUntil) {
        idx = this.microIdx;
      } else if (nowMs >= this.nextMicroAt) {
        this.microIdx = MICRO_POOL[Math.floor(Math.random() * MICRO_POOL.length)];
        this.microUntil = nowMs + 3000 + Math.random() * 2500;
        this.nextMicroAt = this.microUntil + 3500 + Math.random() * 4500;
        idx = this.microIdx;
      }
    } else {
      // 有真实情绪时立刻打断微表情。
      this.microIdx = null;
      this.microUntil = 0;
      this.nextMicroAt = nowMs + 4000 + Math.random() * 4000;
    }
    if (idx === this.currentIdx) return;

    try {
      // 0.6s 切换间隔，避免每帧抖动
      this.mgr.setExpression(idx);
      this.currentIdx = idx;
      this.nextAt = nowMs + 600;
    } catch {
      // 表情加载/切换失败不阻塞主流程
    }
  }

  /** 每次启动/恢复时重置表情槽位，避免残留上一个表情。 */
  reset(): void {
    if (!this.mgr) return;
    try {
      if (typeof this.mgr.resetExpression === 'function') this.mgr.resetExpression();
      this.currentIdx = null;
      this.nextAt = performance.now() + 400;
    } catch { /* ignore */ }
  }

  private pickIndex(snap: EmotionSnapshot): number {
    // 1. 说话中：优先嘴型相关表情
    if (snap.speaking) {
      if (snap.arousal > 0.4) return IDX.GRIN;   // 开心时说话用龇牙
      if (snap.valence < -0.2) return IDX.WORRY; // 低落时用担心嘴
      return IDX.MOUTH;                          // 默认口型切换
    }

    // 2. 惊愕/惊讶
    if (snap.startleT >= 0 && snap.startleT < 1.5) return IDX.O2;

    // 3. 回忆泄露
    if (snap.recallT >= 0 && snap.recallT < 3.3) {
      // 回忆里情绪偏负面用栗子嘴（委屈脸），正面用脸红
      if (snap.valence < 0) return IDX.CHESTNUT;
      return IDX.BLUSH;
    }

    // 4. 常规情绪映射（加权优先级：惊愕 > 回忆 > 说话 > 情绪）
    const v = snap.valence;
    const a = snap.arousal;

    if (v > 0.34 && a > 0.12) return IDX.BLUSH;      // 开心+有活力 = 脸红
    if (v > 0.18 && a > 0.05) return IDX.THREE;      // 小开心 = 3嘴（可爱笑）
    if (v > 0.06) return IDX.GRIN;                   // 轻微正向 = 龇牙
    if (v < -0.3 && a > 0.25) return IDX.DARK;       // 明显低落 = 脸黑
    if (v < -0.14) return IDX.WORRY;                 // 轻微低落 = 担心嘴
    if (a > 0.5 && Math.abs(v) < 0.18) return IDX.O; // 高唤醒+中性 = OO（惊喜/好奇）
    if (a < -0.3) return IDX.XX;                     // 低唤醒 = XX（困/无语）

    // 默认：无明显情绪 → 回到口型中性
    return IDX.MOUTH;
  }

  /** 调试用：当前表情索引。 */
  debugIndex(): number | null { return this.currentIdx; }
}
