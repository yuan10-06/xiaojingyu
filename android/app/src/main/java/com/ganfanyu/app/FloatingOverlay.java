package com.ganfanyu.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.Settings;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.View;
import android.view.WindowManager;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** 桌面桌宠：透明 WebView 播放动画；重力开关打开时单击可切换重力，双击弹出小鲸鱼对话。 */
final class FloatingOverlay {
    private static final String BASE = "http://127.0.0.1:8765";
    private static final String PAGE = BASE + "/whale/pet_overlay.html";
    private static final String PREFS = "float_overlay";
    private static final String KEY_ENABLED = "enabled";
    private static final String KEY_GRAVITY = "gravity";
    private static final Handler UI = new Handler(Looper.getMainLooper());
    private static final int PET_W_DP = 250;
    private static final int PET_H_DP = 141;
    /** 双击判定窗口：两次单击间隔小于它就当双击开对话，否则切重力 */
    private static final long DOUBLE_TAP_MS = 320;

    private static Context ctx;
    private static WindowManager wm;
    private static WebView petView;
    private static WindowManager.LayoutParams petParams;
    private static View petHit;
    private static WindowManager.LayoutParams hitParams;
    private static float hitL = 0.02f;
    private static float hitT = 0.02f;
    private static float hitW = 0.64f;
    private static float hitH = 0.88f;
    private static LinearLayout panel;
    private static TextView balanceView;
    private static Typeface petFont;
    private static JSONArray history = new JSONArray();
    private static volatile boolean enabled;
    private static volatile boolean suppressed;
    private static volatile boolean whalePage;
    private static volatile boolean backendReady;
    private static int petBootTries;
    private static int petLoadRetry;
    private static boolean panelOpen;
    private static long lastTapAt;
    private static android.animation.ValueAnimator walker;

    /* ---------------- 重力模式 ---------------- */
    private static volatile boolean gravityOn;
    private static boolean physicsPaused;
    private static SensorManager sensors;
    private static SensorEventListener motionListener;
    private static volatile float accX, accY;
    private static volatile float gyroZ;
    private static boolean accReady;
    private static float smoothX, smoothY;
    private static float physX, physY;
    private static float velX, velY;
    private static long lastTickAt;
    private static int tickFrame;
    /* 单击要等一个双击窗口再执行，避免误判 */
    private static boolean pendingSingleTap;
    private static final Runnable SINGLE_TAP_RUN = new Runnable() {
        @Override
        public void run() {
            if (!pendingSingleTap) {
                return;
            }
            pendingSingleTap = false;
            // 重力开关关着时，单击完全无反应，避免手一碰她就乱跑
            if (!isGravityPref(ctx)) {
                return;
            }
            setGravityMode(!gravityOn);
            setGravityPref(ctx, gravityOn);
        }
    };
    private static final Runnable PHYSICS_TICK = new Runnable() {
        @Override
        public void run() {
            if (!gravityOn || petView == null || petParams == null || wm == null) {
                return;
            }
            stepPhysics();
            UI.postDelayed(this, 16);
        }
    };

    private FloatingOverlay() {
    }

    static boolean isShowing() {
        return petView != null;
    }

    /** AR 页在前台时先收掉桌面桌宠，避免两只鲸鱼叠在一起；退出 AR 后自动恢复。 */
    static void setArActive(boolean on) {
        suppressed = on;
        UI.post(() -> {
            if (on) {
                closePanel();
                removePetView();
                return;
            }
            if (AppState.activityVisible && isEnabled(ctx)) {
                enabled = true;
                syncVisibility();
            }
        });
    }

    static boolean isEnabled(Context context) {
        if (context == null) {
            return enabled;
        }
        SharedPreferences sp = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        return sp.getBoolean(KEY_ENABLED, false);
    }

    private static void setEnabled(Context context, boolean on) {
        enabled = on;
        try {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                    .edit().putBoolean(KEY_ENABLED, on).apply();
        } catch (Throwable ignored) {
        }
    }

    /** 重力开关：默认关闭，记住上次选择。 */
    private static boolean isGravityPref(Context context) {
        if (context == null) {
            return false;
        }
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getBoolean(KEY_GRAVITY, false);
    }

    private static void setGravityPref(Context context, boolean on) {
        if (context == null) {
            return;
        }
        try {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                    .edit().putBoolean(KEY_GRAVITY, on).apply();
        } catch (Throwable ignored) {
        }
    }

    /** 给主界面读取开关状态。 */
    static boolean getGravityEnabled(Context context) {
        return isGravityPref(context);
    }

    /** 给主界面切换开关：立即作用到正在运行的桌宠，不用重开。 */
    static void setGravityEnabled(Context context, boolean on) {
        setGravityPref(context, on);
        UI.post(() -> {
            if (on) {
                if (petView == null || petParams == null || wm == null) {
                    return;
                }
                setGravityMode(true, true);
            } else {
                setGravityMode(false, true);
            }
        });
    }

    /** BrainService 启动时恢复用户上次开着的状态。 */
    static void restore(Context context) {
        ctx = context.getApplicationContext();
        backendReady = true;
        if (!isEnabled(context)) {
            return;
        }
        enabled = true;
        UI.post(() -> {
            syncVisibility();
            if (petView != null) {
                petLoadRetry = 0;
                petView.loadUrl(PAGE);
            }
        });
    }

    static void show(Context context) {
        ctx = context.getApplicationContext();
        if (!Settings.canDrawOverlays(context)) {
            Toast.makeText(context, "请先授权悬浮窗权限", Toast.LENGTH_SHORT).show();
            return;
        }
        setEnabled(context, true);
        enabled = true;
        addPetView();
        if (AppState.activityVisible && whalePage) {
            Toast.makeText(context, "2D 页里不显示桌宠，切到其他页面就能看到", Toast.LENGTH_SHORT).show();
        }
    }

    static void hide() {
        if (ctx != null) {
            setEnabled(ctx, false);
        }
        enabled = false;
        closePanel();
        removePetView();
        AppState.floatingVisible = false;
    }

    /** 当前是不是在 2D 小鲸鱼页。是的话 App 前台时不出桌宠。 */
    static void setWhalePage(Context context, boolean on) {
        ctx = context.getApplicationContext();
        whalePage = on;
        UI.post(() -> {
            if (whalePage) {
                closePanel();
                removePetView();
                return;
            }
            if (AppState.activityVisible && isEnabled(ctx)) {
                enabled = true;
                addPetView();
            }
        });
    }

    /** App 回到前台：除了 2D 页，桌宠都浮在 App 上面。 */
    static void onAppResume(Context context) {
        ctx = context.getApplicationContext();
        if (!AppState.activityVisible && !isEnabled(context)) {
            return;
        }
        if (isEnabled(context)) {
            enabled = true;
            syncVisibility();
        } else {
            closePanel();
            removePetView();
        }
    }

    /** App 退到后台/桌面：桌宠继续留在桌面。 */
    static void onAppPause(Context context) {
        ctx = context.getApplicationContext();
        if (!isEnabled(context)) {
            return;
        }
        enabled = true;
        addPetView();
    }

    static void onActivityDestroyed() {
        closePanel();
        removePetView();
    }

    private static void syncVisibility() {
        if (AppState.activityVisible && whalePage) {
            closePanel();
            removePetView();
            return;
        }
        addPetView();
    }

    // ------------------------------------------------------------------
    private static void addPetView() {
        if (suppressed) {
            return;
        }
        if (Looper.myLooper() != Looper.getMainLooper()) {
            UI.post(FloatingOverlay::addPetView);
            return;
        }
        if (petView != null || ctx == null || !Settings.canDrawOverlays(ctx)) {
            return;
        }
        if (!isEnabled(ctx)) {
            enabled = false;
            return;
        }
        // 本地服务还没起来时不挂，免得挂上 chrome 错误页
        if (!backendReady) {
            if (petBootTries < 40) {
                petBootTries += 1;
                UI.postDelayed(FloatingOverlay::addPetView, 2000);
            }
            return;
        }
        petBootTries = 0;
        // WebView 必须用 Activity context，application context 会白屏成 about:blank
        android.app.Activity act = AppState.activity;
        if (act == null || act.isDestroyed()) {
            return;
        }
        wm = (WindowManager) ctx.getSystemService(Context.WINDOW_SERVICE);
        if (wm == null) {
            return;
        }
        petView = new WebView(act);
        petView.setBackgroundColor(Color.TRANSPARENT);
        // 桌面桌宠要“实”一点：默认 alpha 固定为 1，避免半透明看起来发虚
        petView.setAlpha(1f);
        petView.setLayerType(View.LAYER_TYPE_HARDWARE, null);
        petView.setVerticalScrollBarEnabled(false);
        petView.setHorizontalScrollBarEnabled(false);
        WebSettings ws = petView.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setMediaPlaybackRequiresUserGesture(false);
        petView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                petLoadRetry = 0;
                android.util.Log.i("GanFanYu", "pet overlay finished " + url);
            }

            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                android.util.Log.e("GanFanYu", "pet overlay load error " + errorCode + " " + description + " " + failingUrl);
                if (petLoadRetry < 3) {
                    petLoadRetry += 1;
                    UI.postDelayed(() -> {
                        if (petView != null) {
                            petView.loadUrl(PAGE);
                        }
                    }, 2500);
                }
            }
        });
        petView.loadUrl(PAGE);
        petView.addJavascriptInterface(new PetBridge(), "PetNative");

        // 画面层完全不收触摸：透明的地方可以直接点穿到桌面/下面的 App
        petParams = new WindowManager.LayoutParams(
                dp(PET_W_DP), dp(PET_H_DP),
                overlayType(),
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
                        | WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
                PixelFormat.TRANSLUCENT);
        petParams.gravity = Gravity.TOP | Gravity.START;
        petParams.x = dp(16);
        petParams.y = dp(240);
        try {
            wm.addView(petView, petParams);
            petView.onResume();
            AppState.floatingVisible = true;
        } catch (Throwable t) {
            petView = null;
            Toast.makeText(ctx, "桌宠没有加上：" + t.getMessage(), Toast.LENGTH_SHORT).show();
            return;
        }

        // 命中层：只覆盖角色身体那一小块，跟着画面里的不透明像素收缩
        petHit = new View(act);
        petHit.setBackgroundColor(Color.TRANSPARENT);
        petHit.setOnTouchListener(new PetTouchListener());
        hitParams = new WindowManager.LayoutParams(
                dp(PET_W_DP), dp(PET_H_DP),
                overlayType(),
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT);
        hitParams.gravity = Gravity.TOP | Gravity.START;
        hitParams.x = petParams.x;
        hitParams.y = petParams.y;
        try {
            wm.addView(petHit, hitParams);
            layoutHit();
        } catch (Throwable t) {
            petHit = null;
            Toast.makeText(ctx, "桌宠没有加上：" + t.getMessage(), Toast.LENGTH_SHORT).show();
            removePetView();
            return;
        }
        // 上次开关是开着的，就把重力接上；静默恢复，不弹提示
        if (isGravityPref(ctx)) {
            setGravityMode(true, true);
        }
    }

    private static void removePetView() {
        stopGravity();
        UI.removeCallbacks(SINGLE_TAP_RUN);
        pendingSingleTap = false;
        if (walker != null) {
            walker.cancel();
            walker = null;
        }
        try {
            if (petHit != null && wm != null) {
                wm.removeView(petHit);
            }
        } catch (Throwable ignored) {
        }
        petHit = null;
        try {
            if (petView != null && wm != null) {
                wm.removeView(petView);
            }
        } catch (Throwable ignored) {
        }
        if (petView != null) {
            try {
                petView.onPause();
            } catch (Throwable ignored) {
            }
            try {
                petView.destroy();
            } catch (Throwable ignored) {
            }
        }
        petView = null;
        AppState.floatingVisible = false;
    }

    private static void petReply(String text, double valence, double arousal) {
        if (petView == null) {
            return;
        }
        final String js = "window.__petReply&&window.__petReply("
                + JSONObject.quote(text) + "," + valence + "," + arousal + ")";
        UI.post(() -> {
            if (petView != null) {
                try {
                    petView.evaluateJavascript(js, null);
                } catch (Throwable ignored) {
                }
            }
        });
    }

    // ------------------------------------------------------------------
    private static void openPanel() {
        if (panel != null || wm == null || ctx == null) {
            return;
        }
        panelOpen = true;
        AppState.floatingVisible = true;
        panel = new LinearLayout(ctx);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(10), dp(8), dp(8), dp(8));
        panel.setBackground(round(0xe6ffffff, 18));

        balanceView = new TextView(ctx);
        balanceView.setText("余额：查询中…");
        balanceView.setTextColor(0xff5b7f93);
        balanceView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        balanceView.setPadding(dp(4), 0, dp(4), dp(6));
        applyPetFont(balanceView);

        LinearLayout row = new LinearLayout(ctx);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);

        EditText input = new EditText(ctx);
        input.setHint("和本鱼说点什么…");
        input.setHintTextColor(0xff8fb0bf);
        input.setTextColor(0xff2c5a73);
        input.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        input.setSingleLine(true);
        input.setInputType(InputType.TYPE_CLASS_TEXT);
        input.setBackground(round(0xffeef7fb, 12));
        input.setPadding(dp(10), dp(7), dp(10), dp(7));
        input.setLayoutParams(new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        applyPetFont(input);

        Button send = new Button(ctx);
        send.setText("发送");
        send.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        send.setTextColor(Color.WHITE);
        send.setBackground(round(0xff4da3c7, 12));
        send.setPadding(dp(12), dp(7), dp(12), dp(7));
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        sp.leftMargin = dp(8);
        send.setLayoutParams(sp);
        applyPetFont(send);

        TextView close = new TextView(ctx);
        close.setText("×");
        close.setTextColor(0xff7a97a6);
        close.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        close.setPadding(dp(8), dp(2), dp(4), dp(2));
        close.setOnClickListener(v -> closePanel());
        applyPetFont(close);

        row.addView(input);
        row.addView(send);
        row.addView(close);
        panel.addView(balanceView);
        panel.addView(row);

        send.setOnClickListener(v -> {
            String text = input.getText().toString().trim();
            if (text.isEmpty()) {
                return;
            }
            input.setText("");
            askWhale(text);
        });
        input.setOnEditorActionListener((v, actionId, event) -> {
            String text = input.getText().toString().trim();
            if (text.isEmpty()) {
                return false;
            }
            input.setText("");
            askWhale(text);
            return true;
        });

        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                dp(300), WindowManager.LayoutParams.WRAP_CONTENT,
                overlayType(),
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT);
        params.gravity = Gravity.TOP | Gravity.START;
        int sw = ctx.getResources().getDisplayMetrics().widthPixels;
        int sh = ctx.getResources().getDisplayMetrics().heightPixels;
        int pw = dp(300);
        int petX = petParams != null ? petParams.x : dp(16);
        int petY = petParams != null ? petParams.y : dp(240);
        params.x = Math.max(dp(8), Math.min(sw - pw - dp(8), petX));
        int belowY = petY + dp(PET_H_DP) + dp(8);
        params.y = belowY + dp(60) < sh * 0.6f
                ? belowY
                : Math.max(dp(40), petY - dp(56) - dp(8));
        try {
            wm.addView(panel, params);
        } catch (Throwable t) {
            android.util.Log.e("GanFanYu", "panel add failed", t);
            panel = null;
            panelOpen = false;
            return;
        }
        input.requestFocus();
        UI.postDelayed(() -> {
            try {
                android.view.inputmethod.InputMethodManager imm =
                        (android.view.inputmethod.InputMethodManager)
                                ctx.getSystemService(Context.INPUT_METHOD_SERVICE);
                if (imm != null) imm.showSoftInput(input, android.view.inputmethod.InputMethodManager.SHOW_IMPLICIT);
            } catch (Throwable ignored) {
            }
        }, 240);
        loadHistory();
        loadBalance();
    }

    private static void closePanel() {
        panelOpen = false;
        AppState.floatingVisible = petView != null;
        try {
            if (panel != null && wm != null) {
                wm.removeView(panel);
            }
        } catch (Throwable ignored) {
        }
        panel = null;
        balanceView = null;
    }

    /** 余额：直接用安卓端 Python 服务已有的 /api/balance（DeepSeek 官方）。 */
    private static void loadBalance() {
        final TextView view = balanceView;
        if (view == null) {
            return;
        }
        view.setText("余额：查询中…");
        new Thread(() -> {
            String text = "余额：暂不可用";
            try {
                String raw = http(BASE + "/api/balance", "GET", null);
                JSONObject obj = new JSONObject(raw);
                if (obj.optBoolean("ok")) {
                    String currency = obj.optString("currency", "");
                    String total = obj.optString("total", "");
                    text = "余额：" + (currency.isEmpty() ? "" : currency + " ") + total;
                } else if ("missing_key".equals(obj.optString("error"))) {
                    text = "余额：还没填 API Key";
                }
            } catch (Throwable ignored) {
            }
            final String out = text;
            UI.post(() -> {
                if (balanceView != null) {
                    balanceView.setText(out);
                }
            });
        }).start();
    }

    private static Typeface petTypeface() {
        if (petFont == null && ctx != null) {
            // 字体只在 seed 里放一份（web/whale/fonts），APK assets 不再重复打包
            try {
                java.io.File file = new java.io.File(
                        ctx.getFilesDir(), "web/whale/fonts/ShangshouSoftCandy.ttf");
                if (file.isFile()) {
                    petFont = Typeface.createFromFile(file);
                }
            } catch (Throwable ignored) {
            }
        }
        return petFont;
    }

    private static void applyPetFont(TextView view) {
        Typeface typeface = petTypeface();
        if (view != null && typeface != null) {
            view.setTypeface(typeface);
        }
    }

    /** 只把最近 8 条装进上下文，不在气泡里显示历史。 */
    private static void loadHistory() {
        new Thread(() -> {
            try {
                String raw = http(BASE + "/api/whale/history?limit=12", "GET", null);
                JSONObject obj = new JSONObject(raw);
                JSONArray arr = obj.optJSONArray("messages");
                JSONArray ctx = new JSONArray();
                if (arr != null) {
                    int from = Math.max(0, arr.length() - 8);
                    for (int i = from; i < arr.length(); i++) {
                        JSONObject m = arr.getJSONObject(i);
                        ctx.put(new JSONObject()
                                .put("role", "her".equals(m.optString("role")) ? "assistant" : "user")
                                .put("content", m.optString("content")));
                    }
                }
                history = ctx;
            } catch (Throwable ignored) {
            }
        }).start();
    }

    private static void askWhale(String text) {
        new Thread(() -> {
            try {
                JSONObject body = new JSONObject();
                body.put("text", text);
                body.put("history", history);
                String raw = http(BASE + "/api/whale/chat", "POST",
                        body.toString().getBytes(StandardCharsets.UTF_8));
                JSONObject obj = new JSONObject(raw);
                if (!obj.optBoolean("ok")) {
                    UI.post(() -> petReply("（没回上来，再说一次）", 0.1, 0.1));
                    return;
                }
                final String reply = obj.optString("text", "咕？");
                final double v = obj.optDouble("valence", 0.2);
                final double a = obj.optDouble("arousal", 0.2);
                history.put(new JSONObject().put("role", "user").put("content", text));
                history.put(new JSONObject().put("role", "assistant").put("content", reply));
                UI.post(() -> petReply(reply, v, a));
            } catch (Throwable t) {
                UI.post(() -> petReply("（连不上本地服务）", 0.1, 0.1));
            }
        }).start();
    }

    private static String http(String url, String method, byte[] body) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(1500);
        conn.setReadTimeout(9000);
        conn.setRequestMethod(method);
        if (body != null) {
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            try (OutputStream out = conn.getOutputStream()) {
                out.write(body);
            }
        }
        int code = conn.getResponseCode();
        InputStream in = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
        StringBuilder sb = new StringBuilder();
        if (in != null) {
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(in, StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    sb.append(line);
                }
            }
        }
        conn.disconnect();
        return sb.toString();
    }

    private static int overlayType() {
        return Build.VERSION.SDK_INT >= 26
                ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                : WindowManager.LayoutParams.TYPE_PHONE;
    }

    private static GradientDrawable round(int color, int radius) {
        GradientDrawable d = new GradientDrawable();
        d.setShape(GradientDrawable.RECTANGLE);
        d.setColor(color);
        d.setCornerRadius(dp(radius));
        return d;
    }

    private static int dp(int value) {
        Context c = ctx != null ? ctx : AppState.context;
        if (c == null) {
            return value * 2;
        }
        return Math.round(TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_DIP, value, c.getResources().getDisplayMetrics()));
    }

    /** 给桌宠页面调用：上报当前帧不透明区域（0~1），用来缩命中框。 */
    private static final class PetBridge {
        @android.webkit.JavascriptInterface
        public void hitBox(double l, double t, double w, double h) {
            UI.post(() -> applyHitBox((float) l, (float) t, (float) w, (float) h));
        }

        @android.webkit.JavascriptInterface
        public void moveBy(int dpX) {
            final int dx = Math.max(-dp(160), Math.min(dp(160), dpX));
            UI.post(() -> walkBy(dx));
        }
    }

    private static void applyHitBox(float l, float t, float w, float h) {
        if (!(l >= 0f) || !(t >= 0f) || !(w > 0f) || !(h > 0f)) {
            return;
        }
        l = Math.max(0f, Math.min(0.96f, l));
        t = Math.max(0f, Math.min(0.96f, t));
        w = Math.max(0.18f, Math.min(1f - l, w));
        h = Math.max(0.22f, Math.min(1f - t, h));
        hitL = l;
        hitT = t;
        hitW = w;
        hitH = h;
        layoutHit();
    }

    private static void layoutHit() {
        if (petHit == null || hitParams == null || petParams == null || wm == null) {
            return;
        }
        int pw = dp(PET_W_DP);
        int ph = dp(PET_H_DP);
        hitParams.width = Math.max(dp(40), Math.round(pw * hitW));
        hitParams.height = Math.max(dp(40), Math.round(ph * hitH));
        hitParams.x = petParams.x + Math.round(pw * hitL);
        hitParams.y = petParams.y + Math.round(ph * hitT);
        try {
            wm.updateViewLayout(petHit, hitParams);
        } catch (Throwable ignored) {
        }
    }

    private static void walkBy(int dpX) {
        if (petView == null || petParams == null || wm == null || ctx == null) {
            return;
        }
        int width = ctx.getResources().getDisplayMetrics().widthPixels;
        int from = petParams.x;
        int to = Math.max(-dp(24), Math.min(width - dp(PET_W_DP) + dp(24), from + dp(dpX)));
        if (to == from) {
            return;
        }
        if (walker != null) {
            walker.cancel();
        }
        final int startX = from;
        final int endX = to;
        android.animation.ValueAnimator anim = android.animation.ValueAnimator.ofFloat(0f, 1f);
        anim.setDuration(2200);
        anim.setInterpolator(new android.view.animation.DecelerateInterpolator());
        anim.addUpdateListener(a -> {
            if (petView == null || petParams == null || wm == null) {
                return;
            }
            float p = (float) a.getAnimatedValue();
            petParams.x = Math.round(startX + (endX - startX) * p);
            try {
                wm.updateViewLayout(petView, petParams);
            } catch (Throwable ignored) {
            }
            layoutHit();
        });
        walker = anim;
        anim.start();
    }

    private static final class PetTouchListener implements View.OnTouchListener {
        private int startX;
        private int startY;
        private float downX;
        private float downY;
        private float lastX;
        private float lastY;
        private long lastMoveAt;
        private float flingX;
        private float flingY;
        private boolean moved;

        @Override
        public boolean onTouch(View v, MotionEvent event) {
            if (petParams == null) {
                return false;
            }
            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    if (walker != null) {
                        walker.cancel();
                        walker = null;
                    }
                    // 手指按住时暂停物理，让她能被拎住，松手再继续飞
                    physicsPaused = gravityOn;
                    startX = petParams.x;
                    startY = petParams.y;
                    downX = event.getRawX();
                    downY = event.getRawY();
                    lastX = downX;
                    lastY = downY;
                    lastMoveAt = SystemClock.uptimeMillis();
                    flingX = 0f;
                    flingY = 0f;
                    moved = false;
                    return true;
                case MotionEvent.ACTION_MOVE: {
                    int dx = (int) (event.getRawX() - downX);
                    int dy = (int) (event.getRawY() - downY);
                    if (Math.abs(dx) > dp(8) || Math.abs(dy) > dp(8)) {
                        moved = true;
                    }
                    if (moved) {
                        long now = SystemClock.uptimeMillis();
                        float span = Math.max(0.001f, (now - lastMoveAt) / 1000f);
                        flingX = (event.getRawX() - lastX) / span;
                        flingY = (event.getRawY() - lastY) / span;
                        lastX = event.getRawX();
                        lastY = event.getRawY();
                        lastMoveAt = now;
                        int sw = ctx.getResources().getDisplayMetrics().widthPixels;
                        int sh = ctx.getResources().getDisplayMetrics().heightPixels;
                        petParams.x = Math.max(-dp(24), Math.min(sw - dp(PET_W_DP) + dp(24), startX + dx));
                        petParams.y = Math.max(0, Math.min(sh - dp(PET_H_DP) + dp(16), startY + dy));
                        physX = petParams.x;
                        physY = petParams.y;
                        try {
                            if (wm != null && petView != null) {
                                wm.updateViewLayout(petView, petParams);
                            }
                        } catch (Throwable ignored) {
                        }
                        layoutHit();
                    }
                    return true;
                }
                case MotionEvent.ACTION_UP:
                    if (!moved) {
                        registerTap();
                    } else if (gravityOn) {
                        // 甩出去的惯性留着，松手后继续滚
                        velX = Math.max(-8000f, Math.min(8000f, flingX));
                        velY = Math.max(-8000f, Math.min(8000f, flingY));
                    }
                    physicsPaused = false;
                    return true;
                case MotionEvent.ACTION_CANCEL:
                    physicsPaused = false;
                    return true;
            }
            return false;
        }
    }

    /** 单击切重力、再点固定；双击打开对话面板（单击要等双击窗口过期才执行）。 */
    private static void registerTap() {
        long now = SystemClock.uptimeMillis();
        if (petView != null) {
            try {
                petView.evaluateJavascript("window.__petTap&&window.__petTap()", null);
            } catch (Throwable ignored) {
            }
        }
        if (pendingSingleTap && now - lastTapAt <= DOUBLE_TAP_MS) {
            pendingSingleTap = false;
            UI.removeCallbacks(SINGLE_TAP_RUN);
            lastTapAt = now;
            openPanel();
            return;
        }
        pendingSingleTap = true;
        lastTapAt = now;
        UI.postDelayed(SINGLE_TAP_RUN, DOUBLE_TAP_MS);
    }

    /* ---------------- 重力物理 ---------------- */

    private static void setGravityMode(boolean on) {
        setGravityMode(on, false);
    }

    private static void setGravityMode(boolean on, boolean quiet) {
        if (on && (petView == null || petParams == null || wm == null || ctx == null)) {
            on = false;
        }
        if (on == gravityOn) {
            return;
        }
        gravityOn = on;
        physicsPaused = false;
        velX = 0f;
        velY = 0f;
        if (on) {
            // 自动走动是原生补间动画，开了物理就把它停掉，免得两边抢位置
            if (walker != null) {
                walker.cancel();
                walker = null;
            }
            physX = petParams.x;
            physY = petParams.y;
            smoothX = 0f;
            smoothY = 0f;
            startSensors();
            lastTickAt = SystemClock.uptimeMillis();
            UI.removeCallbacks(PHYSICS_TICK);
            UI.post(PHYSICS_TICK);
        } else {
            stopPhysicsLoop();
        }
        if (petView != null) {
            try {
                petView.evaluateJavascript(
                        "window.__petGravity&&window.__petGravity(" + (on ? "true" : "false") + ")",
                        null);
            } catch (Throwable ignored) {
            }
        }
        if (!quiet && ctx != null) {
            Toast.makeText(ctx, on ? "重力模式：倾斜或摇晃手机" : "已固定在这里",
                    Toast.LENGTH_SHORT).show();
        }
    }

    private static void stopGravity() {
        gravityOn = false;
        physicsPaused = false;
        velX = 0f;
        velY = 0f;
        stopPhysicsLoop();
    }

    private static void stopPhysicsLoop() {
        UI.removeCallbacks(PHYSICS_TICK);
        stopSensors();
    }

    private static void startSensors() {
        if (ctx == null) {
            return;
        }
        if (sensors == null) {
            sensors = (SensorManager) ctx.getSystemService(Context.SENSOR_SERVICE);
        }
        if (sensors == null || motionListener != null) {
            return;
        }
        motionListener = new SensorEventListener() {
            @Override
            public void onSensorChanged(SensorEvent e) {
                int type = e.sensor.getType();
                if (type == Sensor.TYPE_ACCELEROMETER) {
                    accX = e.values[0];
                    accY = e.values[1];
                    accReady = true;
                } else if (type == Sensor.TYPE_GYROSCOPE) {
                    gyroZ = e.values[2];
                }
            }

            @Override
            public void onAccuracyChanged(Sensor sensor, int accuracy) {
            }
        };
        Sensor acc = sensors.getDefaultSensor(Sensor.TYPE_ACCELEROMETER);
        Sensor gyro = sensors.getDefaultSensor(Sensor.TYPE_GYROSCOPE);
        if (acc != null) {
            sensors.registerListener(motionListener, acc, SensorManager.SENSOR_DELAY_GAME);
        }
        if (gyro != null) {
            sensors.registerListener(motionListener, gyro, SensorManager.SENSOR_DELAY_GAME);
        }
        accReady = false;
    }

    private static void stopSensors() {
        if (sensors != null && motionListener != null) {
            try {
                sensors.unregisterListener(motionListener);
            } catch (Throwable ignored) {
            }
        }
        motionListener = null;
        accReady = false;
    }

    /** 把加速度计/陀螺仪换算成屏幕方向，推着她撞墙反弹。 */
    private static void stepPhysics() {
        long now = SystemClock.uptimeMillis();
        float dt = (now - lastTickAt) / 1000f;
        lastTickAt = now;
        if (dt <= 0f || dt > 0.06f) {
            dt = 0.016f;
        }
        if (physicsPaused || !accReady || ctx == null) {
            return;
        }

        // 加速度计是「设备坐标」，要按当前屏幕旋转映射到屏幕坐标
        float sx;
        float sy;
        int rotation = 0;
        try {
            rotation = wm.getDefaultDisplay().getRotation();
        } catch (Throwable ignored) {
        }
        switch (rotation) {
            case Surface.ROTATION_90:
                sx = -accY;
                sy = -accX;
                break;
            case Surface.ROTATION_180:
                sx = accX;
                sy = -accY;
                break;
            case Surface.ROTATION_270:
                sx = accY;
                sy = accX;
                break;
            default:
                sx = -accX;
                sy = accY;
                break;
        }
        // 按屏幕真实物理尺寸换算：dpi / 0.0254 = 每米多少像素，
        // 这样加速度计读到的 m/s² 直接乘上去就是真实地球重力，不再“轻飘飘”。
        float pxPerMeter = 0f;
        try {
            pxPerMeter = ctx.getResources().getDisplayMetrics().densityDpi * 39.37f;
        } catch (Throwable ignored) {
        }
        if (pxPerMeter <= 0f) {
            pxPerMeter = 6000f;
        }

        // 低通一下滤掉传感器高频噪声；摇晃的大冲击还能透过来
        smoothX = smoothX * 0.72f + sx * 0.28f;
        smoothY = smoothY * 0.72f + sy * 0.28f;

        // 加速度计读数含重力，乘 px/m 就是真实重力加速度（px/s²）；
        // 再乘 0.25：0.5 倍仍偏重，这里再轻一档，落地约 0.45 秒
        float gravityScale = pxPerMeter * 0.25f;
        float forceX = smoothX * gravityScale + (float) Math.toDegrees(gyroZ) * 5f;
        float forceY = smoothY * gravityScale;
        velX += forceX * dt;
        velY += forceY * dt;

        // 真实场景近似没有空气阻力，只留一点点损耗，否则会一直抖个不停
        float damp = (float) Math.pow(0.998f, dt * 60f);
        velX = Math.max(-24000f, Math.min(24000f, velX * damp));
        velY = Math.max(-24000f, Math.min(24000f, velY * damp));

        int pw = dp(PET_W_DP);
        int ph = dp(PET_H_DP);
        int sw = ctx.getResources().getDisplayMetrics().widthPixels;
        int sh = ctx.getResources().getDisplayMetrics().heightPixels;
        float minX = -dp(24);
        float maxX = sw - pw + dp(24);
        float minY = 0f;
        float maxY = Math.max(0f, sh - ph + dp(16));

        // 真实重力一帧能走几百像素，必须切成小步，否则会直接穿墙
        float travel = Math.max(Math.abs(velX), Math.abs(velY)) * dt;
        int steps = Math.max(1, Math.min(10, (int) Math.ceil(travel / 40f)));
        float span = dt / steps;
        for (int i = 0; i < steps; i++) {
            physX += velX * span;
            physY += velY * span;
            if (physX < minX) {
                physX = minX;
                velX = Math.abs(velX) < 600f ? 0f : -velX * 0.5f;
            } else if (physX > maxX) {
                physX = maxX;
                velX = Math.abs(velX) < 600f ? 0f : -velX * 0.5f;
            }
            if (physY < minY) {
                physY = minY;
                velY = Math.abs(velY) < 40f ? 0f : -velY * 0.5f;
            } else if (physY > maxY) {
                // 贴底时把重力每帧加出来的小速度吃掉，否则会一直微微弹跳
                physY = maxY;
                float bounce = -velY * 0.5f;
                velY = Math.abs(bounce) < 600f ? 0f : bounce;
            }
        }

        petParams.x = Math.round(physX);
        petParams.y = Math.round(physY);
        try {
            wm.updateViewLayout(petView, petParams);
        } catch (Throwable ignored) {
        }
        tickFrame += 1;
        if ((tickFrame & 1) == 0) {
            layoutHit();
        }
    }
}
