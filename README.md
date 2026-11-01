<div align="center">

<img src="docs/assets/icon.png" width="96" alt="小鲸鱼图标">

# 小鲸鱼 · BrainN

### 本地优先、有长期记忆和人格连续性的 AI 桌面伴侣

Windows 桌面版 · Android

[下载 Windows 安装包](https://github.com/yuan10-06/xiaojingyu/releases/latest) ·
[快速开始](#快速开始) ·
[架构说明](docs/ARCHITECTURE.md) ·
[常见问题](docs/FAQ.md) ·
[参与贡献](CONTRIBUTING.md)

<img src="docs/assets/hero.png" width="860" alt="小鲸鱼开屏">

</div>

> 她不是一个新的聊天框。她住在你的桌面里，记得你们聊过的事，会因为天气和心情变化，也会在你离开电脑时自己待着。

## 她是什么

小鲸鱼是一个本地优先的 AI 桌面伴侣：

- **有记忆**：聊天、事件、关系和生活记录保存在本地记忆库，重启后仍能接着聊。
- **有人格**：同一份人格贯穿聊天、2D 形象和桌面桌宠，不是三套互不相干的设定。
- **有生活**：天气、城市、日程、心情和主动消息，让她的反应不是随机文案。
- **有仪式感**：启动动画、随机初始人设、主题和音色，都可以按你的喜好调整。
- **本地优先**：聊天和记忆默认留在本机；只有调用大模型时，当前对话才会发到你配置的 API。

## 亮点

| 功能 | 说明 |
|---|---|
| 开屏动画 | 黑幕、鲸鱼标识、授权序列、揭幕；支持预览和自定义文案/主题/速度 |
| 随机初始人设 | 新用户版安装包首次启动随机生成学校、专业、城市、爱好、兼职；城市和天气自动对齐 |
| 长期记忆 | 本地记忆库 + 全量记忆，重启后仍能记得之前的事 |
| 桌面桌宠 | 透明小窗，可拖拽、隐藏、唤回；带余额和工作状态动画 |
| Android | 摇一摇手机，桌宠在屏幕里碰撞；再点一下固定位置 |
| 世界 | 双城天气、距离、她的城市、日程和常去的地方 |
| 可自定义 | 开屏文案、主题、速度、音色、模型和 API 地址 |

## 快速开始

### Windows

1. 从 [Releases](https://github.com/yuan10-06/xiaojingyu/releases/latest) 下载 `xiaojingyu-Setup-v9.10.exe`。
2. 安装。安装包未签名，SmartScreen 提示时选择“更多信息 → 仍要运行”。
3. 启动后填入 DeepSeek API Key；也可以先跳过，之后再补。
4. 安装时会重置初始人设，聊天记录和记忆库不会被删除。

### Android

1. 从 [Releases](https://github.com/yuan10-06/xiaojingyu/releases/latest) 下载 `xiaojingyu-v9.10.apk`。
2. 允许“安装未知应用”后安装。
3. 源码构建需要 JDK 17、Android SDK 和 Chaquopy，详见 [docs/BUILD_ANDROID.md](docs/BUILD_ANDROID.md)。

## 从源码运行

```bash
git clone https://github.com/yuan10-06/xiaojingyu.git
cd xiaojingyu
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python desktop_main.py
```

桌面桌宠需要 Node.js 和 Electron 运行时；构建与打包见 [docs/BUILD.md](docs/BUILD.md)。

> 仓库不包含第三方 Live2D 模型、字体和 Cubism Core。2D Live2D 形象需要你自备有授权的模型；桌面桌宠、聊天和记忆功能不受影响。说明见 [docs/ASSETS_NOT_INCLUDED.md](docs/ASSETS_NOT_INCLUDED.md)。

## 隐私

- API Key 只保存在本机。
- 聊天、人设、记忆和设置默认保存在 `%LOCALAPPDATA%\BrainN`。
- 只有调用大模型、天气或地图服务时才会出网。
- 卸载不会删除聊天和记忆；需要彻底清理由你手动删除数据目录。

## 架构

小鲸鱼使用 Brain-Truth 架构：六层结构 + 具身 IO + 可插拔记忆卡。人格不是一段提示词，而是由构成、记忆、情绪、实践和版本链共同维持的连续体。

详细说明见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## Roadmap

- [x] Windows 桌面版
- [x] Android 版
- [x] 开屏动画与随机初始人设
- [ ] 人设分享卡导出
- [ ] 更多桌宠动作和互动
- [ ] 主题与音色市场

## 贡献

欢迎提 Issue 和 PR。可以先从 `good first issue` 开始；提交前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

代码使用 MIT License，见 [LICENSE](LICENSE)。随仓库分发的素材授权与第三方组件见 [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md)。

## 免责声明

小鲸鱼是个人开源项目，与 DeepSeek 官方无关。DeepSeek 仅作为可选的模型 API 接入；开屏中的品牌素材仅用于说明兼容性，不代表官方 affiliation。
