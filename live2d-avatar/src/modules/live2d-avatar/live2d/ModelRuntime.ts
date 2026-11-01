import { Application } from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display-mulmotion/cubism4';
import behavior from '../config/behavior.json';
import paramsConfig from '../config/params.json';
import type { AvatarEvent, AvatarMountOptions, AvatarHandle } from '../types';
import { BlinkController } from './BlinkController';
import { ParamMap } from './ParamMap';
import { PoseController } from './PoseController';
import { GestureController } from './GestureController';
import { HitTest } from '../interact/HitTest';
import { PointerController } from '../interact/Pointer';
import { Reflex } from '../interact/Reflex';
import { IdleBehavior } from '../idle/IdleBehavior';
import { EmotionMapper } from '../soul/EmotionMapper';
import { SpeakLayer } from '../soul/SpeakLayer';
import { ExpressionManager } from './ExpressionManager';

function idText(id: unknown): string {
  if (typeof id === 'string') return id;
  const anyId = id as any;
  if (anyId && typeof anyId.getString === 'function') return anyId.getString();
  return String(id);
}

export class ModelRuntime implements AvatarHandle {
  private readonly app: Application;
  private readonly canvas: HTMLCanvasElement;
  private model: any = null;
  private coreModel: any = null;
  private params: ParamMap | null = null;
  private blink: BlinkController | null = null;
  private reflex: Reflex | null = null;
  private idle: IdleBehavior | null = null;
  private emotion: EmotionMapper | null = null;
  private pose: PoseController | null = null;
  private gesture: GestureController | null = null;
  private speak: SpeakLayer | null = null;
  private expression: ExpressionManager | null = null;
  private voiceEnabled = false;
  private eyesClosed = false;
  private pointer: PointerController | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private destroyed = false;
  private paused = false;
  private baseY = 0;
  private tapTimes: number[] = [];
  private headTaps: number[] = [];
  private lastInteract = 0;
  private lonelyFired = false;
  private readonly tick = (): void => this.update();

  constructor(private readonly options: AvatarMountOptions) {
    const cap = options.pixelRatioCap ?? 2;
    this.app = new Application({
      resizeTo: options.container,
      backgroundAlpha: 0,
      antialias: true,
      autoDensity: true,
      resolution: Math.min(window.devicePixelRatio || 1, cap)
    });
    this.canvas = this.app.view as unknown as HTMLCanvasElement;
    this.canvas.style.touchAction = 'none';
    this.canvas.style.display = 'block';
    this.canvas.style.width = '100%';
    this.canvas.style.height = '100%';
    options.container.appendChild(this.canvas);
  }

  async load(): Promise<void> {
    try {
      const model = await Live2DModel.from(this.options.modelUrl, { autoInteract: false });
      if (this.destroyed) {
        model.destroy();
        return;
      }
      (model as any).autoUpdate = false;
      model.anchor.set(0.5, 0.5);
      this.app.stage.addChild(model);
      this.model = model;
      this.fit();

      const internal: any = model.internalModel;
      this.coreModel = internal.coreModel;
      const raw: any = this.coreModel?._model;
      this.params = new ParamMap(this.coreModel);
      this.blink = new BlinkController(this.params, behavior.blink as any);
      this.reflex = new Reflex(this.params, this.blink, behavior as any);
      this.idle = new IdleBehavior(this.params, behavior.idle as any);
      this.emotion = new EmotionMapper(this.params, this.idle, this.blink, (behavior as any).emotion, (behavior as any).social);
      this.pose = new PoseController(this.params, (behavior as any).pose, performance.now() / 1000);
      this.gesture = new GestureController(this.params);
      this.speak = new SpeakLayer();
      // 模型是异步加载的：宿主在 mount 后立刻开语音时 speak 还不存在，
      // 所以把开关缓存下来，SpeakLayer 创建时补一次，否则对话永远不出声。
      this.speak.setVoiceEnabled(this.voiceEnabled);
      this.expression = new ExpressionManager(model);

      // 单向消费灵魂状态：宿主注入 soul 才接，没有就纯本地生命感。
      try {
        this.options.soul?.onStateFrame((frame) => this.emotion?.push(frame));
        this.options.soul?.onSpeak((s) => {
          // 把当前情绪一起交给说话层：云端 TTS 据此带情绪念，而不是平铺直叙。
          const st = this.emotion?.debugState();
          this.speak?.speak(s.text, s.volume, st ? { valence: st.valence, arousal: st.arousal } : undefined);
        });
        this.options.soul?.onMemoryRecall((m) => this.emotion?.recall(m.salience));
      } catch {
        // soul 订阅失败不阻塞表现层。
      }

      const hitTest = new HitTest(this.canvas, model, behavior.hitZones as any);
      this.pointer = new PointerController(
        this.canvas,
        hitTest,
        {
          onTap: (hit) => {
            const affinity = this.emotion?.getAffinity() ?? 0.5;
            const now = performance.now();
            this.lastInteract = now;
            this.lonelyFired = false;
            this.reflex?.tap(hit.zone, hit.cx, hit.cy, affinity);
            this.pose?.tap(hit.zone, now);
            if (hit.zone === 'tail') this.gesture?.play('tailWag', 2.4);
            this.handleTapBurst(hit.zone, now);
            if (this.speak?.speaking()) {
              this.speak.interrupt();
              this.emotion?.startle();
            }
            this.emit('tap', { zone: hit.zone, cx: hit.cx, cy: hit.cy });
          },
          onDragStart: () => {
            this.lastInteract = performance.now();
            this.lonelyFired = false;
            this.reflex?.startDrag();
            this.emit('drag_start');
          },
          onDrag: (cx, cy) => {
            this.lastInteract = performance.now();
            this.reflex?.drag(cx, cy);
          },
          onDragEnd: () => {
            this.reflex?.endDrag();
            this.emit('drag_end');
          }
        },
        behavior.drag.threshold
      );

      if (typeof ResizeObserver !== 'undefined') {
        this.resizeObserver = new ResizeObserver(() => this.fit());
        this.resizeObserver.observe(this.options.container);
      } else {
        window.addEventListener('resize', this.fit);
      }

      const ids: any[] = raw?.parameters?.ids ?? [];
      const count = Number(raw?.parameters?.count ?? 0);
      const parameters = [];
      for (let i = 0; i < count; i++) {
        parameters.push({
          id: idText(ids[i]),
          min: this.coreModel.getParameterMinimumValue(i),
          max: this.coreModel.getParameterMaximumValue(i),
          def: this.coreModel.getParameterDefaultValue(i)
        });
      }
      const info = {
        coreVersion: (window as any).Live2DCubismCore?.Version?.csmGetVersion?.() ?? null,
        latestMoc: (window as any).Live2DCubismCore?.Version?.csmGetLatestMocVersion?.() ?? null,
        parameterCount: count,
        parameters,
        drawableCount: Number(raw?.drawables?.count ?? 0),
        partCount: Number(raw?.parts?.count ?? 0)
      };
      this.emit('ready', { info, version: paramsConfig.cubismCore.version });
      this.lastInteract = performance.now();
      this.app.ticker.add(this.tick);
    } catch (error) {
      this.emit('error', { message: String((error as Error)?.message || error) });
      throw error;
    }
  }

  pause(): void {
    if (this.destroyed) return;
    this.paused = true;
    this.app.ticker.stop();
  }

  resume(): void {
    if (this.destroyed) return;
    this.paused = false;
    this.app.ticker.start();
    this.fit();
  }

  sendUserInput(text: string, meta?: Record<string, unknown>): void {
    this.lastInteract = performance.now();
    this.lonelyFired = false;
    this.emit('user_input', { text, meta });
    try {
      this.options.soul?.sendUserInput(text, meta);
    } catch {
      // P0 里 soul 是可选的；宿主未注入时不阻塞交互。
    }
  }

  setVoiceEnabled(on: boolean): void {
    this.voiceEnabled = !!on;
    this.speak?.setVoiceEnabled(on);
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.pointer?.destroy();
    this.pointer = null;
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    window.removeEventListener('resize', this.fit);
    this.params?.reset();
    this.reflex?.reset();
    this.idle?.reset();
    this.pose = null;
    this.gesture?.reset();
    this.gesture = null;
    this.app.ticker.remove(this.tick);
    this.model = null;
    this.coreModel = null;
    this.params = null;
    this.blink = null;
    this.reflex = null;
    this.idle = null;
    this.emotion = null;
    this.speak = null;
    try {
      this.app.destroy(true, { children: true, texture: true, baseTexture: true });
    } catch {
      // 已经释放过就忽略。
    }
  }

  private readonly fit = (): void => {
    const model = this.model;
    if (!model) return;
    const width = this.options.container.clientWidth || window.innerWidth;
    const height = this.options.container.clientHeight || window.innerHeight;
    if (width <= 0 || height <= 0) return;
    this.app.renderer.resize(width, height);
    model.scale.set(1);
    const bounds = model.getLocalBounds();
    if (!bounds || bounds.width <= 0 || bounds.height <= 0) return;
    const scale = Math.min(
      (width * behavior.layout.fit) / bounds.width,
      (height * behavior.layout.fit) / bounds.height
    );
    model.scale.set(scale);
    model.x = width / 2;
    model.y = height * behavior.layout.centerY;
    this.baseY = model.y;
  };

  private update(): void {
    if (this.destroyed || this.paused || !this.model || !this.params) return;
    const dtMs = this.app.ticker.deltaMS;
    const dt = Math.min(dtMs / 1000, 0.05);
    const nowSec = performance.now() / 1000;

    // 整体漂浮：像泡在水里一样轻微上下游动，不改模型参数，只动容器位置。
    this.model.y = this.baseY + Math.sin(nowSec * 0.55) * 4 + Math.sin(nowSec * 1.7) * 1.2;

    // 长时间没人理：低头委屈并上报一次。
    if (!this.lonelyFired && this.lastInteract > 0 && performance.now() - this.lastInteract > 120000) {
      this.lonelyFired = true;
      this.emotion?.nudge(-0.3, -0.12, 6);
      this.pose?.set('sad');
      this.emit('lonely');
    }

    // 顺序固定：motion/physics 先跑，再叠加本层的加性参数。
    this.model.update(dtMs);
    this.params.beginFrame();

    // 水印消除：模型默认 Paramcol_3=0 时显示水印，常驻加 1 隐藏；
    // 走参数通道而不是表情槽位，避免表情差分切换时把水印消除覆盖掉。
    this.params.add('Paramcol_3', 1);

    // 生命感（P1）：噪声驱动，无周期；reflex 活跃时 gaze/头部通道让位。
    const attention = this.reflex?.attentionWeight() ?? 0;
    this.idle?.update(dt, attention);
    // 姿势层：大姿态基线，交互时头部让位给躲闪，身体/手臂保持。
    this.pose?.update(dt, performance.now() / 1000, attention);
    this.gesture?.update(dt);
    this.emotion?.update(dt);
    this.speak?.tick(dt, this.params);
    // 注意：这里必须传绝对时间戳；传 dtMs（每帧约 16ms）会让表情防抖永远不通过、锁死在第一个表情。
    this.expression?.update(performance.now(), {
      valence: this.emotion?.debugState().valence ?? 0,
      arousal: this.emotion?.debugState().arousal ?? 0,
      affinity: this.emotion?.getAffinity() ?? 0.5,
      recallT: this.emotion?.debugRecallT?.() ?? -1,
      startleT: this.emotion?.debugStartleT?.() ?? -1,
      speaking: this.speak?.speaking() ?? false,
    });

    this.reflex?.update(dt);
    this.blink?.tick(dt);
    this.params.commit();
    if (this.eyesClosed && this.coreModel
        && typeof this.coreModel.setParameterValueById === 'function') {
      // 直接写绝对值：ParamMap 的加性 overlay 不会每帧重复扣减，眨眼层会把眼睛重新撑开。
      try {
        this.coreModel.setParameterValueById('ParamEyeLOpen', 0);
        this.coreModel.setParameterValueById('ParamEyeROpen', 0);
      } catch {
        // 模型没有这个参数时忽略
      }
    }
  }

  /** 验收用：直接读 core 当前实际参数值（含 motion/physics/overlay 合成结果）。 */
  debugSample(): Record<string, number> {
    const out: Record<string, number> = {};
    if (!this.coreModel || typeof this.coreModel.getParameterValueById !== 'function') return out;
    const want = [
      'ParamBreath', 'ParamAngleX', 'ParamAngleY', 'ParamAngleZ', 'ParamBodyAngleZ',
      'ParamBodyAngleZ1', 'ParamBodyAngleZ2', 'ParamBodyAngleX', 'ParamBodyAngleY',
      'ParamEyeBallX', 'ParamEyeBallY', 'ParamEyeLOpen', 'ParamEyeROpen',
      'ParamEyeSmile', 'ParamEyeAnger', 'ParamMouthForm', 'ParamBrowLY', 'ParamBrowRY',
      'ParamBrowLForm', 'ParamBrowRForm', 'ParamMouthOpenY', 'ParamMouthX',
      'Param_arm_L1', 'Param_arm_L2', 'Param_arm_L3', 'Param_arm_R1', 'Param_arm_R2', 'Param_arm_R3',
      'Paramcol_1', 'Paramcol_2',
      'Param_Angle_Rotation_2_ArtMesh367', 'Param_Angle_Rotation_3_ArtMesh367'
    ];
    for (const id of want) {
      try {
        out[id] = Number(this.coreModel.getParameterValueById(id));
      } catch {
        // 参数不存在就跳过。
      }
    }
    return out;
  }

  /** 验收用：当前表情槽位索引（null=尚未切换过）。 */
  debugExpression(): number | null {
    return this.expression?.debugIndex() ?? null;
  }

  /** 验收用：当前姿势名。 */
  debugPose(): string {
    return this.pose?.debugCurrent() ?? 'none';
  }

  /** 验收用：正在播放的动作。 */
  debugGesture(): string[] {
    return this.gesture?.running ?? [];
  }

  /** 宿主/验收用：主动播放一个动作（wave/coverMouth/coverFace/nod/shake/hop/stretch/earDrop/tailHide/tailWag）。 */
  playGesture(name: string, dur = 2.4): void {
    this.gesture?.play(name, dur);
  }

  /** 宿主用：切换姿势（idle/tilt/curious/side/shy/stretch/turn/relax/sad/angry）。 */
  setPose(name: string): void {
    this.pose?.set(name);
  }

  /** 宿主用：摄像头人脸坐标驱动眼珠和头部，坐标范围 -1..1。 */
  lookAt(cx: number, cy: number, weight = 0.8): void {
    this.reflex?.lookAt(cx, cy, weight);
  }

  clearLook(): void {
    this.reflex?.clearLook();
  }

  /** 隐私/闭眼：强制合上眼睛；恢复时先把眼睛撑开，再交给 blink 层。 */
  setEyesClosed(on: boolean): void {
    const next = !!on;
    if (!next && this.eyesClosed && this.coreModel
        && typeof this.coreModel.setParameterValueById === 'function') {
      try {
        this.coreModel.setParameterValueById('ParamEyeLOpen', 1);
        this.coreModel.setParameterValueById('ParamEyeROpen', 1);
      } catch {
        // ignore
      }
    }
    this.eyesClosed = next;
  }

  /** 连击判定：摸头 3 次害羞捂脸，乱戳 4 次生气；普通点击给轻动作。 */
  private handleTapBurst(zone: string, now: number): void {
    this.tapTimes = this.tapTimes.filter((t) => now - t < 3000);
    this.tapTimes.push(now);
    if (zone === 'head') {
      this.headTaps = this.headTaps.filter((t) => now - t < 4000);
      this.headTaps.push(now);
    }
    if (this.headTaps.length >= 3) {
      this.headTaps = [];
      this.tapTimes = [];
      this.emotion?.nudge(0.55, 0.45, 4);
      this.gesture?.play('coverFace', 3.0);
      this.gesture?.play('earDrop', 2.4);
      this.emit('head_hug');
      return;
    }
    if (this.tapTimes.length >= 4) {
      this.tapTimes = [];
      this.emotion?.nudge(-0.55, 0.5, 4);
      this.gesture?.play('shake', 1.4);
      this.pose?.set('angry');
      this.emit('annoyed');
      return;
    }
    if (zone === 'head') this.gesture?.play('nod', 1.2);
    else if (zone === 'body') this.gesture?.play('coverMouth', 1.6);
  }

  private emit(type: string, payload?: unknown): void {
    const event: AvatarEvent = { type, payload };
    try {
      this.options.onEvent?.(event);
    } catch {
      // 宿主埋点异常不能影响表现层。
    }
  }
}
