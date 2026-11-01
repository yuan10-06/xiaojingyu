# Android 构建

Android 端使用 Java + Chaquopy + WebView，Python 代码和网页资源随 APK 一起打包。

## 环境

- JDK 17
- Android SDK（compileSdk 以 `android/app/build.gradle` 为准）
- Gradle 8.9（仓库不包含 `tools/`，可使用系统 Gradle 或 Android Studio）
- Python 3.13（Chaquopy 构建时使用）

## 构建

1. 在 `android/local.properties` 里写 `sdk.dir=<你的 Android SDK 路径>`（该文件不提交）。
2. 准备 `android/app/src/main/assets/seed.zip`。该文件由干净的 `config/`、`assets/`、`mobile/web/` 打包生成，仓库不包含它，避免把第三方模型/字体和用户数据带进 Git。
3. 执行：

```powershell
cd android
gradle assembleDebug
```

4. APK 在 `android/app/build/outputs/apk/`。

## 说明

- `android/app/src/main/python/` 是移动端 Python 运行副本。
- `android/app/src/main/assets/seed.zip` 里不要放 `.env`、API Key、记忆库、日志和用户人设覆盖。
- 公开版需要确认 Live2D 模型、字体和 Cubism Core 的分发授权，见 [ASSETS_NOT_INCLUDED.md](ASSETS_NOT_INCLUDED.md)。
