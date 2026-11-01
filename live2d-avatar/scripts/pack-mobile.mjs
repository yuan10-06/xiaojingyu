import { execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

// 打包小鲸鱼交互层到 App：vite lib 构建 → 拷贝 JS/Core/模型到 mobile/web/whale/。
const root = path.resolve(import.meta.dirname, '..');
const target = path.join(root, '..', 'mobile', 'web', 'whale');
const modelSrc = path.join(root, 'public', 'live2d', 'whale_girl');
const modelDst = path.join(target, 'model');

execSync('npx vite build --config vite.lib.config.ts', { cwd: root, stdio: 'inherit' });

fs.mkdirSync(target, { recursive: true });
fs.copyFileSync(path.join(root, 'dist-lib', 'whale-avatar.js'), path.join(target, 'whale-avatar.js'));
fs.copyFileSync(path.join(root, 'public', 'live2dcubismcore.min.js'), path.join(target, 'live2dcubismcore.min.js'));
fs.copyFileSync(path.join(root, 'public', 'scene_bg.jpg'), path.join(target, 'scene_bg.jpg'));

fs.rmSync(modelDst, { recursive: true, force: true });
fs.cpSync(modelSrc, modelDst, { recursive: true });

const size = (p) => fs.statSync(p).size;
console.log('packed ->', target);
console.log('whale-avatar.js', Math.round(size(path.join(target, 'whale-avatar.js')) / 1024) + 'KB');
