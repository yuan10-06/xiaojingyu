# 仓库未包含的素材

为了不把来源不明的第三方素材带进开源仓库，以下内容默认不提交：

## Live2D 模型

- `mobile/web/whale/model/`
- `live2d-avatar/assets/whale_girl/`
- `live2d-avatar/public/live2d/`

你需要自备有分发权的 Live2D 模型，放到对应目录。模型文件通常包括：

```text
*.model3.json
*.moc3
*.physics3.json
*.cdi3.json
EXP/*.exp3.json
*.8192/texture_00.png
```

## 字体

- `mobile/web/whale/fonts/ShangshouSoftCandy.ttf`

请替换为你确认可商用的字体，或使用系统字体回退。

## Cubism Core

- `mobile/web/whale/live2dcubismcore.min.js`
- `live2d-avatar/public/live2dcubismcore.min.js`

从 Live2D 官方获取并遵守其许可；不要直接复制来源不明的版本。

## 没有这些素材会怎样

- 2D Live2D 形象可能无法渲染或回退到静态图。
- 桌面桌宠、聊天、记忆、开屏和世界功能不受影响。
- 安装包和 APK 的正式分发版本可以包含你有权分发的素材；仓库本身保持干净。
