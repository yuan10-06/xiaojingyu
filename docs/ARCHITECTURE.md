# 架构说明

小鲸鱼不是“一个提示词 + 一个聊天框”，而是一套持续运行的本地人格系统。

## 整体结构

```text
pywebview / Android WebView
        │
        ▼
mobile_server.py  ── HTTP / SSE ──  网页界面
        │
        ▼
      main.py
        │
        ├── brainn.core.BrainNCore      核心状态与模块注册
        ├── brainn.core.ShadowRuntime   时间 / 感知 / 驱力 / 实践 / 世界 / 社会 / 冲突 / 无意识 / 叙事
        ├── brainn.memory               长期记忆与全量记忆
        ├── brainn.persona              人格、关系、禁忌、说话方式
        ├── brainn.weather              城市天气与心情影响
        └── brainn.llm                  DeepSeek / OpenAI 兼容模型
```

## 六层结构

1. **构成**：她是谁，核心特质、关系、边界和禁忌。
2. **记忆**：聊天、事件、关系、生活记录，以及可选的共享记忆库。
3. **情绪**：心情、驱力、身体状态和天气影响。
4. **实践**：她每天做什么，日程、习惯和主动行为。
5. **社会**：她与用户、角色和外部世界的关系网。
6. **版本链**：人格演化记录、关键转折和连续性。

## 具身 IO

- Windows：pywebview + WebView2 主窗，Electron 透明桌宠。
- Android：Java + Chaquopy + WebView，桌宠支持重力/摇一摇碰撞。
- 聊天、2D 形象和桌宠共用同一份人格、记忆和心情。

## 记忆

- 默认数据库：`%LOCALAPPDATA%\BrainN\data\ganfanyu.db`。
- 全量记忆可在设置里开启，保存到用户指定目录。
- 记忆只在本地读写；调用模型时按需要拼接上下文。

## 人格与城市

- 新用户版安装包首次启动生成随机初始人设，种子保存在数据目录。
- 人设城市是天气城市的唯一来源，避免“人格页南京、架构页郑州”。
- 用户可以通过对话式人设调整修改城市，保存时会同步天气。

## 更多

更细的 Brain-Truth 设计与复刻说明暂不随仓库发布；需要讨论实现细节可以在 Issue 里交流。
