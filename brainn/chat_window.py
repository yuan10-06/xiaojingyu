"""单机聊天窗口：内置图形界面，不连接 QQ。

主线程只负责 tkinter；大脑、数据库、调度器都在后台 asyncio 线程里。
两边通过 queue 和 call_soon_threadsafe 通信，界面不会卡住。
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import webbrowser
from pathlib import Path
from typing import Any, Callable

import tkinter as tk

from PIL import Image, ImageTk

from .config import Config
from .timing import ReplyPlan

log = logging.getLogger(__name__)

BG = "#ededed"
HER_BUBBLE = "#ffffff"
ME_BUBBLE = "#95ec69"
BAR_BG = "#f7f7f7"
SYS_FG = "#8c8c8c"
HER_FG = "#1f1f1f"
FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 8)
FONT_TITLE = ("Microsoft YaHei UI", 12, "bold")

from .chat_engine import ChatEngine


class ChatWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.engine: ChatEngine | None = None
        self._q: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...]]] = queue.Queue()
        self._images: list[ImageTk.PhotoImage] = []
        self._typing_on = False
        self.title("小鲸鱼")
        self.geometry("480x720")
        self.minsize(390, 520)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self.after(80, self._drain)

    def bind_engine(self, engine: ChatEngine) -> None:
        self.engine = engine
        self.set_status("启动中")

    # ---------- 界面搭建 ----------
    def _build(self) -> None:
        bar = tk.Frame(self, bg=BAR_BG)
        bar.pack(fill="x", side="top")
        tk.Label(bar, text="小鲸鱼", bg=BAR_BG, fg=HER_FG, font=FONT_TITLE).pack(
            side="left", padx=14, pady=10
        )
        self.status = tk.Label(bar, text="启动中", bg=BAR_BG, fg=SYS_FG, font=FONT_SMALL)
        self.status.pack(side="left", pady=12)

        bottom = tk.Frame(self, bg=BAR_BG)
        bottom.pack(fill="x", side="bottom")
        self.entry = tk.Text(
            bottom,
            height=2,
            font=FONT,
            wrap="word",
            relief="flat",
            bd=0,
            padx=8,
            pady=6,
            bg="white",
        )
        self.entry.pack(side="left", fill="both", expand=True, padx=(10, 6), pady=8)
        send = tk.Button(
            bottom,
            text="发送",
            command=self._send,
            font=FONT,
            relief="flat",
            bd=0,
            bg="#07c160",
            fg="white",
            activebackground="#06ad56",
            activeforeground="white",
            padx=16,
            pady=4,
        )
        send.pack(side="right", padx=(0, 10), pady=8)

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        scroll = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width)
        )
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

        self.typing = tk.Label(self.inner, text="小鲸鱼正在输入…", bg=BG, fg=SYS_FG, font=FONT_SMALL)
        self.entry.bind("<Return>", self._on_return)
        self.entry.bind("<Shift-Return>", lambda _e: None)
        self.after(300, self.entry.focus_set)

    # ---------- 线程安全更新 ----------
    def post(self, fn: Callable[..., Any], *args: Any) -> None:
        self._q.put((fn, args))

    def _drain(self) -> None:
        while True:
            try:
                fn, args = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception:  # noqa: BLE001
                log.exception("界面更新失败")
        self.after(60, self._drain)

    # ---------- 消息展示 ----------
    def show_text(self, who: str, text: str) -> None:
        if not text:
            return
        row = tk.Frame(self.inner, bg=BG)
        row.pack(fill="x", pady=3)
        bubble = tk.Label(
            row,
            text=text,
            bg=HER_BUBBLE if who == "her" else ME_BUBBLE,
            fg=HER_FG,
            font=FONT,
            justify="left",
            wraplength=360,
            padx=11,
            pady=7,
        )
        bubble.pack(side="left" if who == "her" else "right", padx=10)
        self._scroll_to_end()

    def show_sticker(self, path: Any) -> None:
        try:
            image = Image.open(path)
            image.thumbnail((200, 200))
            photo = ImageTk.PhotoImage(image)
        except Exception:  # noqa: BLE001
            log.exception("表情包显示失败：%s", path)
            self.show_text("her", "[表情包]")
            return
        self._images.append(photo)
        row = tk.Frame(self.inner, bg=BG)
        row.pack(fill="x", pady=3)
        tk.Label(row, image=photo, bg=BG).pack(side="left", padx=10)
        self._scroll_to_end()

    def show_link(self, payload: dict[str, Any]) -> None:
        url = str(payload.get("url") or "")
        title = str(payload.get("title") or url)
        if not url:
            return
        row = tk.Frame(self.inner, bg=BG)
        row.pack(fill="x", pady=3)
        label = tk.Label(
            row,
            text=f"链接：{title[:60]}",
            bg=HER_BUBBLE,
            fg="#1a5fb4",
            font=FONT_SMALL,
            wraplength=340,
            justify="left",
            padx=10,
            pady=7,
            cursor="hand2",
        )
        label.pack(side="left", padx=10)
        label.bind("<Button-1>", lambda _e: webbrowser.open(url))
        self._scroll_to_end()

    def show_system(self, text: str) -> None:
        tk.Label(self.inner, text=text, bg=BG, fg=SYS_FG, font=FONT_SMALL, wraplength=400).pack(
            pady=6
        )
        self._scroll_to_end()

    def show_history(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            content = str(row.get("content") or "").strip()
            if not content:
                continue
            self.show_text("me" if row.get("role") == "user" else "her", content)

    # ---------- 状态与输入 ----------
    def set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def set_typing(self, on: bool) -> None:
        if on and not self._typing_on:
            self.typing.pack(pady=4)
            self._typing_on = True
            self._scroll_to_end()
        elif not on and self._typing_on:
            self.typing.pack_forget()
            self._typing_on = False

    def _send(self) -> None:
        text = self.entry.get("1.0", "end").strip()
        if not text:
            return
        self.entry.delete("1.0", "end")
        self.show_text("me", text)
        if self.engine is not None:
            self.engine.user_send(text)

    def _on_return(self, _event: tk.Event) -> str:
        self._send()
        return "break"

    def _on_wheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _scroll_to_end(self) -> None:
        self.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(1.0)

    def close(self) -> None:
        if self.engine is not None:
            try:
                self.engine.shutdown()
            except Exception:  # noqa: BLE001
                log.exception("关闭引擎失败")
        self.destroy()
