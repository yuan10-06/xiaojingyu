package com.ganfanyu.app;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.drawable.ColorDrawable;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.provider.Settings;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.util.Log;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.Locale;

public class MainActivity extends Activity {
    private static final int REQ_FILE = 1001;
    private static final int REQ_CAMERA = 1002;
    private static final int REQ_EXPORT = 1003;
    private static final int REQ_CAMERA_PERM = 11;
    private static final int REQ_LOCATION_PERM = 12;
    private static final int REQ_VOICE_PERM = 13;
    private static final int REQ_CALENDAR_PERM = 14;
    private static final int REQ_WORLD_CAMERA_PERM = 15;
    private SpeechRecognizer voiceRecognizer;
    private boolean voiceListening;
    private boolean worldListenActive;
    private boolean pendingWorldListening;
    private Runnable worldListenRestart;
    private final Handler locationHandler = new Handler(Looper.getMainLooper());
    private final Handler voiceHandler = new Handler(Looper.getMainLooper());
    private boolean locationDelivered;
    private WebView web;
    private FrameLayout rootView;
    private WorldCallController worldCall;
    private boolean pendingWorldCall;
    private String pendingWorldSession = "";
    private ValueCallback<Uri[]> pendingFileCallback;
    private String pendingExportPath;
    private String pendingExportName;
    private boolean pendingCamera;
    private boolean pendingCameraTool;
    private boolean wantsChat;
    // 原生 TTS：WebView 的 speechSynthesis 在国内 ROM 上常常拿不到语音（默认引擎为 null），
    // 这里直接用系统 TextToSpeech 兜底。
    private TextToSpeech tts;
    private volatile boolean ttsReady;
    private String pendingSpeak;
    // 云端 TTS（MiniMax speech-02-hd）：配置由小鲸鱼页 JS 通过 setTtsCloudConfig 推过来；
    // 合成结果缓存到 files/tts_cache，同一句不重复请求、不重复扣额度。
    private volatile String mmKey = "";
    private volatile String mmGroup = "";
    private volatile String mmVoice = "whale_jelpeita_01";
    private volatile int mmPitch = 0;
    private MediaPlayer mmPlayer;
    private volatile String mmSpeaking;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        installCrashLogger();
        // 删除原生静态开屏后，用深海底色接住网页加载前的空窗，避免白屏闪一下
        getWindow().setBackgroundDrawable(new ColorDrawable(0xff061426));
        setupFullscreen();
        wantsChat = "chat".equals(getIntent().getStringExtra("open"));
        WebView.setWebContentsDebuggingEnabled(true);
        web = new WebView(this);
        FrameLayout root = new FrameLayout(this);
        rootView = root;
        // 深海底色接住网页加载前的空窗；开机动画由网页里的 DSH 序列负责
        root.setBackgroundColor(0xff061426);
        root.addView(web, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        // 全面屏：把系统栏高度交给网页，网页自己决定内容避让
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            int top = 0, bottom = 0, ime = 0;
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(
                        WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                top = bars.top;
                bottom = bars.bottom;
                ime = insets.getInsets(WindowInsets.Type.ime()).bottom;
            } else {
                top = insets.getSystemWindowInsetTop();
                bottom = insets.getSystemWindowInsetBottom();
            }
            postInsets(top, bottom, ime);
            return insets;
        });
        setContentView(root);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setTextZoom(100);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(true);
        // 开机动画的语音/音效要能在没有点击时解码播放
        s.setMediaPlaybackRequiresUserGesture(false);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri u = request.getUrl();
                if ("127.0.0.1".equals(u.getHost())) {
                    return false;
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, u));
                } catch (Exception ignored) {
                }
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                FloatingOverlay.setWhalePage(MainActivity.this, isWhaleUrl(url));
                if (insetTopPx > 0 || insetBottomPx > 0 || insetImePx > 0) {
                    postInsets(insetTopPx, insetBottomPx, insetImePx);
                }
                if (wantsChat) {
                    openChatInWeb();
                }
            }

            @Override
            public void doUpdateVisitedHistory(WebView view, String url, boolean isReload) {
                FloatingOverlay.setWhalePage(MainActivity.this, isWhaleUrl(url));
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                             FileChooserParams params) {
                if (pendingFileCallback != null) {
                    pendingFileCallback.onReceiveValue(null);
                }
                pendingFileCallback = callback;
                try {
                    startActivityForResult(params.createIntent(), REQ_FILE);
                    return true;
                } catch (Exception e) {
                    pendingFileCallback = null;
                    return false;
                }
            }
        });

        // 记忆导出等附件下载：交给系统下载器，落到“下载”目录
        web.setDownloadListener((url, userAgent, contentDisposition, mimetype, contentLength) -> {
            try {
                String name = URLUtil.guessFileName(url, contentDisposition, mimetype);
                DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
                req.setMimeType(mimetype);
                req.addRequestHeader("User-Agent", userAgent);
                req.setNotificationVisibility(
                        DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
                DownloadManager dm = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
                if (dm != null) {
                    dm.enqueue(req);
                    Toast.makeText(this, "已下载到「下载」目录：" + name, Toast.LENGTH_LONG).show();
                }
            } catch (Exception e) {
                Toast.makeText(this, "下载失败，请重试", Toast.LENGTH_SHORT).show();
            }
        });

        web.addJavascriptInterface(new AndroidBridge(), "Android");
        worldCall = new WorldCallController(this, rootView, web);
        worldCall.setTopInset(insetTopPx);

        initTts();
        startBrainService();
        requestNotificationPermission();
        maybeAskBattery();
        loadWhenReady();
    }

    private void initTts() {
        try {
            tts = new TextToSpeech(this, status -> {
                if (status != TextToSpeech.SUCCESS || tts == null) {
                    return;
                }
                try {
                    int r = tts.setLanguage(Locale.CHINA);
                    ttsReady = r != TextToSpeech.LANG_MISSING_DATA
                            && r != TextToSpeech.LANG_NOT_SUPPORTED;
                    if (ttsReady) {
                        tts.setSpeechRate(1.05f);
                        tts.setPitch(1.15f);
                        if (pendingSpeak != null) {
                            tts.speak(pendingSpeak, TextToSpeech.QUEUE_FLUSH, null, "whale");
                            pendingSpeak = null;
                        }
                    }
                } catch (Throwable ignored) {
                }
            });
        } catch (Throwable ignored) {
        }
    }

    private void installCrashLogger() {
        // 先抓住原来的处理器，不能在处理器内部再取默认处理器，否则会递归到自己。
        final Thread.UncaughtExceptionHandler previous =
                Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((thread, throwable) -> {
            try {
                java.io.File dir = getExternalFilesDir(null);
                if (dir != null) {
                    dir.mkdirs();
                    java.io.FileWriter writer = new java.io.FileWriter(
                            new java.io.File(dir, "crash.log"), true);
                    writer.write(new java.util.Date().toString() + "\n");
                    java.io.StringWriter buffer = new java.io.StringWriter();
                    throwable.printStackTrace(new java.io.PrintWriter(buffer));
                    writer.write(buffer.toString());
                    writer.write("\n\n");
                    writer.close();
                }
            } catch (Throwable ignored) {
            }
            if (previous != null) {
                previous.uncaughtException(thread, throwable);
            }
        });
    }

    private void setupFullscreen() {
        // 全面屏（edge-to-edge）：内容铺到刘海和手势条下面，安全区由网页按 --safe-top/--safe-bottom 自己让开。
        Window window = getWindow();
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        if (Build.VERSION.SDK_INT >= 30) {
            window.setDecorFitsSystemWindows(false);
        } else {
            window.getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        }
        if (Build.VERSION.SDK_INT >= 29) {
            window.setNavigationBarContrastEnforced(false);
        }
        applySystemBarTheme("whale");
    }

    private void applySystemBarTheme(String theme) {
        boolean light = "white".equals(theme) || "sakura".equals(theme) || "wuling".equals(theme);
        Window window = getWindow();
        // 系统栏透明，颜色交给网页的头部/壁纸透上来
        window.setStatusBarColor(Color.TRANSPARENT);
        window.setNavigationBarColor(Color.TRANSPARENT);
        int flags = window.getDecorView().getSystemUiVisibility();
        flags |= View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION;
        if (Build.VERSION.SDK_INT >= 26) {
            flags = light
                    ? (flags | View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR)
                    : (flags & ~(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR));
        } else {
            flags = light
                    ? (flags | View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR)
                    : (flags & ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        }
        window.getDecorView().setSystemUiVisibility(flags);
    }

    /** 系统栏高度以 CSS px 推给网页（WebView 1dp = 1px）。 */
    private int insetTopPx;
    private int insetBottomPx;
    private int insetImePx;

    private void postInsets(int topPx, int bottomPx, int imePx) {
        insetTopPx = topPx;
        insetBottomPx = bottomPx;
        insetImePx = imePx;
        if (worldCall != null) {
            worldCall.setTopInset(topPx);
        }
        float density = getResources().getDisplayMetrics().density <= 0
                ? 1f : getResources().getDisplayMetrics().density;
        int top = Math.round(topPx / density);
        int bottom = Math.round(bottomPx / density);
        int ime = Math.round(imePx / density);
        if (top < 0) top = 0;
        if (bottom < 0) bottom = 0;
        if (ime < 0) ime = 0;
        final int t = top, b = bottom, k = ime;
        runOnUiThread(() -> {
            if (web == null) return;
            try {
                web.evaluateJavascript("(function(){var r=document.documentElement;if(!r)return;"
                        + "r.style.setProperty('--safe-top','" + t + "px');"
                        + "r.style.setProperty('--safe-bottom','" + b + "px');"
                        + "r.style.setProperty('--kb','" + k + "px');"
                        + "r.classList.toggle('kb-open'," + (k > 0) + ");"
                        + "if(window.__applyInsets)window.__applyInsets(" + t + "," + b + "," + k + ");})()", null);
            } catch (Throwable ignored) {
            }
        });
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void startBrainService() {
        Intent i = new Intent(this, BrainService.class);
        try {
            if (Build.VERSION.SDK_INT >= 26) {
                startForegroundService(i);
            } else {
                startService(i);
            }
        } catch (Exception ignored) {
        }
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 10);
        }
    }

    private void maybeAskBattery() {
        SharedPreferences sp = getSharedPreferences("app", MODE_PRIVATE);
        if (sp.getBoolean("battery_asked", false)) {
            return;
        }
        sp.edit().putBoolean("battery_asked", true).apply();
        new AlertDialog.Builder(this)
                .setTitle("保持后台运行")
                .setMessage("安卓会清理后台应用。为了不让她在你锁屏后掉线，下一步请允许“忽略电池优化”。")
                .setPositiveButton("去设置", (d, w) -> {
                    try {
                        Intent i = new Intent(
                                Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                                Uri.parse("package:" + getPackageName()));
                        startActivity(i);
                    } catch (Exception e) {
                        try {
                            startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
                        } catch (Exception ignored) {
                        }
                    }
                })
                .setNegativeButton("以后", null)
                .show();
    }

    private boolean locationPermissionGranted() {
        return Build.VERSION.SDK_INT < 23
                || checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    private boolean fineLocationGranted() {
        return Build.VERSION.SDK_INT < 23
                || checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    private void requestLocationThenFetch() {
        if (Build.VERSION.SDK_INT >= 23 && !locationPermissionGranted()) {
            requestPermissions(new String[]{
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION
            }, REQ_LOCATION_PERM);
            return;
        }
        fetchLocation();
    }

    private void fetchLocation() {
        if (!locationPermissionGranted()) {
            sendLocationError("denied");
            return;
        }
        try {
            final LocationManager manager = (LocationManager) getSystemService(LOCATION_SERVICE);
            if (manager == null) {
                sendLocationError("unavailable");
                return;
            }
            Location best = null;
            for (String provider : new String[]{
                    LocationManager.GPS_PROVIDER,
                    LocationManager.NETWORK_PROVIDER,
                    LocationManager.PASSIVE_PROVIDER
            }) {
                try {
                    Location item = manager.getLastKnownLocation(provider);
                    if (item != null && (best == null || item.getTime() > best.getTime())) {
                        best = item;
                    }
                } catch (Exception ignored) {
                }
            }
            if (best != null && System.currentTimeMillis() - best.getTime() < 30000) {
                sendLocation(best);
                return;
            }
            String provider = null;
            try {
                if (fineLocationGranted() && manager.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
                    provider = LocationManager.GPS_PROVIDER;
                } else if (manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) {
                    provider = LocationManager.NETWORK_PROVIDER;
                }
            } catch (Exception ignored) {
            }
            if (provider == null) {
                if (best != null) {
                    sendLocation(best);
                } else {
                    sendLocationError("unavailable");
                }
                return;
            }
            locationDelivered = false;
            final String chosen = provider;
            final Location fallbackLoc = best;
            final LocationListener listener = new LocationListener() {
                @Override
                public void onLocationChanged(Location location) {
                    if (locationDelivered) {
                        return;
                    }
                    locationDelivered = true;
                    try {
                        manager.removeUpdates(this);
                    } catch (Exception ignored) {
                    }
                    sendLocation(location);
                }

                @Override
                public void onStatusChanged(String provider, int status, Bundle extras) {
                }

                @Override
                public void onProviderEnabled(String provider) {
                }

                @Override
                public void onProviderDisabled(String provider) {
                }
            };
            try {
                manager.requestLocationUpdates(chosen, 0, 0, listener, Looper.getMainLooper());
            } catch (SecurityException e) {
                sendLocationError("denied");
                return;
            }
            locationHandler.postDelayed(() -> {
                if (locationDelivered) {
                    return;
                }
                locationDelivered = true;
                try {
                    manager.removeUpdates(listener);
                } catch (Exception ignored) {
                }
                Location last = fallbackLoc;
                try {
                    Location item = manager.getLastKnownLocation(chosen);
                    if (item != null && (last == null || item.getTime() > last.getTime())) {
                        last = item;
                    }
                } catch (Exception ignored) {
                }
                if (last != null) {
                    sendLocation(last);
                } else {
                    sendLocationError("timeout");
                }
            }, 15000);
        } catch (Exception e) {
            sendLocationError("unavailable");
        }
    }

    private void sendLocation(Location location) {
        try {
            JSONObject out = new JSONObject();
            out.put("ok", true);
            out.put("lat", location.getLatitude());
            out.put("lon", location.getLongitude());
            out.put("accuracy", Math.round(location.getAccuracy()));
            out.put("provider", String.valueOf(location.getProvider()));
            out.put("ts", location.getTime());
            sendLocationJson(out.toString());
        } catch (Exception e) {
            sendLocationError("unavailable");
        }
    }

    private void sendLocationError(String error) {
        try {
            JSONObject out = new JSONObject();
            out.put("ok", false);
            out.put("error", error);
            sendLocationJson(out.toString());
        } catch (Exception ignored) {
        }
    }

    private void sendLocationJson(String json) {
        final WebView target = web;
        if (target == null) {
            return;
        }
        final String js = "window.__onLocation&&window.__onLocation(" + json + ")";
        runOnUiThread(() -> target.evaluateJavascript(js, null));
    }

    private void loadWhenReady() {
        new Thread(() -> {
            boolean ok = false;
            for (int i = 0; i < 80; i++) {
                try {
                    java.net.HttpURLConnection c = (java.net.HttpURLConnection)
                            new java.net.URL("http://127.0.0.1:8765/api/status").openConnection();
                    c.setConnectTimeout(800);
                    c.setReadTimeout(800);
                    if (c.getResponseCode() == 200) {
                        ok = true;
                        break;
                    }
                } catch (Exception ignored) {
                }
                try {
                    Thread.sleep(500);
                } catch (InterruptedException ignored) {
                }
            }
            final boolean ready = ok;
            runOnUiThread(() -> {
                if (ready) {
                    web.loadUrl("http://127.0.0.1:8765/");
                    return;
                }
                String detail = BrainService.lastError;
                if (detail == null || detail.isEmpty()) {
                    detail = "本地服务没有启动（可能是首次解压较慢，退回桌面再进来试试）";
                }
                new AlertDialog.Builder(this)
                        .setTitle("小鲸鱼启动失败")
                        .setMessage(detail + "\n\n日志：Android/data/" + getPackageName()
                                + "/files/logs/brainn.log\n崩溃日志：Android/data/"
                                + getPackageName() + "/files/crash.log")
                        .setPositiveButton("重试", (d, w) -> {
                            startBrainService();
                            loadWhenReady();
                        })
                        .setNegativeButton("关闭", null)
                        .show();
            });
        }, "brainn-wait").start();
    }

    private void openChatInWeb() {
        wantsChat = false;
        if (web != null) {
            web.evaluateJavascript("window.__openChat&&window.__openChat()", null);
        }
    }

    /** 2D 小鲸鱼页：这一页不显示桌面桌宠。 */
    private static boolean isWhaleUrl(String url) {
        return url != null && url.contains("whale.html");
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if ("chat".equals(intent.getStringExtra("open"))) {
            wantsChat = true;
            openChatInWeb();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        AppState.activityVisible = true;
        AppState.context = getApplicationContext();
        AppState.activity = this;
        FloatingOverlay.onAppResume(this);
        if (worldCall != null) {
            worldCall.onActivityResume();
        }
        if (web != null) {
            web.evaluateJavascript("window.__onResume&&window.__onResume()", null);
            web.evaluateJavascript("window.__syncChatFocus&&window.__syncChatFocus()", null);
        }
    }

    @Override
    protected void onPause() {
        AppState.activityVisible = false;
        AppState.chatFocused = false;
        FloatingOverlay.onAppPause(this);
        if (worldCall != null) {
            worldCall.onActivityPause();
        }
        if (worldListenActive) {
            stopWorldListening();
        }
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        FloatingOverlay.onActivityDestroyed();
        stopWorldListening();
        if (worldCall != null) {
            worldCall.destroy();
            worldCall = null;
        }
        AppState.activity = null;
        try {
            if (tts != null) {
                tts.stop();
                tts.shutdown();
            }
        } catch (Throwable ignored) {
        }
        tts = null;
        mmStop();
        super.onDestroy();
    }

    private void requestCameraThenLaunch() {
        requestCameraThenLaunch(false);
    }

    private void requestCameraThenLaunch(boolean forTool) {
        pendingCameraTool = forTool;
        if (Build.VERSION.SDK_INT >= 23
                && checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            pendingCamera = true;
            requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA_PERM);
            return;
        }
        launchCamera();
    }

    private void launchCamera() {
        try {
            Intent intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            startActivityForResult(intent, REQ_CAMERA);
        } catch (Exception e) {
            Toast.makeText(this, "没有找到可用的相机", Toast.LENGTH_SHORT).show();
        }
    }

    private void uploadPhoto(byte[] bytes) {
        new Thread(() -> {
            int code = 0;
            try {
                HttpURLConnection c = (HttpURLConnection)
                        new URL("http://127.0.0.1:8765/api/send_image").openConnection();
                c.setRequestMethod("POST");
                c.setDoOutput(true);
                c.setConnectTimeout(2000);
                c.setReadTimeout(20000);
                c.setRequestProperty("Content-Type", "application/octet-stream");
                try (OutputStream os = c.getOutputStream()) {
                    os.write(bytes);
                }
                code = c.getResponseCode();
                c.disconnect();
            } catch (Exception ignored) {
            }
            final int result = code;
            runOnUiThread(() -> {
                if (result != 200) {
                    Toast.makeText(this, "照片没发出去，稍后再试", Toast.LENGTH_SHORT).show();
                } else if (web != null) {
                    web.evaluateJavascript("window.__afterPhoto&&window.__afterPhoto()", null);
                }
            });
        }, "brainn-photo").start();
    }

    /** 工具鱼拍照：走 /api/tool/upload，回来作为附件 chip。 */
    private void uploadToolPhoto(byte[] bytes) {
        new Thread(() -> {
            String body = "";
            try {
                String name = "photo_" + System.currentTimeMillis() + ".jpg";
                HttpURLConnection c = (HttpURLConnection)
                        new URL("http://127.0.0.1:8765/api/tool/upload?name=" + name).openConnection();
                c.setRequestMethod("POST");
                c.setDoOutput(true);
                c.setConnectTimeout(2000);
                c.setReadTimeout(30000);
                c.setRequestProperty("Content-Type", "application/octet-stream");
                try (OutputStream os = c.getOutputStream()) {
                    os.write(bytes);
                }
                int code = c.getResponseCode();
                if (code == 200) {
                    java.io.BufferedReader reader = new java.io.BufferedReader(
                            new java.io.InputStreamReader(c.getInputStream(),
                                    java.nio.charset.StandardCharsets.UTF_8));
                    StringBuilder sb = new StringBuilder();
                    String line;
                    while ((line = reader.readLine()) != null) {
                        sb.append(line);
                    }
                    reader.close();
                    body = sb.toString();
                }
                c.disconnect();
            } catch (Exception ignored) {
            }
            final String json = body;
            runOnUiThread(() -> {
                if (json.isEmpty()) {
                    Toast.makeText(this, "照片没传上，稍后再试", Toast.LENGTH_SHORT).show();
                } else if (web != null) {
                    web.evaluateJavascript(
                            "window.__afterToolPhoto&&window.__afterToolPhoto(" + json + ")", null);
                }
            });
        }, "brainn-tool-photo").start();
    }

    /** 语音转文字：走系统语音识别，结果回填输入框，不发语音消息。 */
    void startVoiceInput() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_VOICE_PERM);
            return;
        }
        startRecognition(false);
    }

    /** 视频通话里的自动听：不按按钮，识别到一句就发一句。 */
    void startWorldListening() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            pendingWorldListening = true;
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_VOICE_PERM);
            return;
        }
        worldListenActive = true;
        pendingWorldListening = false;
        startRecognition(true);
    }

    void stopWorldListening() {
        worldListenActive = false;
        pendingWorldListening = false;
        if (worldListenRestart != null) {
            voiceHandler.removeCallbacks(worldListenRestart);
            worldListenRestart = null;
        }
        try {
            if (voiceRecognizer != null) {
                voiceRecognizer.cancel();
            }
        } catch (Throwable ignored) {
        }
        voiceListening = false;
    }

    private void startRecognition(boolean world) {
        runOnUiThread(() -> {
            try {
                if (voiceRecognizer == null) {
                    voiceRecognizer = SpeechRecognizer.createSpeechRecognizer(MainActivity.this);
                    voiceRecognizer.setRecognitionListener(new VoiceListener());
                }
                if (voiceListening) {
                    voiceRecognizer.cancel();
                }
                Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
                i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
                i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN");
                i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false);
                i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
                if (world) {
                    i.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 1300);
                    i.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 900);
                    i.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, 2200);
                }
                voiceListening = true;
                voiceRecognizer.startListening(i);
            } catch (Throwable e) {
                if (world) {
                    scheduleWorldRestart(1200);
                } else {
                    voiceResult("", false, "语音服务不可用");
                }
            }
        });
    }

    private void scheduleWorldRestart(long delayMs) {
        if (!worldListenActive) {
            return;
        }
        if (worldListenRestart != null) {
            voiceHandler.removeCallbacks(worldListenRestart);
        }
        worldListenRestart = () -> {
            worldListenRestart = null;
            if (worldListenActive) {
                startRecognition(true);
            }
        };
        voiceHandler.postDelayed(worldListenRestart, Math.max(300, delayMs));
    }

    private void voiceResult(String text, boolean ok, String err) {
        voiceListening = false;
        final String payload;
        try {
            JSONObject o = new JSONObject();
            o.put("text", text == null ? "" : text);
            o.put("ok", ok);
            o.put("err", err == null ? "" : err);
            payload = o.toString();
        } catch (Throwable e) {
            return;
        }
        if (web == null) {
            return;
        }
        web.post(new Runnable() {
            @Override
            public void run() {
                web.evaluateJavascript("window.__onVoiceResult&&window.__onVoiceResult(" + payload + ")", null);
            }
        });
    }

    private class VoiceListener implements RecognitionListener {
        @Override public void onReadyForSpeech(Bundle params) {}
        @Override public void onBeginningOfSpeech() {}
        @Override public void onRmsChanged(float rmsdB) {}
        @Override public void onBufferReceived(byte[] buffer) {}
        @Override public void onEndOfSpeech() {}
        @Override public void onPartialResults(Bundle partialResults) {}
        @Override public void onEvent(int eventType, Bundle params) {}

        @Override
        public void onError(int error) {
            if (worldListenActive) {
                if (error == SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS) {
                    stopWorldListening();
                    voiceResult("", false, "没有麦克风权限");
                    return;
                }
                scheduleWorldRestart(error == SpeechRecognizer.ERROR_RECOGNIZER_BUSY ? 1600 : 900);
                return;
            }
            voiceResult("", false, "语音识别失败（" + error + "）");
        }

        @Override
        public void onResults(Bundle results) {
            ArrayList<String> list = results == null ? null
                    : results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
            String text = (list != null && !list.isEmpty()) ? list.get(0) : "";
            if (worldListenActive) {
                if (!text.isEmpty()) {
                    voiceResult(text, true, "");
                }
                scheduleWorldRestart(650);
                return;
            }
            voiceResult(text, !text.isEmpty(), text.isEmpty() ? "没听清，再说一次" : "");
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_LOCATION_PERM) {
            if (locationPermissionGranted()) {
                fetchLocation();
            } else {
                sendLocationError("denied");
            }
            return;
        }
        if (requestCode == REQ_VOICE_PERM) {
            boolean granted = grantResults.length > 0
                    && grantResults[0] == PackageManager.PERMISSION_GRANTED;
            boolean wasWorld = pendingWorldListening;
            pendingWorldListening = false;
            if (granted) {
                if (wasWorld) {
                    startWorldListening();
                } else {
                    startVoiceInput();
                }
            } else {
                voiceResult("", false, "没有麦克风权限");
            }
            return;
        }
        if (requestCode == REQ_CALENDAR_PERM) {
            boolean granted = grantResults.length > 0
                    && grantResults[0] == PackageManager.PERMISSION_GRANTED;
            if (web != null) {
                web.evaluateJavascript(
                        "window.__onCalendarPerm&&window.__onCalendarPerm(" + granted + ")", null);
            }
            return;
        }
        if (requestCode == REQ_CAMERA_PERM) {
            boolean granted = grantResults.length > 0
                    && grantResults[0] == PackageManager.PERMISSION_GRANTED;
            if (granted && pendingCamera) {
                launchCamera();
            } else {
                Toast.makeText(this, "没有相机权限，拍不了照", Toast.LENGTH_SHORT).show();
            }
            pendingCamera = false;
        }
        if (requestCode == REQ_WORLD_CAMERA_PERM) {
            boolean granted = grantResults.length > 0
                    && grantResults[0] == PackageManager.PERMISSION_GRANTED;
            String session = pendingWorldSession;
            boolean wasPending = pendingWorldCall;
            pendingWorldCall = false;
            pendingWorldSession = "";
            if (granted && wasPending && worldCall != null) {
                worldCall.start(session);
            } else if (worldCall != null) {
                worldCall.failPermission();
            }
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == REQ_FILE) {
            if (pendingFileCallback != null) {
                Uri[] result = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
                pendingFileCallback.onReceiveValue(result);
                pendingFileCallback = null;
            }
            return;
        }
        if (requestCode == REQ_EXPORT) {
            Uri target = (resultCode == RESULT_OK && data != null) ? data.getData() : null;
            String src = pendingExportPath;
            pendingExportPath = null;
            pendingExportName = null;
            if (target != null && src != null) {
                copyExportTo(new File(src), target);
            } else if (src != null) {
                try {
                    new File(src).delete();
                } catch (Throwable ignored) {
                }
            }
            return;
        }
        if (requestCode == REQ_CAMERA) {
            if (resultCode == RESULT_OK && data != null && data.getExtras() != null) {
                Object extra = data.getExtras().get("data");
                if (extra instanceof Bitmap) {
                    Bitmap bitmap = (Bitmap) extra;
                    ByteArrayOutputStream out = new ByteArrayOutputStream();
                    bitmap.compress(Bitmap.CompressFormat.JPEG, 90, out);
                    if (pendingCameraTool) {
                        uploadToolPhoto(out.toByteArray());
                    } else {
                        uploadPhoto(out.toByteArray());
                    }
                }
            }
            pendingCameraTool = false;
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    /** 把导出的记忆包写到用户选的位置（U 盘、高速磁盘、云盘都走这里）。 */
    private void copyExportTo(final File src, final Uri target) {
        new Thread(() -> {
            boolean ok = false;
            String message;
            try (InputStream in = new FileInputStream(src);
                 OutputStream out = getContentResolver().openOutputStream(target, "w")) {
                if (out == null) {
                    throw new IOException("无法写入目标文件");
                }
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) {
                    out.write(buf, 0, n);
                }
                out.flush();
                ok = true;
                message = "记忆已提取到所选设备";
            } catch (Throwable t) {
                message = "写入失败：" + t.getMessage();
            }
            final boolean done = ok;
            final String text = message;
            runOnUiThread(() -> {
                Toast.makeText(MainActivity.this, text, Toast.LENGTH_LONG).show();
                jsCallback("window.__onMemoryExported&&window.__onMemoryExported(" + done + ")");
                if (done) {
                    try {
                        src.delete();
                    } catch (Throwable ignored) {
                    }
                }
            });
        }, "memory-export").start();
    }

    @Override
    public void onBackPressed() {
        if (web == null) {
            moveTaskToBack(true);
            return;
        }
        try {
            web.evaluateJavascript(
                    "(function(){try{return window.__androidBack?!!window.__androidBack():false}catch(e){return false}})()",
                    value -> {
                        boolean handled = value != null && value.contains("true");
                        if (!handled) {
                            // 没有可退的层：回桌面，前台服务继续跑
                            moveTaskToBack(true);
                        }
                    });
        } catch (Throwable ignored) {
            moveTaskToBack(true);
        }
    }

    // ---- 云端 TTS（MiniMax speech-02-hd） ----

    private void jsCallback(String js) {
        runOnUiThread(() -> {
            try { web.evaluateJavascript(js, null); } catch (Throwable ignored) {}
        });
    }

    private void mmStop() {
        mmSpeaking = null;
        runOnUiThread(() -> {
            try {
                if (mmPlayer != null) {
                    try { if (mmPlayer.isPlaying()) mmPlayer.stop(); } catch (Throwable ignored) {}
                    mmPlayer.release();
                    mmPlayer = null;
                }
            } catch (Throwable ignored) {}
        });
    }

    /** 合成并播放；没配 Key/Group 时返回 false，由 JS 退回系统 TTS。 */
    private boolean mmSpeak(String text, String emotion) {
        final String key = mmKey.trim();
        final String group = mmGroup.trim();
        if (key.isEmpty() || group.isEmpty()) return false;
        final String t = text.trim();
        if (t.isEmpty()) return false;
        mmStop();
        mmSpeaking = t;
        final String voice = mmVoice.trim().isEmpty() ? "whale_xisite_01" : mmVoice.trim();
        final String emo = emotion == null || emotion.trim().isEmpty() ? "neutral" : emotion.trim();
        final int pitch = Math.max(-12, Math.min(12, mmPitch));
        new Thread(() -> {
            File audio;
            try {
                File dir = new File(getFilesDir(), "tts_cache");
                //noinspection ResultOfMethodCallIgnored
                dir.mkdirs();
                File cached = new File(dir, mmHash(voice + "|" + pitch + "|" + t) + ".mp3");
                if (cached.exists() && cached.length() > 0) {
                    cached.setLastModified(System.currentTimeMillis());
                    audio = cached;
                } else {
                    byte[] mp3 = mmRequest(key, group, voice, emo, pitch, t);
                    if (mp3 == null || mp3.length == 0) {
                        jsCallback("window.__whaleTts&&window.__whaleTts.onError&&window.__whaleTts.onError()");
                        return;
                    }
                    FileOutputStream fos = new FileOutputStream(cached);
                    fos.write(mp3);
                    fos.close();
                    mmTrim(dir);
                    audio = cached;
                }
            } catch (Throwable e) {
                jsCallback("window.__whaleTts&&window.__whaleTts.onError&&window.__whaleTts.onError()");
                return;
            }
            if (!t.equals(mmSpeaking)) return; // 合成期间被更新的请求打断
            final File play = audio;
            runOnUiThread(() -> {
                try {
                    mmPlayer = new MediaPlayer();
                    mmPlayer.setDataSource(play.getAbsolutePath());
                    mmPlayer.prepare();
                    final int durMs = mmPlayer.getDuration();
                    mmPlayer.setOnCompletionListener(mp ->
                            jsCallback("window.__whaleTts&&window.__whaleTts.onEnd&&window.__whaleTts.onEnd()"));
                    mmPlayer.setOnErrorListener((mp, what, extra) -> {
                        jsCallback("window.__whaleTts&&window.__whaleTts.onError&&window.__whaleTts.onError()");
                        return true;
                    });
                    mmPlayer.start();
                    // 播放开始：把真实音频时长回传给页面，嘴型按真实时长驱动
                    jsCallback("window.__whaleTts&&window.__whaleTts.onStart&&window.__whaleTts.onStart(" + durMs + ")");
                } catch (Throwable e) {
                    jsCallback("window.__whaleTts&&window.__whaleTts.onError&&window.__whaleTts.onError()");
                }
            });
        }, "mm-tts").start();
        return true;
    }

    private byte[] mmRequest(String key, String group, String voice, String emotion, int pitch, String text) throws Exception {
        JSONObject body = new JSONObject();
        body.put("model", "speech-02-hd");
        body.put("text", text);
        body.put("stream", false);
        JSONObject vs = new JSONObject();
        vs.put("voice_id", voice);
        vs.put("speed", 1.05);
        vs.put("vol", 1.0);
        vs.put("pitch", pitch); // 克隆音色 0（升调会失真），预置音色才微调
        if (!"neutral".equals(emotion)) vs.put("emotion", emotion);
        body.put("voice_setting", vs);
        JSONObject as = new JSONObject();
        as.put("sample_rate", 32000);
        as.put("bitrate", 128000);
        as.put("format", "mp3");
        as.put("channel", 1);
        body.put("audio_setting", as);

        HttpURLConnection c = (HttpURLConnection) new URL(
                "https://api.minimaxi.com/v1/t2a_v2?GroupId=" + group).openConnection();
        c.setRequestMethod("POST");
        c.setConnectTimeout(10000);
        c.setReadTimeout(30000);
        c.setDoOutput(true);
        c.setRequestProperty("Authorization", "Bearer " + key);
        c.setRequestProperty("Content-Type", "application/json");
        byte[] payload = body.toString().getBytes("UTF-8");
        OutputStream os = c.getOutputStream();
        os.write(payload);
        os.close();
        int code = c.getResponseCode();
        InputStream is = code >= 200 && code < 300 ? c.getInputStream() : c.getErrorStream();
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while (is != null && (n = is.read(buf)) != -1) bos.write(buf, 0, n);
        c.disconnect();
        String raw = new String(bos.toByteArray(), "UTF-8");
        if (code < 200 || code >= 300) {
            Log.e("GanFanYu", "mm tts http " + code + ": " + raw);
            return null;
        }
        JSONObject resp = new JSONObject(raw);
        JSONObject base = resp.optJSONObject("base_resp");
        if (base != null && base.optInt("status_code", 0) != 0) {
            // 常见：1004 密钥无效、1008 额度不足、1002 限流
            Log.e("GanFanYu", "mm tts api " + base.optInt("status_code", -1) + ": "
                    + base.optString("status_msg"));
            return null;
        }
        JSONObject data = resp.optJSONObject("data");
        if (data == null) return null;
        String hex = data.optString("audio", "");
        if (hex.isEmpty()) return null;
        byte[] out = new byte[hex.length() / 2];
        for (int i = 0; i < out.length; i++) {
            out[i] = (byte) Integer.parseInt(hex.substring(i * 2, i * 2 + 2), 16);
        }
        return out;
    }

    private String mmHash(String s) {
        try {
            MessageDigest md = MessageDigest.getInstance("MD5");
            byte[] d = md.digest(s.getBytes("UTF-8"));
            StringBuilder sb = new StringBuilder();
            for (byte b : d) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (Throwable e) {
            return String.valueOf(s.hashCode());
        }
    }

    /** LRU：缓存目录最多保留 200 条，先删最旧的。 */
    private void mmTrim(File dir) {
        try {
            File[] fs = dir.listFiles();
            if (fs == null || fs.length <= 200) return;
            Arrays.sort(fs, Comparator.comparingLong(File::lastModified));
            for (int i = 0; i < fs.length - 200; i++) {
                //noinspection ResultOfMethodCallIgnored
                fs[i].delete();
            }
        } catch (Throwable ignored) {}
    }

    public class AndroidBridge {
        @JavascriptInterface
        public void openNotificationSettings() {
            try {
                Intent i = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS);
                i.putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName());
                startActivity(i);
            } catch (Exception ignored) {
                try {
                    startActivity(new Intent(Settings.ACTION_SETTINGS));
                } catch (Exception ignored2) {
                }
            }
        }

        @JavascriptInterface
        public String platform() {
            return "android";
        }

        @JavascriptInterface
        public boolean hasVoiceInput() {
            return true;
        }

        @JavascriptInterface
        public void startVoiceInput() {
            MainActivity.this.startVoiceInput();
        }

        @JavascriptInterface
        public boolean hasTts() {
            return ttsReady;
        }

        @JavascriptInterface
        public boolean hasCloudTts() {
            return !mmKey.trim().isEmpty() && !mmGroup.trim().isEmpty();
        }

        /** 小鲸鱼页把 localStorage 里的云端语音配置推过来。 */
        @JavascriptInterface
        public void setTtsCloudConfig(String json) {
            try {
                JSONObject o = new JSONObject(json == null ? "{}" : json);
                mmKey = o.optString("key", "");
                mmGroup = o.optString("group", "");
                String v = o.optString("voice", "");
                if (!v.trim().isEmpty()) mmVoice = v.trim();
                mmPitch = o.optInt("pitch", 0);
            } catch (Throwable ignored) {
            }
        }

        /** 云端合成播放；未配置时返回 false，JS 退回系统 TTS。emotion 由页面按她的心情给。 */
        @JavascriptInterface
        public boolean speakCloud(String text, String emotion) {
            if (text == null) return false;
            return mmSpeak(text, emotion);
        }

        /**
         * 预合成固定台词（触摸/道具/空闲的那几十句），只写缓存不播放。
         * 之后同一句直接命中缓存，不再消耗 MiniMax 额度。
         */
        @JavascriptInterface
        public void precacheCloud(String json) {
            if (json == null || json.isEmpty()) return;
            final String key = mmKey;
            final String group = mmGroup;
            if (key.trim().isEmpty() || group.trim().isEmpty()) return;
            final String voice = mmVoice.trim().isEmpty() ? "whale_jelpeita_01" : mmVoice.trim();
            final int pitch = Math.max(-12, Math.min(12, mmPitch));
            new Thread(() -> {
                try {
                    org.json.JSONArray arr = new org.json.JSONArray(json);
                    File dir = new File(getFilesDir(), "tts_cache");
                    //noinspection ResultOfMethodCallIgnored
                    dir.mkdirs();
                    for (int i = 0; i < arr.length(); i++) {
                        String t = arr.optString(i, "").trim();
                        if (t.isEmpty()) continue;
                        File cached = new File(dir, mmHash(voice + "|" + pitch + "|" + t) + ".mp3");
                        if (cached.exists() && cached.length() > 0) continue;
                        byte[] mp3 = mmRequest(key, group, voice, "neutral", pitch, t);
                        if (mp3 == null || mp3.length == 0) break; // 额度或网络异常就别继续烧
                        FileOutputStream fos = new FileOutputStream(cached);
                        fos.write(mp3);
                        fos.close();
                        Thread.sleep(350); // 限速，避免触发 1002 限流
                    }
                    mmTrim(dir);
                    Log.i("BrainN", "precache done");
                } catch (Throwable e) {
                    Log.w("BrainN", "precache failed", e);
                }
            }, "mm-precache").start();
        }

        @JavascriptInterface
        public void speak(String text, float rate, float pitch) {
            final String t = text == null ? "" : text.trim();
            if (t.isEmpty()) {
                return;
            }
            runOnUiThread(() -> {
                if (tts == null) {
                    return;
                }
                if (!ttsReady) {
                    pendingSpeak = t;
                    return;
                }
                try {
                    tts.setSpeechRate(rate > 0 ? rate : 1.05f);
                    tts.setPitch(pitch > 0 ? pitch : 1.15f);
                    tts.speak(t, TextToSpeech.QUEUE_FLUSH, null, "whale");
                } catch (Throwable ignored) {
                }
            });
        }

        @JavascriptInterface
        public void stopSpeak() {
            runOnUiThread(() -> {
                try {
                    if (tts != null) {
                        tts.stop();
                    }
                } catch (Throwable ignored) {
                }
            });
            mmStop();
            jsCallback("window.__whaleTts&&window.__whaleTts.onEnd&&window.__whaleTts.onEnd()");
        }

        @JavascriptInterface
        public void setSystemBarTheme(String theme) {
            runOnUiThread(() -> applySystemBarTheme(String.valueOf(theme)));
        }

        @JavascriptInterface
        public void takePhoto() {
            runOnUiThread(() -> requestCameraThenLaunch());
        }

        @JavascriptInterface
        public void takePhotoForTool() {
            runOnUiThread(() -> requestCameraThenLaunch(true));
        }

        @JavascriptInterface
        public boolean hasCamera() {
            return Build.VERSION.SDK_INT < 23
                    || checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED;
        }

        @JavascriptInterface
        public void startArPet() {
            runOnUiThread(() -> {
                try {
                    startActivity(new Intent(MainActivity.this, ArPetActivity.class));
                } catch (Throwable t) {
                    Toast.makeText(MainActivity.this, "AR 打不开：" + t.getMessage(), Toast.LENGTH_SHORT).show();
                }
            });
        }

        @JavascriptInterface
        public void startWorldCall(String sessionId) {
            runOnUiThread(() -> {
                if (worldCall == null) {
                    return;
                }
                if (Build.VERSION.SDK_INT >= 23
                        && checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                    pendingWorldCall = true;
                    pendingWorldSession = sessionId == null ? "" : sessionId;
                    requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_WORLD_CAMERA_PERM);
                    return;
                }
                worldCall.start(sessionId == null ? "" : sessionId);
            });
        }

        @JavascriptInterface
        public void endWorldCall() {
            runOnUiThread(() -> {
                if (worldCall != null) {
                    worldCall.stop();
                }
                stopWorldListening();
            });
        }

        @JavascriptInterface
        public void startWorldListening() {
            runOnUiThread(MainActivity.this::startWorldListening);
        }

        @JavascriptInterface
        public void stopWorldListening() {
            runOnUiThread(MainActivity.this::stopWorldListening);
        }

        @JavascriptInterface
        public void pauseWorldCall() {
            runOnUiThread(() -> {
                if (worldCall != null) {
                    worldCall.setUserPaused(true);
                }
            });
        }

        @JavascriptInterface
        public void resumeWorldCall() {
            runOnUiThread(() -> {
                if (worldCall != null) {
                    worldCall.setUserPaused(false);
                }
            });
        }

        @JavascriptInterface
        public void setWorldCamera(String lens) {
            runOnUiThread(() -> {
                if (worldCall != null) {
                    worldCall.setFront(!"back".equalsIgnoreCase(String.valueOf(lens)));
                }
            });
        }

        @JavascriptInterface
        public void worldLookNow() {
            if (worldCall != null) {
                worldCall.requestSnapshot(true);
            }
        }

        @JavascriptInterface
        public boolean hasLocationPermission() {
            return locationPermissionGranted();
        }

        @JavascriptInterface
        public void requestLocation() {
            runOnUiThread(MainActivity.this::requestLocationThenFetch);
        }

        @JavascriptInterface
        public void openUrl(String url) {
            String u = String.valueOf(url == null ? "" : url).trim();
            if (!u.startsWith("http://") && !u.startsWith("https://")) {
                return;
            }
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(u)));
            } catch (Exception e) {
                Toast.makeText(MainActivity.this, "没有可用的浏览器", Toast.LENGTH_SHORT).show();
            }
        }

        @JavascriptInterface
        public boolean hasOverlay() {
            return Settings.canDrawOverlays(MainActivity.this);
        }

        @JavascriptInterface
        public boolean getPetGravity() {
            return FloatingOverlay.getGravityEnabled(MainActivity.this);
        }

        @JavascriptInterface
        public void setPetGravity(boolean on) {
            FloatingOverlay.setGravityEnabled(MainActivity.this, on);
        }

        @JavascriptInterface
        public void openOverlaySettings() {
            try {
                Intent i = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:" + getPackageName()));
                startActivity(i);
            } catch (Exception e) {
                try {
                    startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION));
                } catch (Exception ignored) {
                }
            }
        }

        @JavascriptInterface
        public void showFloating() {
            try {
                Intent i = new Intent(MainActivity.this, BrainService.class);
                i.setAction(BrainService.ACTION_SHOW_FLOATING);
                startService(i);
            } catch (Exception ignored) {
            }
        }

        @JavascriptInterface
        public void hideFloating() {
            try {
                Intent i = new Intent(MainActivity.this, BrainService.class);
                i.setAction(BrainService.ACTION_HIDE_FLOATING);
                startService(i);
            } catch (Exception ignored) {
            }
        }

        @JavascriptInterface
        public void setWhalePage(boolean on) {
            FloatingOverlay.setWhalePage(MainActivity.this, on);
        }

        /** 提取记忆：把后端打好的 zip 交给系统文件选择器，可存到 U 盘/高速磁盘。 */
        @JavascriptInterface
        public void saveMemoryExport(String path, String name) {
            runOnUiThread(() -> {
                try {
                    File src = new File(path);
                    if (!src.exists()) {
                        Toast.makeText(MainActivity.this, "导出文件不存在，请重试", Toast.LENGTH_SHORT).show();
                        return;
                    }
                    pendingExportPath = path;
                    pendingExportName = name == null || name.isEmpty() ? src.getName() : name;
                    Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
                    intent.addCategory(Intent.CATEGORY_OPENABLE);
                    intent.setType("application/zip");
                    intent.putExtra(Intent.EXTRA_TITLE, pendingExportName);
                    startActivityForResult(intent, REQ_EXPORT);
                } catch (Throwable t) {
                    Toast.makeText(MainActivity.this, "打不开保存位置：" + t.getMessage(),
                            Toast.LENGTH_SHORT).show();
                }
            });
        }

        @JavascriptInterface
        public boolean hasCalendarPermission() {
            return Build.VERSION.SDK_INT < 23
                    || checkSelfPermission(Manifest.permission.READ_CALENDAR) == PackageManager.PERMISSION_GRANTED;
        }

        @JavascriptInterface
        public void requestCalendarPermission() {
            if (hasCalendarPermission()) {
                return;
            }
            runOnUiThread(() -> requestPermissions(
                    new String[]{Manifest.permission.READ_CALENDAR}, REQ_CALENDAR_PERM));
        }

        /** 今日待办：读手机日历里今天的日程，按开始时间排。 */
        @JavascriptInterface
        public String todayTodos() {
            JSONObject out = new JSONObject();
            try {
                out.put("permission", hasCalendarPermission());
                JSONArray items = new JSONArray();
                if (hasCalendarPermission()) {
                    java.util.Calendar c = java.util.Calendar.getInstance();
                    c.set(java.util.Calendar.HOUR_OF_DAY, 0);
                    c.set(java.util.Calendar.MINUTE, 0);
                    c.set(java.util.Calendar.SECOND, 0);
                    c.set(java.util.Calendar.MILLISECOND, 0);
                    long start = c.getTimeInMillis();
                    long end = start + 24L * 60L * 60L * 1000L;
                    Uri.Builder b = android.provider.CalendarContract.Instances.CONTENT_URI.buildUpon();
                    android.content.ContentUris.appendId(b, start);
                    android.content.ContentUris.appendId(b, end);
                    android.database.Cursor cur = getContentResolver().query(
                            b.build(),
                            new String[]{
                                    android.provider.CalendarContract.Instances.TITLE,
                                    android.provider.CalendarContract.Instances.BEGIN,
                                    android.provider.CalendarContract.Instances.END,
                                    android.provider.CalendarContract.Instances.ALL_DAY,
                                    android.provider.CalendarContract.Instances.EVENT_LOCATION
                            },
                            null, null,
                            android.provider.CalendarContract.Instances.BEGIN + " ASC");
                    if (cur != null) {
                        while (cur.moveToNext() && items.length() < 6) {
                            JSONObject o = new JSONObject();
                            o.put("title", cur.getString(0) == null ? "" : cur.getString(0));
                            o.put("begin", cur.getLong(1));
                            o.put("end", cur.getLong(2));
                            o.put("allDay", cur.getInt(3) == 1);
                            o.put("place", cur.getString(4) == null ? "" : cur.getString(4));
                            items.put(o);
                        }
                        cur.close();
                    }
                }
                out.put("ok", true);
                out.put("items", items);
            } catch (Throwable t) {
                try {
                    out.put("ok", false);
                    out.put("error", String.valueOf(t.getMessage()));
                } catch (Throwable ignored) {
                }
            }
            return out.toString();
        }

        @JavascriptInterface
        public boolean hasUsageAccess() {
            return UsageReader.hasAccess(MainActivity.this);
        }

        @JavascriptInterface
        public void openUsageAccessSettings() {
            try {
                startActivity(new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS));
            } catch (Exception ignored) {
            }
        }

        @JavascriptInterface
        public String currentApp() {
            return UsageReader.currentAppJson();
        }

        @JavascriptInterface
        public void setChatFocused(boolean focused) {
            AppState.chatFocused = focused;
        }

        @JavascriptInterface
        public String notifyStatus() {
            try {
                JSONObject out = new JSONObject();
                out.put("enabled", Notifier.canNotify());
                out.put("permission", Notifier.permissionGranted());
                out.put("channel", Notifier.channelImportance());
                return out.toString();
            } catch (Throwable ignored) {
                return "{}";
            }
        }

        @JavascriptInterface
        public void requestNotifyPermission() {
            runOnUiThread(MainActivity.this::requestNotificationPermission);
        }

        @JavascriptInterface
        public boolean canNotify() {
            return Notifier.canNotify();
        }

        @JavascriptInterface
        public void testNotification() {
            Notifier.showTest("小鲸鱼", "通知通道正常，她回消息时就会这样提示你。");
        }
    }
}
