"""单机聊天版：图形窗口，不连接 QQ，只需 DeepSeek API Key。"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from tkinter import messagebox

from brainn.chat_window import ChatEngine, ChatWindow
from brainn.config import load_config


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_dir / "brainn.log", encoding="utf-8")],
    )


def main() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass

    config = load_config()
    setup_logging(config.log_dir)

    env_file = config.root / ".env"
    if not env_file.exists():
        template = config.root / ".env.example"
        if template.exists():
            env_file.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        messagebox.showinfo(
            "首次运行",
            "已生成 .env。\n\n请用记事本打开它，填好 DEEPSEEK_API_KEY，再重新打开本程序。",
        )
        return
    if not config.deepseek_key:
        messagebox.showinfo("缺少 API Key", "请在 .env 里填写 DEEPSEEK_API_KEY，然后重新打开。")
        return

    window = ChatWindow()
    engine = ChatEngine(config, window)
    window.bind_engine(engine)
    if not engine.start():
        messagebox.showerror("启动失败", "初始化没有完成，详情见 logs/brainn.log。")
        window.destroy()
        return

    if "--smoke" in sys.argv:

        def _smoke_send() -> None:
            window.show_text("me", "在吗")
            engine.user_send("在吗")

        window.after(3000, _smoke_send)
        window.after(30000, window.close)

    window.mainloop()


if __name__ == "__main__":
    main()
