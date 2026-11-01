# Windows 构建与打包

## 环境

- Windows 10/11
- Python 3.13（建议使用虚拟环境）
- WebView2 Runtime（Windows 11 通常已自带）
- Node.js 22+（桌面桌宠 Electron 运行时）
- Inno Setup 6（生成安装包）

## 源码运行

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python desktop_main.py
```

调试参数：

```powershell
python desktop_main.py --debug
python desktop_main.py --smoke --allow-multi --port 8899
python desktop_main.py --window-smoke 5 --allow-multi
```

## PyInstaller

```powershell
.venv\Scripts\python.exe -m PyInstaller --noconfirm Desktop.spec
```

输出在 `dist/BrainN/`，入口是 `小鲸鱼.exe`。`web/`、`config/`、`assets/`、`desktop_runtime/` 需要和 exe 放在同一目录。

## 安装包

安装脚本是 `build_desktop/installer.iss`，用 Inno Setup 6 编译：

```powershell
& "C:\Users\<你>\AppData\Local\InnoSetup6\ISCC.exe" "build_desktop\installer.iss"
```

安装包输出到 `dist_desktop/`。安装时会执行 `--reset-persona` 和 `--reset-splash-identity`，首次启动重新随机初始人设。

## 注意

- 不要把 `.env`、`config/*_overrides.yaml`、`data/`、`logs/`、`persona_seed.json` 打进安装包。
- 不要把安装包提交进 Git；放 Releases。
- 公开版请确认开屏素材、字体、Live2D 模型和第三方代码的授权。
