import type { ParamMap } from './ParamMap';

interface Active {
  name: string;
  t: number;
  dur: number;
}

/** attack → hold → release 包络，让动作起落都不生硬。 */
const ease = (p: number): number => {
  const attack = 0.15;
  const release = 0.76;
  if (p < attack) return p / attack;
  if (p > release) return Math.max(0, (1 - p) / (1 - release));
  return 1;
};

const TAIL = [
  'Param_Angle_Rotation_2_ArtMesh367',
  'Param_Angle_Rotation_3_ArtMesh367',
  'Param_Angle_Rotation_4_ArtMesh367',
  'Param_Angle_Rotation_5_ArtMesh367',
  'Param_Angle_Rotation_6_ArtMesh367'
];

/**
 * 短动作层：叠加在姿势基线之上的一次性动作。
 * 招手 / 捂嘴 / 捂脸 / 点头 / 摇头 / 蹦 / 耳朵尾巴特效 / 摇尾巴。
 * 可并发（最多 3 个），动作结束后自动回到基线，不残留参数。
 */
export class GestureController {
  private actives: Active[] = [];

  constructor(private readonly params: ParamMap) {}

  play(name: string, dur: number): void {
    if (this.actives.length >= 3) this.actives.shift();
    this.actives.push({ name, t: 0, dur });
  }

  get running(): string[] {
    return this.actives.map((g) => g.name);
  }

  update(dt: number): void {
    if (!this.actives.length) return;
    // 多动作并发时同一参数取"绝对值最大"的那一个，绝不做加法叠加，避免超出参数范围穿模。
    const acc = new Map<string, number>();
    const merge = (id: string, v: number): void => {
      const prev = acc.get(id) || 0;
      if (Math.abs(v) > Math.abs(prev)) acc.set(id, v);
    };
    const keep: Active[] = [];
    for (const g of this.actives) {
      g.t += dt;
      const p = Math.min(1, g.t / g.dur);
      this.collect(g.name, p, ease(p), merge);
      if (g.t < g.dur) keep.push(g);
    }
    for (const [id, v] of acc) this.params.add(id, v);
    this.actives = keep;
  }

  reset(): void {
    this.actives = [];
  }

  private collect(name: string, p: number, env: number, put: (id: string, v: number) => void): void {
    const add = (id: string, v: number): void => {
      put(id, v * env);
    };
    // 开关型参数（耳朵/尾巴消失）不乘包络，直接用目标值。
    const set = (id: string, v: number): void => {
      put(id, v);
    };

    switch (name) {
      case 'wave':
        add('Param_arm_R1', -0.45);
        add('Param_arm_R2', 0.42 * Math.sin(p * Math.PI * 4));
        add('ParamMouthForm', 0.15);
        add('ParamAngleY', 2 * Math.sin(p * Math.PI * 2));
        break;
      case 'coverMouth':
        add('Param_arm_R1', -0.5);
        add('Param_arm_R2', 0.6);
        add('Param_arm_R3', 0.3);
        add('ParamMouthForm', 0.3);
        break;
      case 'coverFace':
        add('Param_arm_L1', -0.5);
        add('Param_arm_R1', -0.5);
        add('Param_arm_L2', 0.6);
        add('Param_arm_R2', 0.6);
        add('ParamAngleX', -10);
        add('ParamBodyAngleX', 2);
        break;
      case 'nod':
        add('ParamAngleX', -7 * Math.sin(p * Math.PI * 4));
        break;
      case 'shake':
        add('ParamAngleY', 7 * Math.sin(p * Math.PI * 5));
        break;
      case 'hop':
        add('ParamAngleX', -6.5 * Math.sin(p * Math.PI));
        add('ParamBodyAngleX', -2.6 * Math.sin(p * Math.PI));
        break;
      case 'stretch':
        add('Param_arm_L1', -0.55);
        add('Param_arm_R1', -0.55);
        add('Param_arm_L2', -0.3);
        add('Param_arm_R2', -0.3);
        add('ParamAngleX', -6 * Math.sin(p * Math.PI));
        add('ParamBodyAngleX', -2 * Math.sin(p * Math.PI));
        break;
      case 'earDrop':
        if (p < 0.76) set('Paramcol_2', 1);
        break;
      case 'tailHide':
        if (p < 0.76) set('Paramcol_1', 2);
        break;
      case 'tailWag':
        TAIL.forEach((id, i) => {
          add(id, 0.38 * Math.sin(p * Math.PI * 5 - i * 0.55));
        });
        break;
      case 'tilt':
        add('ParamAngleZ', 8 * Math.sin(p * Math.PI));
        add('ParamAngleY', 3 * Math.sin(p * Math.PI));
        add('ParamAngleX', -3 * Math.sin(p * Math.PI));
        add('ParamBodyAngleX', 1.5 * Math.sin(p * Math.PI));
        break;
      case 'yawn':
        add('ParamMouthForm', -0.28 * Math.sin(p * Math.PI));
        add('ParamMouthOpenY', 0.6 * Math.sin(p * Math.PI));
        add('Param_arm_R1', -0.42 * Math.sin(p * Math.PI));
        add('ParamAngleX', -8 * Math.sin(p * Math.PI));
        break;
      case 'heart':
        add('Param_arm_L1', -0.34);
        add('Param_arm_R1', -0.34);
        add('Param_arm_L2', 0.52);
        add('Param_arm_R2', 0.52);
        add('ParamMouthForm', 0.42);
        add('ParamAngleY', 4 * Math.sin(p * Math.PI));
        break;
      default:
        break;
    }
  }
}
