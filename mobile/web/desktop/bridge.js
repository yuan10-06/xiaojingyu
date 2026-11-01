/* 电脑版桥接（P1）
 * 把网页里的 window.Android 映射到 pywebview 的 Python API。
 * 手机端不加载 pywebview，本文件不会覆盖原生 Android 桥接。
 */
(function () {
  'use strict';

  var api = null;
  var installed = false;
  var fullscreen = false;

  function call(name, args, fallback) {
    if (api && typeof api[name] === 'function') {
      try {
        return api[name].apply(api, args || []);
      } catch (e) {}
    }
    return fallback;
  }

  function setFullscreenState(on) {
    fullscreen = !!on;
    refreshMaxIcon();
  }

  function refreshFullscreen() {
    var p = call('window_is_fullscreen', [], false);
    if (p && typeof p.then === 'function') {
      p.then(setFullscreenState).catch(function () {});
    } else {
      setFullscreenState(!!p);
    }
  }

  function pushFiles(files) {
    if (!files || !files.length) return;
    var input = document.getElementById('chatFileInput');
    if (!input) return;
    try {
      var dt = new DataTransfer();
      for (var i = 0; i < files.length; i++) dt.items.add(files[i]);
      input.files = dt.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    } catch (e) {}
  }

  var CHROME_CSS = [
    'html.desktop{--app-chrome-h:38px}',
    'html.desktop body{padding-top:var(--app-chrome-h)}',
    'html.desktop .sheet,html.desktop .memSheet,html.desktop .setup,',
    'html.desktop .restartOverlay{top:var(--app-chrome-h)}',
    'html.desktop .topbar{top:var(--app-chrome-h)}',
    'html.desktop #callSelf{top:calc(var(--app-chrome-h) + 58px)}',
    '#appChrome{position:fixed;top:0;left:0;right:0;height:var(--app-chrome-h);display:flex;',
    'align-items:center;gap:9px;padding:0 0 0 12px;background:#061426;color:#e8f2ff;',
    'z-index:2147482998;border-bottom:1px solid #17304a;font-family:-apple-system,',
    '"Microsoft YaHei",sans-serif;user-select:none;overflow:hidden}',
    '#appChrome .acIcon{width:22px;height:22px;border-radius:6px;object-fit:cover;',
    'box-shadow:0 0 0 1px rgba(255,255,255,.14)}',
    '#appChrome .acTitle{font-size:13px;font-weight:600;letter-spacing:.03em;color:#f2f7ff}',
    '#appChrome .acSub{font-size:9.5px;color:#6f8ba8;letter-spacing:.14em;white-space:nowrap}',
    '#appChrome .acSpacer{flex:1}',
    '#appChrome .acBtn{height:30px;border:0;background:transparent;color:#9fb6cc;border-radius:7px;',
    'display:inline-flex;align-items:center;justify-content:center;gap:6px;',
    'font:12px/1 inherit;font-family:inherit;cursor:default}',
    '#appChrome .acBtn:hover{background:#12283d;color:#fff}',
    '#appChrome .acSettings{padding:0 10px}',
    '#appChrome .acSettings svg{width:15px;height:15px}',
    '#appChrome .acWin{width:42px;height:38px;border-radius:0}',
    '#appChrome .acWin:hover{background:#17304a}',
    '#appChrome .acClose:hover{background:#d33a3f;color:#fff}',
    '#appChrome .acWin svg{width:12px;height:12px}',
    'html.dsu-lock #appChrome{display:none}'
  ].join('');

  function setMaxIcon(maxed) {
    var btn = document.getElementById('acMax');
    if (!btn) return;
    var ico = btn.querySelector('.acMaxIcon');
    if (!ico) return;
    ico.innerHTML = maxed
      ? '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.2">'
        + '<rect x="3.2" y="1.8" width="7" height="7"/><path d="M1.8 4v6.2h6.2"/></svg>'
      : '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.2">'
        + '<rect x="1.8" y="1.8" width="8.4" height="8.4"/></svg>';
    btn.title = maxed ? '还原' : '最大化';
  }

  function refreshMaxIcon() {
    var p = call('window_is_maximized', [], false);
    if (p && typeof p.then === 'function') {
      p.then(setMaxIcon).catch(function () {});
    } else {
      setMaxIcon(!!p);
    }
  }

  function mountChrome() {
    if (!document.body || document.getElementById('appChrome')) return;
    var style = document.createElement('style');
    style.id = 'appChromeCss';
    style.textContent = CHROME_CSS;
    document.head.appendChild(style);
    var bar = document.createElement('div');
    bar.id = 'appChrome';
    bar.className = 'pywebview-drag-region';
    bar.innerHTML =
      '<img class="acIcon" src="/app_icon.png" alt="" onerror="this.style.display=\'none\'">'
      + '<span class="acTitle">小鲸鱼</span>'
      + '<span class="acSub">BRAIN · TRUTH</span>'
      + '<span class="acSpacer"></span>'
      + '<button class="acBtn acSettings" id="acSettings" type="button" title="设置">'
      + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
      + '<circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1'
      + 'a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6'
      + ' 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9'
      + ' 1.7 1.7 0 0 0-1.6-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1'
      + ' 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3'
      + 'H9a1.7 1.7 0 0 0 1-1.6V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.6'
      + ' 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9'
      + 'V9a1.7 1.7 0 0 0 1.6 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.6 1z"/></svg>'
      + '<span>设置</span></button>'
      + '<button class="acBtn acWin" id="acMin" type="button" title="最小化">'
      + '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.2">'
      + '<path d="M2 6h8"/></svg></button>'
      + '<button class="acBtn acWin" id="acMax" type="button" title="最大化">'
      + '<span class="acMaxIcon"></span></button>'
      + '<button class="acBtn acWin acClose" id="acClose" type="button" title="关闭">'
      + '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.3">'
      + '<path d="M2 2l8 8M10 2l-8 8"/></svg></button>';
    document.body.insertBefore(bar, document.body.firstChild);

    var stop = function (e) { e.stopPropagation(); };
    ['acSettings', 'acMin', 'acMax', 'acClose'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('mousedown', stop);
    });
    var settings = document.getElementById('acSettings');
    if (settings) {
      settings.onclick = function () {
        try { if (window.__closeMemory) window.__closeMemory(); } catch (e) {}
        try { if (window.__closeHomePicker) window.__closeHomePicker(); } catch (e) {}
        if (typeof window.switchTab === 'function') {
          window.switchTab('settings');
        } else {
          location.href = '/index.html?settings=1';
        }
      };
    }
    var min = document.getElementById('acMin');
    if (min) min.onclick = function () { call('minimize_window', [], false); };
    var max = document.getElementById('acMax');
    if (max) {
      max.onclick = function () {
        call('toggle_maximize', [], false);
        setTimeout(refreshMaxIcon, 350);
      };
    }
    var close = document.getElementById('acClose');
    if (close) close.onclick = function () { call('close_window', [], false); };

    /* 只允许拖顶部栏，不启用 pywebview 的全窗口 easy_drag，避免设置页也被拖走 */
    var dragging = null;
    bar.addEventListener('mousedown', function (e) {
      if (e.button !== 0) return;
      if (fullscreen) return; // 全屏时窗口不允许被拖出屏幕
      if (e.target && e.target.closest && e.target.closest('button')) return;
      dragging = { x: e.clientX, y: e.clientY };
      function onMove(ev) {
        if (!dragging) return;
        try {
          if (window.pywebview && window.pywebview._jsApiCallback) {
            window.pywebview._jsApiCallback(
              'pywebviewMoveWindow',
              [ev.screenX - dragging.x, ev.screenY - dragging.y],
              'move'
            );
          }
        } catch (err) {}
      }
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', function () {
        window.removeEventListener('mousemove', onMove);
        dragging = null;
      }, { once: true });
    });
    bar.addEventListener('dblclick', function (e) {
      if (e.target && e.target.closest && e.target.closest('button')) return;
      call('toggle_maximize', [], false);
      setTimeout(refreshMaxIcon, 350);
    });
    var resizeTimer = null;
    window.addEventListener('resize', function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(refreshMaxIcon, 280);
    });
    setMaxIcon(false);
    refreshMaxIcon();
  }

  function install() {
    if (installed) return;
    if (!(window.pywebview && window.pywebview.api)) return;
    /* 手机上已有原生桥接时绝不覆盖 */
    if (window.Android && !window.__BRAINN_DESKTOP__) return;

    installed = true;
    api = window.pywebview.api;
    window.__BRAINN_DESKTOP__ = true;
    document.documentElement.classList.add('desktop');
    if (document.body) mountChrome();
    else window.addEventListener('DOMContentLoaded', mountChrome, { once: true });
    window.Android = {
      isDesktop: function () { return true; },
      setSystemBarTheme: function (t) {
        return call('set_theme', [String(t || '')], true);
      },
      setWhalePage: function () {},
      setChatFocused: function () {},
      canNotify: function () { return true; },
      notifyStatus: function () { return '{"enabled":true,"channel":3,"permission":true}'; },
      requestNotifyPermission: function () {},
      testNotification: function () {
        return call('test_notification', [], true);
      },
      openNotificationSettings: function () {
        return call('open_notification_settings', [], false);
      },
      hasCamera: function () { return false; },
      hasLocationPermission: function () { return false; },
      hasOverlay: function () { return true; },
      hasUsageAccess: function () { return false; },
      currentApp: function () { return '{"ok":false}'; },
      showFloating: function () {
        return call('show_pet', [], true);
      },
      hideFloating: function () {
        return call('hide_pet', [], true);
      },
      openOverlaySettings: function () {},
      openUrl: function (url) {
        return call('open_url', [String(url || '')], false);
      },
      desktopSettings: function () {
        return call('desktop_settings', [], '{}');
      },
      /* 全量记忆导出：弹系统“选择文件夹”，把 zip 复制到 U 盘/高速磁盘 */
      saveMemoryExport: function (path, name) {
        return call('save_memory_export', [String(path || ''), String(name || '')], false);
      },
      /* 全量记忆存档目录：弹系统文件夹选择框 */
      chooseDirectory: function (directory) {
        return call('choose_directory', [String(directory || '')], '');
      },
      setAutostart: function (on) {
        return call('set_autostart', [!!on], false);
      },
      setCloseToTray: function (on) {
        return call('set_close_to_tray', [!!on], false);
      },
      minimizeWindow: function () {
        return call('minimize_window', [], false);
      },
      toggleMaximize: function () {
        return call('toggle_maximize', [], false);
      },
      closeWindow: function () {
        return call('close_window', [], false);
      },
      windowMaximized: function () {
        return call('window_is_maximized', [], false);
      }
    };

    /* 窗口焦点：不在前台时才弹 Windows 通知 */
    window.addEventListener('focus', function () {
      call('set_window_active', [true], null);
    });
    window.addEventListener('blur', function () {
      call('set_window_active', [false], null);
    });

    /* F11：交给主窗做全屏切换 */
    window.addEventListener('keydown', function (e) {
      if (e.key === 'F11' || e.keyCode === 122) {
        e.preventDefault();
        var p = call('toggle_fullscreen', [], false);
        if (p && typeof p.then === 'function') p.then(setFullscreenState).catch(function () {});
        else refreshFullscreen();
      }
    }, true);
    refreshFullscreen();
    window.addEventListener('resize', function () { setTimeout(refreshFullscreen, 120); });

    /* 页面初始化时可能已经按“无 Android”渲染过权限状态，补刷一次 */
    setTimeout(function () {
      try { window.refreshPermissions && window.refreshPermissions(); } catch (e) {}
      try { window.initDesktopPanel && window.initDesktopPanel(); } catch (e) {}
      /* 电脑版文案：去掉“手机 / 安卓”的表述 */
      try {
        var apiNote = document.getElementById('apiTestInfo');
        if (apiNote) {
          apiNote.textContent = 'Key 只保存在这台电脑的本地数据目录；修改后大脑会自动重启。'
            + '中转站、OpenRouter、OpenAI、Gemini 等只要兼容 OpenAI 的 /chat/completions 就能用。';
        }
        var setupText = document.querySelector('#setup > p');
        if (setupText) {
          setupText.textContent = '先填一个模型 API Key，之后她就在这台电脑上自己跑。'
            + 'Key 只保存在本机；其他服务商和中转站可以进「模型 API」里改。';
        }
        var setupHint = document.getElementById('setupHint');
        if (setupHint) setupHint.textContent = '启动后请允许 Windows 通知，这样才能在她说话时提醒你。';
        var wh = document.getElementById('whalePhoneHint');
        if (wh) wh.textContent = '电脑版支持摄像头视频通话，请允许浏览器使用摄像头。';
        var notifNote = document.getElementById('notifNote');
        if (notifNote) {
          notifNote.textContent = '不在聊天页（动态、设置或后台）时会弹 Windows 通知；没弹可以先“发送测试通知”。';
        }
      } catch (e) {}
    }, 0);
  }

  /* 拖拽文件进来时交给聊天输入，避免 WebView 直接打开文件 */
  window.addEventListener('dragover', function (e) {
    if (window.__BRAINN_DESKTOP__) e.preventDefault();
  });
  window.addEventListener('drop', function (e) {
    if (!window.__BRAINN_DESKTOP__) return;
    e.preventDefault();
    var files = e.dataTransfer && e.dataTransfer.files;
    if (files && files.length) pushFiles(files);
  });

  /* 粘贴图片发给聊天 */
  window.addEventListener('paste', function (e) {
    if (!window.__BRAINN_DESKTOP__) return;
    var items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    var files = [];
    for (var i = 0; i < items.length; i++) {
      if (items[i].kind === 'file') {
        var file = items[i].getAsFile();
        if (file) files.push(file);
      }
    }
    if (files.length) {
      e.preventDefault();
      pushFiles(files);
    }
  });

  /* pywebview 6 把事件派发在 window 上，不是 document */
  window.addEventListener('pywebviewready', install);
  document.addEventListener('pywebviewready', install);
  install();
})();
