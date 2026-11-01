"""原生 dsh-startup 启动画面（Host 半侧）。

直接托管插件原版 splash.css / splash.js / asset-data.js，并照抄插件的
<head>/<body> 注入片段；配置存本地 JSON，字段与插件 DEFAULTS 一致。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROUTE_BASE = "/dsh-startup"
PLUGIN_VERSION = "1.5.2"

DEFAULTS = {
    "enabled": True,
    "mode": "session",
    "theme": "light",
    "speed": 1,
    "autoPlay": "off",
    "requireInteraction": True,
    "allowSkip": True,
    "sound": True,
    "soundVolume": 0.55,
    "voice": True,
    "voiceLang": "zh",
    "voiceName": "zhixing-cn",
    "voiceRate": 0.9,
    "voicePitch": 0.92,
    "voiceVolume": 0.85,
    "voiceCue": True,
    "sfx": "audio",
    "voiceSource": "asset",
    "voiceLead": 240,
    "mascot": 0,
    "emblem": 0,
    "eventWindow": False,
    "identity": "主人",
    "identityId": "0001",
    "accessLevel": "最高权限",
    "identityPassword": "",
    "brand1": "小鲸鱼",
    "brand2": "BRAIN · TRUTH",
    "brand3a": "BRAIN",
    "brand3b": "TRUTH",
    "orgZh": "小鲸鱼",
    "orgEn": "BRAIN TRUTH",
    "orgSub": "她正在醒来…",
    "welcomeBox": "BRAIN TRUTH",
    "footer": "Powered By 小鲸鱼",
    "accent": "#4d6bfe",
    "glitchA": "#ff3b30",
    "glitchB": "#2971b8",
}

BOOL_KEYS = (
    "enabled",
    "requireInteraction",
    "allowSkip",
    "sound",
    "voice",
    "voiceCue",
    "eventWindow",
)
ENUMS = {
    "mode": ("session", "daily"),
    "theme": ("light", "dark"),
}
TEXT_KEYS = (
    "identity",
    "identityId",
    "accessLevel",
    "brand1",
    "brand2",
    "brand3a",
    "brand3b",
    "orgZh",
    "orgEn",
    "orgSub",
    "welcomeBox",
    "footer",
    "voiceName",
)
COLOR_KEYS = ("accent", "glitchA", "glitchB")
NUMBERS = {
    "speed": (0.35, 3),
    "soundVolume": (0, 1),
    "voiceRate": (0.5, 2),
    "voicePitch": (0.4, 2),
    "voiceVolume": (0, 1),
    "voiceLead": (0, 1200),
    "mascot": (-1, 4),
    "emblem": (0, 3),
}

CRITICAL_CSS = (
    "html.dsu-lock,html.dsu-lock body{overflow:hidden!important}"
    "#dsh-startup-root.dsu-boot{position:fixed;inset:0;z-index:2147483000;background:#000}"
    "html.dsu-lock body{--dsw-specific-sidebar-fill:transparent!important;"
    "--dsw-alias-label-primary:#fff!important}"
    "html[data-windows-titlebar].dsu-lock body{--dsw-specific-sidebar-fill:transparent!important;"
    "--dsw-alias-label-primary:#fff!important}"
    "html.dsu-lock{background:#000!important;color-scheme:dark}"
    "html.dsu-lock body{background:#000!important}"
    "html.dsu-lock #dsh-startup-veil{display:block}"
    "#dsh-startup-veil{display:none;position:fixed;inset:0;z-index:2147482999;background:#000}"
)

BOOTSTRAP_JS = """(function(){try{
var d=document.documentElement;
d.classList.add('dsu-lock');
var c=window.__DSH_STARTUP__||{};
var root=document.getElementById('dsh-startup-root');
var off=!c.enabled;
if(!off&&c.mode==='session'&&sessionStorage.getItem('dsh-startup-screen:shown')==='1')off=true;
if(!off&&c.mode==='daily'&&localStorage.getItem('dsh-startup-screen:day')===new Date().toISOString().slice(0,10))off=true;
if(off){window.__DSH_STARTUP_SKIP__=true;d.classList.remove('dsu-lock');if(root&&root.parentNode)root.parentNode.removeChild(root);}
else{setTimeout(function(){try{var r=document.getElementById('dsh-startup-root');if(r&&r.className&&r.className.indexOf('dsu-boot')!==-1){if(r.parentNode)r.parentNode.removeChild(r);var v=document.getElementById('dsh-startup-veil');if(v&&v.parentNode)v.parentNode.removeChild(v);document.documentElement.classList.remove('dsu-lock');if(document.body)document.body.style.overflow='';window.__DSH_STARTUP_FAILED__=true;}}catch(e){}},9000);}
}catch(e){} })()"""


def _hex(value: str) -> str:
    return value if re.match(r"^#[0-9a-fA-F]{3,8}$", value) else ""


class SplashHost:
    DEFAULTS = DEFAULTS

    def __init__(self, resource_root: Path, app_home: Path) -> None:
        self.resource_root = Path(resource_root)
        self.app_home = Path(app_home)
        self.config_path = self.app_home / "dsh-startup.json"
        # 每个进程只注入一次：从其它页面返回首页时不再重播，避免黑屏
        self._played = False

    def asset_dir(self) -> Path:
        candidates = [
            self.resource_root / "desktop_runtime" / "dsh-startup",
            Path(os.getenv("LOCALAPPDATA", "")) / "BrainN" / "dsh-startup",
        ]
        for path in candidates:
            if (path / "splash.js").exists():
                return path
        return candidates[0]

    def available(self) -> bool:
        return (self.asset_dir() / "splash.js").exists()

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------
    def _sanitize(self, raw: dict) -> dict:
        out = dict(DEFAULTS)
        if not isinstance(raw, dict):
            return out
        for key, default in DEFAULTS.items():
            if key not in raw:
                continue
            value = raw[key]
            if key in BOOL_KEYS:
                out[key] = bool(value) if isinstance(value, bool) else default
            elif key in ENUMS:
                out[key] = value if value in ENUMS[key] else default
            elif key in NUMBERS:
                low, high = NUMBERS[key]
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    out[key] = min(high, max(low, float(value)))
                else:
                    out[key] = default
            elif key in COLOR_KEYS:
                text = _hex(str(value))
                out[key] = text or default
            elif key in TEXT_KEYS:
                text = str(value).strip()[:64]
                # voiceName 的空字符串 = 自动（优先神经网络女声），不能当成“未填”回退默认
                out[key] = text if key == "voiceName" else (text or default)
            elif isinstance(default, str):
                out[key] = str(value)[:64]
            elif isinstance(default, (int, float)):
                out[key] = value if isinstance(value, (int, float)) else default
        if not str(out.get("identity") or "").strip():
            out["identity"] = DEFAULTS["identity"]
        if not str(out.get("identityId") or "").strip():
            out["identityId"] = (
                re.sub(r"[^A-Z0-9]", "", str(out["identity"]).upper())[:12] or "OPERATOR"
            )
        return out

    def read_config(self) -> dict:
        try:
            stored = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            stored = {}
        return self._sanitize(stored)

    def save_config(self, patch: dict) -> dict:
        current = self.read_config()
        if isinstance(patch, dict):
            current.update({k: v for k, v in patch.items() if k in DEFAULTS})
        config = self._sanitize(current)
        try:
            self.config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass
        return config

    def reset_config(self) -> dict:
        return self.save_config(dict(DEFAULTS))

    def _theme_script(self, skip: bool) -> str:
        """桌面版页面必须自己应用模块主题，手机版旧脚本已被屏蔽。"""
        theme = str(self.read_config().get("theme") or "light")
        parts = ["window.__DSH_NATIVE_BOOT__=true;"]
        if skip:
            parts.append("window.__DSH_STARTUP_SKIP__=true;")
        parts.append(
            "window.__applyHomeTheme=function(t){try{"
            "document.documentElement.classList.toggle('home-dark',String(t)==='dark')"
            "}catch(e){}};"
        )
        parts.append(f"window.__applyHomeTheme({json.dumps(theme)});")
        return "<script>" + "".join(parts) + "</script>"

    # ------------------------------------------------------------------
    # 注入
    # ------------------------------------------------------------------
    def inject(self, html: str) -> str:
        if not html or (ROUTE_BASE + "/splash.js") in html:
            return html
        # 手机版在 index.html 里放了一个静态 root，桌面版由这里完全接管，
        # 先清掉它，避免后续回到首页时空 root 被旧样式铺满黑幕。
        html = re.sub(
            r'<div\s+id="dsh-startup-root"[^>]*>\s*</div>',
            "",
            html,
            count=1,
        )
        if self._played or not self.available():
            # 同进程后续页面 / 运行时素材缺失：只告诉页面「桌面版由原生接管」，
            # 抑制手机版旧动画，不再重播启动画面。
            mark = self._theme_script(True)
            if "</head>" in html:
                return html.replace("</head>", mark + "</head>", 1)
            return mark + html
        self._played = True
        config = json.dumps(self.read_config(), ensure_ascii=False).replace(
            "</", "<\\/"
        )
        head = (
            '<style id="dsh-startup-critical">' + CRITICAL_CSS + "</style>"
            + self._theme_script(False)
            + "<script>try{document.documentElement.classList.add('dsu-lock')}"
            "catch(e){}</script>"
            '<link rel="stylesheet" href="' + ROUTE_BASE + '/splash.css">'
        )
        veil = "" if 'id="dsh-startup-veil"' in html else (
            '<div id="dsh-startup-veil" aria-hidden="true"></div>'
        )
        root = "" if 'id="dsh-startup-root"' in html else (
            '<div id="dsh-startup-root" class="dsu-root dsu-boot"></div>'
        )
        body = (
            veil + root + "<script>window.__DSH_STARTUP_BOOT__=\"index\";"
            f"window.__DSH_STARTUP_VERSION__={json.dumps(PLUGIN_VERSION)};"
            f"window.__DSH_STARTUP_CONFIG_URL__={json.dumps(ROUTE_BASE + '/config')};"
            f"window.__DSH_STARTUP__={config};" + BOOTSTRAP_JS + "</script>"
            '<script defer src="' + ROUTE_BASE + '/asset-data.js"></script>'
            '<script defer src="' + ROUTE_BASE + '/splash.js"></script>'
        )
        out = html
        if "</head>" in out:
            out = out.replace("</head>", head + "</head>", 1)
        else:
            out = head + out
        if "<body>" in out:
            out = out.replace("<body>", "<body>" + body, 1)
        elif "</body>" in out:
            out = out.replace("</body>", body + "</body>", 1)
        else:
            out = out + body
        return out
