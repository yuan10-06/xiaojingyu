import type { SoulAdapter } from './soul/SoulAdapter';

export interface AvatarEvent {
  type: string;
  payload?: unknown;
}

export interface AvatarMountOptions {
  container: HTMLElement;
  modelUrl: string;
  soul?: SoulAdapter;
  pixelRatioCap?: number;
  onEvent?: (event: AvatarEvent) => void;
}

export interface AvatarHandle {
  destroy(): void;
  pause(): void;
  resume(): void;
  sendUserInput(text: string, meta?: Record<string, unknown>): void;
  /** 开启/关闭说话语音（Web Speech API，失败自动静音）。 */
  setVoiceEnabled(on: boolean): void;
  /** 开发/验收用：读关键参数的当前实际值。 */
  debugSample?(): Record<string, number>;
  /** 开发/验收用：读当前表情槽位。 */
  debugExpression?(): number | null;
  /** 开发/验收用：读当前姿势名。 */
  debugPose?(): string;
  /** 开发/验收用：正在播放的动作名。 */
  debugGesture?(): string[];
  /** 主动播放一个动作。 */
  playGesture?(name: string, dur?: number): void;
  /** 切换姿势。 */
  setPose?(name: string): void;
  /** 摄像头人脸坐标驱动眼珠/头部，范围 -1..1。 */
  lookAt?(cx: number, cy: number, weight?: number): void;
  /** 回到自然 idle 注视。 */
  clearLook?(): void;
  /** 强制闭眼/恢复眨眼。 */
  setEyesClosed?(on: boolean): void;
  /** 设置表情权重（3D 专用）。 */
  setEmotion?(name: string, weight: number, hold?: number): void;
  /** 校准用：直接把某根骨骼转到指定世界轴角度。 */
  debugSetBone?(bone: string, x: number, y: number, z: number): void;
  /** 校准用：关键骨骼世界坐标。 */
  debugWorld?(): Record<string, number>;
}
