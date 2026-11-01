/**
 * 所有参数写入都走“读当前值 + delta”的加性通道。
 * 每帧先收集 pending，再和上一帧的 overlay 差值一起提交，
 * 避免覆盖 motion / expression / physics 的输出。
 */
export class ParamMap {
  private readonly applied = new Map<string, number>();
  private pending = new Map<string, number>();

  constructor(private readonly core: any) {}

  beginFrame(): void {
    this.pending = new Map();
  }

  add(id: string, delta: number): void {
    if (!Number.isFinite(delta)) return;
    this.pending.set(id, (this.pending.get(id) || 0) + delta);
  }

  commit(): void {
    if (!this.core) return;
    const ids = new Set<string>([...this.applied.keys(), ...this.pending.keys()]);
    for (const id of ids) {
      const next = this.pending.get(id) || 0;
      const prev = this.applied.get(id) || 0;
      const diff = next - prev;
      if (Math.abs(diff) > 1e-5) {
        try {
          this.core.addParameterValueById(id, diff, 1);
        } catch {
          // 参数不存在时静默跳过，避免一个可选参数拖垮整个循环。
        }
      }
      if (Math.abs(next) > 1e-5) this.applied.set(id, next);
      else this.applied.delete(id);
    }
  }

  reset(): void {
    if (!this.core) return;
    for (const [id, value] of this.applied) {
      try {
        this.core.addParameterValueById(id, -value, 1);
      } catch {
        // ignore
      }
    }
    this.applied.clear();
    this.pending.clear();
  }
}
