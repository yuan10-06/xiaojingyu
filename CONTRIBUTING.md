# 贡献指南

感谢你愿意帮小鲸鱼变得更好。

## 先提 Issue

- Bug 请附上系统版本、复现步骤、日志或截图。
- 新功能请先描述使用场景，不要直接提交大改动。
- 安全问题请不要公开贴在 Issue 里，见 [SECURITY.md](SECURITY.md)。

## 提交 PR

1. Fork 仓库并从 `main` 建分支。
2. 只改和当前问题相关的代码，避免顺手重构。
3. 本地至少跑一次：

```bash
python -m py_compile mobile_server.py desktop_main.py
python desktop_main.py --smoke --allow-multi --port 8899
```

4. PR 描述写清楚：改了什么、为什么改、怎么验证。
5. 不要提交 `.env`、API Key、记忆库、日志、安装包和第三方未授权素材。

## 代码风格

- Python 4 空格缩进，遵循现有文件风格。
- 前端优先用项目已有工具函数，不引入新框架。
- 新增用户可见文案使用中文；代码注释简洁，不写废话。
- 不提交二进制大文件；安装包和 APK 走 Releases。

## 素材

美术、语音、字体和 Live2D 模型请确认你有分发权。仓库默认不接收来源不明的素材。
