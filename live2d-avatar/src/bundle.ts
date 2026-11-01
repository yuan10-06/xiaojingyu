import { mount } from './modules/live2d-avatar/index';
import { LocalSoulAdapter } from './modules/live2d-avatar/soul/LocalSoulAdapter';

// 打包成单文件 IIFE，供 App WebView 里的 whale.html 使用。7.5 起只保留 2D。
(window as any).WhaleAvatar = { mount, LocalSoulAdapter };
