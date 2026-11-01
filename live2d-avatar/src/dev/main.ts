import { mount } from '../modules/live2d-avatar/index';
import { MockSoulAdapter } from '../modules/live2d-avatar/soul/MockSoulAdapter';
import type { AvatarEvent } from '../modules/live2d-avatar/types';

declare global {
  interface Window {
    __live2dInfo: any;
    __avatar: any;
    __mockSoul: MockSoulAdapter;
    __lastAvatarEvent: any;
    __simulateTap: (x: number, y: number) => void;
    __simulateDrag: (x0: number, y0: number, x1: number, y1: number) => void;
    __avatarEvents: any[];
    __remount: () => Promise<boolean>;
  }
}

const hud = document.getElementById('hud') as HTMLDivElement;
const stage = document.getElementById('stage') as HTMLDivElement;
let info: any = null;
let lastEvent = '等待交互';

function render(): void {
  if (!info) {
    hud.innerHTML = '<b>Live2D Avatar</b>\n' + lastEvent;
    return;
  }
  const s = window.__mockSoul?.getState?.();
  const soulLine = s ? '<b>情绪</b> v ' + s.valence.toFixed(2) + ' · a ' + s.arousal.toFixed(2) : '';
  hud.innerHTML = [
    '<b>Core</b> ' + info.coreVersion + ' / moc3 v' + info.latestMoc,
    '<b>模型</b> 大肥鱼 · 参数 ' + info.parameterCount + ' · Drawable ' + info.drawableCount + ' · Part ' + info.partCount,
    '<b>水印</b> Paramcol_3 = 1',
    soulLine,
    '<b>交互</b> ' + lastEvent
  ].filter(Boolean).join('\n');
}

const events: any[] = [];
window.__avatarEvents = events;

function handleEvent(event: AvatarEvent): void {
  window.__lastAvatarEvent = event;
  events.push({ at: Math.round(performance.now()), type: event.type, payload: event.payload });
  if (events.length > 120) events.shift();
  const payload: any = event.payload || {};
  if (event.type === 'ready') {
    info = payload.info;
    window.__live2dInfo = payload.info;
  } else if (event.type === 'tap') {
    lastEvent = 'tap · ' + payload.zone + ' (x ' + Number(payload.cx).toFixed(2) + ', y ' + Number(payload.cy).toFixed(2) + ')';
  } else if (event.type === 'drag_start') {
    lastEvent = 'drag · 跟手';
  } else if (event.type === 'drag_end') {
    lastEvent = 'drag · 松手回弹';
  } else if (event.type === 'error') {
    lastEvent = '加载失败：' + payload.message;
  } else if (event.type === 'user_input') {
    lastEvent = 'user_input · ' + payload.text;
  }
  render();
}

render();

const mockSoul = new MockSoulAdapter();
window.__mockSoul = mockSoul;
setInterval(render, 500);

const mountOptions = {
  container: stage,
  modelUrl: encodeURI('/live2d/whale_girl/大肥鱼.model3.json'),
  soul: mockSoul,
  pixelRatioCap: 2,
  onEvent: handleEvent
};

let avatar = mount(mountOptions);
window.__avatar = avatar;

// 内存验收用：完整 destroy 后重新 mount。
window.__remount = async () => {
  avatar.destroy();
  await new Promise((r) => setTimeout(r, 300));
  const canvasEl = stage.querySelector('canvas');
  if (canvasEl) canvasEl.remove();
  avatar = mount(mountOptions);
  window.__avatar = avatar;
  await new Promise((r) => setTimeout(r, 1500));
  return true;
};

function canvas(): HTMLElement | null {
  return stage.querySelector('canvas');
}

window.__simulateTap = (x: number, y: number) => {
  const target = canvas();
  if (!target) return;
  const base = { bubbles: true, cancelable: true, pointerId: 1, pointerType: 'touch', isPrimary: true, button: 0 };
  target.dispatchEvent(new PointerEvent('pointerdown', { ...base, clientX: x, clientY: y }));
  target.dispatchEvent(new PointerEvent('pointerup', { ...base, clientX: x, clientY: y }));
};

window.__simulateDrag = (x0: number, y0: number, x1: number, y1: number) => {
  const target = canvas();
  if (!target) return;
  const base = { bubbles: true, cancelable: true, pointerId: 2, pointerType: 'touch', isPrimary: true, button: 0 };
  target.dispatchEvent(new PointerEvent('pointerdown', { ...base, clientX: x0, clientY: y0 }));
  for (let i = 1; i <= 6; i++) {
    target.dispatchEvent(new PointerEvent('pointermove', {
      ...base,
      clientX: x0 + ((x1 - x0) * i) / 6,
      clientY: y0 + ((y1 - y0) * i) / 6
    }));
  }
  target.dispatchEvent(new PointerEvent('pointerup', { ...base, clientX: x1, clientY: y1 }));
};
