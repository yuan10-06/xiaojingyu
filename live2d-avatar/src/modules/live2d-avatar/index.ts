import { ModelRuntime } from './live2d/ModelRuntime';
import type { AvatarHandle, AvatarMountOptions } from './types';

export type { AvatarEvent, AvatarHandle, AvatarMountOptions } from './types';
export type { SoulAdapter, StateFrame } from './soul/SoulAdapter';

/**
 * 宿主唯一入口：挂载 / 销毁 / 暂停 / 恢复 / 上报用户输入。
 * 表现层不读写 brainN 数据库、记忆和配置。
 */
export function mount(options: AvatarMountOptions): AvatarHandle {
  const runtime = new ModelRuntime(options);
  void runtime.load().catch(() => {
    // 错误已经通过 onEvent('error') 上报，这里只兜住 Promise。
  });
  return {
    destroy: () => runtime.destroy(),
    pause: () => runtime.pause(),
    resume: () => runtime.resume(),
    sendUserInput: (text, meta) => runtime.sendUserInput(text, meta),
    setVoiceEnabled: (on) => runtime.setVoiceEnabled(on),
    debugSample: () => runtime.debugSample(),
    debugExpression: () => runtime.debugExpression(),
    debugPose: () => runtime.debugPose(),
    debugGesture: () => runtime.debugGesture(),
    playGesture: (name, dur) => runtime.playGesture(name, dur),
    setPose: (name) => runtime.setPose(name),
    lookAt: (cx, cy, weight) => runtime.lookAt(cx, cy, weight),
    clearLook: () => runtime.clearLook(),
    setEyesClosed: (on) => runtime.setEyesClosed(on),
  };
}
