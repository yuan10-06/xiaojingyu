"""BrainN 桌面版启动入口（P0）。

用法：
  python desktop_main.py                 打开桌面窗口
  python desktop_main.py --smoke         只起本地服务做冒烟，不开窗
  python desktop_main.py --window-smoke 5 开窗 5 秒后自动关闭（自测用）
  python desktop_main.py --portable      数据放在运行目录旁的 data/
"""
from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BrainN 桌面版")
    parser.add_argument("--port", type=int, default=8765, help="本地服务端口，占用时自动换端口")
    parser.add_argument("--data-dir", default="", help="覆盖数据目录（默认 %%LOCALAPPDATA%%\\BrainN\\data）")
    parser.add_argument("--portable", action="store_true", help="数据放在运行目录旁的 data/")
    parser.add_argument("--debug", action="store_true", help="打开 pywebview 调试")
    parser.add_argument("--smoke", action="store_true", help="只启动服务并检查接口，不开窗")
    parser.add_argument("--window-smoke", type=float, default=0, help="开窗后 N 秒自动关闭")
    parser.add_argument("--check-bridge", action="store_true", help="开窗后检查 desktop bridge 并自动关闭")
    parser.add_argument("--check-ui", action="store_true", help="开窗后逐个切换页面巡检并自动关闭")
    parser.add_argument("--check-pet", action="store_true", help="开启桌宠并检查桌宠窗口后自动关闭")
    parser.add_argument("--autostart", action="store_true", help="登录自启：不弹主窗，只在托盘和桌宠待命")
    parser.add_argument("--allow-multi", action="store_true", help="跳过单实例检查")
    return parser


def main(argv: list[str] | None = None) -> int:
    if "--pet-process" in sys.argv:
        # 打包后桌宠子进程复用同一个 exe
        sys.argv = [a for a in sys.argv if a != "--pet-process"]
        import desktop_pet

        desktop_pet.main()
        return 0

    if "--reset-splash-identity" in sys.argv:
        # 安装新用户版时由安装程序调用：只重置开屏身份，不动聊天数据
        from brainn.desktop import paths
        from brainn.desktop.splash import SplashHost

        SplashHost(paths.resource_root(), paths.app_home()).reset_identity()
        return 0

    if "--reset-persona" in sys.argv:
        # 新用户版每次安装都重新随机一套初始人设：
        # 清掉旧种子 + 旧人设覆盖；天气覆盖由首次启动按新种子自动对齐。
        from brainn.desktop import paths

        root = paths.resource_root()
        data_dir = paths.resolve_data_dir(None, False, root)
        for path in (
            root / "config" / "persona_overrides.yaml",
            data_dir / "persona_seed.json",
            root / "data" / "persona_seed.json",
        ):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return 0

    args = build_parser().parse_args(argv)

    from brainn.desktop import paths
    from brainn.desktop.app import DesktopApp, SingleInstance

    root = paths.prepare_runtime_root()
    web_dir = paths.web_dir()
    data_dir = paths.resolve_data_dir(args.data_dir or None, args.portable, root)

    guard = SingleInstance()
    if not args.allow_multi and not guard.acquire():
        SingleInstance.focus_existing()
        print("BrainN 已经在运行，已尝试唤醒原窗口")
        return 0

    app = DesktopApp(
        root=root,
        data_dir=data_dir,
        web_dir=web_dir,
        port=args.port,
        debug=args.debug,
        window_smoke=args.window_smoke,
        bridge_check=args.check_bridge,
        ui_check=args.check_ui,
        pet_check=args.check_pet,
        autostart=args.autostart,
    )
    if args.smoke:
        return app.smoke()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
