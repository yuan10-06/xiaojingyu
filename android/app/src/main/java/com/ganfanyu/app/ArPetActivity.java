package com.ganfanyu.app;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.opengl.GLES11Ext;
import android.opengl.GLES20;
import android.opengl.GLSurfaceView;
import android.opengl.Matrix;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Base64;
import android.util.Size;
import android.util.SizeF;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageProxy;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.lifecycle.Lifecycle;
import androidx.lifecycle.LifecycleOwner;
import androidx.lifecycle.LifecycleRegistry;

import com.google.ar.core.Anchor;
import com.google.ar.core.ArCoreApk;
import com.google.ar.core.Camera;
import com.google.ar.core.Coordinates2d;
import com.google.ar.core.Frame;
import com.google.ar.core.HitResult;
import com.google.ar.core.Plane;
import com.google.ar.core.Point;
import com.google.ar.core.Pose;
import com.google.ar.core.Session;
import com.google.ar.core.Trackable;
import com.google.ar.core.TrackingState;
import com.google.ar.core.Config;
import com.google.ar.core.exceptions.CameraNotAvailableException;
import com.google.mlkit.vision.barcode.BarcodeScanner;
import com.google.mlkit.vision.barcode.BarcodeScannerOptions;
import com.google.mlkit.vision.barcode.BarcodeScanning;
import com.google.mlkit.vision.barcode.common.Barcode;
import com.google.mlkit.vision.common.InputImage;
import org.opencv.core.Core;
import org.opencv.core.CvType;
import org.opencv.core.Mat;
import org.opencv.imgproc.Imgproc;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/**
 * AR 桌宠：后置相机看现实，平面锚定后把 2D 小鲸鱼贴在现实里。
 * - 有 ARCore（Google Play Services for AR）时用平面锚定。
 * - 没装/不支持时自动退回 CameraX 的轻量 AR：真实现实画面 + 可摆放的鲸鱼。
 * - 「识别场景」只抓一帧交给本地 Python（G3/M13/M15/M16 都复用），不存原图、不认人脸。
 */
public final class ArPetActivity extends Activity {
    private static final int REQ_CAMERA = 9201;
    private static final String BASE = "http://127.0.0.1:8765";
    private static final String PET_PAGE = BASE + "/whale/pet_overlay.html";
    private static final int PET_W_DP = 250;
    private static final int PET_H_DP = 141;
    private static final float PET_REAL_HEIGHT_M = 0.32f;
    private static final int FRAME_MAX_WIDTH = 960;
    private static final int JPEG_QUALITY = 72;

    private FrameLayout root;
    private FrameLayout surfaceHost;
    private FrameLayout petBox;
    private WebView petWeb;
    private TextView petBubbleNative;
    private Runnable petBubbleHide;
    private LinearLayout topBar;
    private TextView titleView;
    private TextView hintView;
    private TextView lookBtn;
    private View touchLayer;

    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService netExecutor = Executors.newSingleThreadExecutor();
    private final ExecutorService captureExecutor = Executors.newSingleThreadExecutor();
    private final AtomicBoolean layoutQueued = new AtomicBoolean(false);
    private final AtomicBoolean looking = new AtomicBoolean(false);

    private volatile float petX;
    private volatile float petY;
    private volatile float petScale = 0.8f;
    private volatile boolean petVisible;

    private boolean arMode;
    private boolean liteStarted;
    private Session session;
    private GLSurfaceView arView;
    private ArRenderer renderer;
    private int probeTries;
    private boolean installAvailable;
    private boolean installAsked;

    private PreviewView previewView;
    private ProcessCameraProvider cameraProvider;
    private ImageAnalysis analysis;
    private final AtomicBoolean wantFrame = new AtomicBoolean(false);
    private LifecycleOwner cameraOwner;
    private LifecycleRegistry cameraLifecycle;

    // 轻量 AR 的 3D：只用旋转矢量，把鲸鱼锚在一个假想地平面/固定距离上。
    // 平移不跟踪，但转手机时会留在空间里，不再像贴在屏幕上。
    private SensorManager sensorManager;
    private Sensor rotationSensor;
    private final float[] rotMatrix = new float[9];
    private volatile boolean hasRotation;
    private boolean sensorAnchorValid;
    private final float[] sensorAnchor = new float[3];
    private float focalPx;
    private float sensorSmX;
    private float sensorSmY;
    private float sensorSmScale;
    private boolean sensorSmInit;
    private boolean autoPlaced;
    private final float[] worldAnchor = new float[3];
    private boolean worldAnchorValid;
    private float petRotationDeg;

    // 二维码锚定：ML Kit 给四角，把宠物坐标存在二维码的仿射坐标系里。
    private BarcodeScanner qrScanner;
    private final AtomicBoolean qrBusy = new AtomicBoolean(false);
    private long lastQrScanAt;
    private volatile QrTrack qrTrack;
    private boolean qrLocked;
    private float qrA;
    private float qrB;
    private float qrBaseScale;
    private float qrSize0;
    private boolean qrHintShown;

    // 无标记平面跟踪（OpenCV）：优先于二维码/重力。
    private PlaneTracker planeTracker;
    private volatile boolean planeActive;
    private volatile boolean planePending;
    private float planeTapX;
    private float planeTapY;
    private long lastTrackAt;
    private byte[] yPlaneBuffer;
    private byte[] yRowBuffer;
    private final float[] displayRot = new float[9];

    private static final class QrTrack {
        final float[] pts = new float[8];
        long at;
    }

    private volatile String worldSession = "";
    private boolean destroying;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        FloatingOverlay.setArActive(true);
        buildUi();
        enterImmersive();
        main.postDelayed(this::startModes, 80);
    }

    // ------------------------------------------------------------------
    // UI
    // ------------------------------------------------------------------

    private void buildUi() {
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.TRANSPARENT);

        surfaceHost = new FrameLayout(this);
        root.addView(surfaceHost, match());

        petBox = new FrameLayout(this);
        FrameLayout.LayoutParams petLp = new FrameLayout.LayoutParams(dp(PET_W_DP), dp(PET_H_DP));
        petLp.gravity = Gravity.TOP | Gravity.START;
        petBox.setTranslationX(-10000);
        petBox.setAlpha(0f);
        root.addView(petBox, petLp);

        /* AR 里的回复气泡独立放在小鲸鱼上方，避免盖住人物 */
        petBubbleNative = new TextView(this);
        petBubbleNative.setTextColor(0xFF1E4A63);
        petBubbleNative.setTextSize(14);
        petBubbleNative.setLineSpacing(0, 1.2f);
        petBubbleNative.setPadding(dp(12), dp(8), dp(12), dp(8));
        petBubbleNative.setMaxLines(5);
        petBubbleNative.setEllipsize(android.text.TextUtils.TruncateAt.END);
        petBubbleNative.setClickable(false);
        petBubbleNative.setFocusable(false);
        GradientDrawable bubbleBg = new GradientDrawable();
        bubbleBg.setColor(0xF2FFFFFF);
        bubbleBg.setCornerRadius(dp(14));
        petBubbleNative.setBackground(bubbleBg);
        petBubbleNative.setElevation(dp(6));
        petBubbleNative.setVisibility(View.GONE);
        petBubbleNative.setAlpha(0f);
        FrameLayout.LayoutParams bubbleLp = new FrameLayout.LayoutParams(
                dp(260), ViewGroup.LayoutParams.WRAP_CONTENT);
        root.addView(petBubbleNative, bubbleLp);

        petWeb = new WebView(this);
        petWeb.setBackgroundColor(Color.TRANSPARENT);
        petWeb.setLayerType(View.LAYER_TYPE_HARDWARE, null);
        petWeb.setVerticalScrollBarEnabled(false);
        petWeb.setHorizontalScrollBarEnabled(false);
        WebSettings ws = petWeb.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setMediaPlaybackRequiresUserGesture(false);
        petWeb.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                /* AR 页面里让桌宠把所有气泡交给原生层，气泡就不会压在人物身上 */
                view.evaluateJavascript(
                        "window.__petUseNativeBubble&&window.__petUseNativeBubble(true)", null);
            }
        });
        petWeb.addJavascriptInterface(new Object() {
            @android.webkit.JavascriptInterface
            public void look() {
                runOnUiThread(ArPetActivity.this::lookNow);
            }

            @android.webkit.JavascriptInterface
            public void close() {
                runOnUiThread(ArPetActivity.this::finish);
            }

            @android.webkit.JavascriptInterface
            public void tap(float x, float y) {
                runOnUiThread(() -> handleTap(x, y));
            }

            @android.webkit.JavascriptInterface
            public void arSetup() {
                runOnUiThread(() -> {
                    try {
                        ArCoreApk.InstallStatus s = ArCoreApk.getInstance()
                                .requestInstall(ArPetActivity.this, true);
                        android.util.Log.i("GanFanYu", "ARCore requestInstall=" + s);
                    } catch (Throwable t) {
                        android.util.Log.w("GanFanYu", "ARCore requestInstall failed", t);
                    }
                });
            }

            @android.webkit.JavascriptInterface
            public void bubble(String text) {
                runOnUiThread(() -> showPetBubble(text));
            }

            @android.webkit.JavascriptInterface
            public boolean isArCore() {
                return arMode;
            }
        }, "PetNative");
        petBox.addView(petWeb, match());
        petWeb.loadUrl(PET_PAGE);

        touchLayer = new View(this);
        touchLayer.setBackgroundColor(Color.TRANSPARENT);
        touchLayer.setOnTouchListener((v, e) -> {
            if (e.getAction() == MotionEvent.ACTION_UP) {
                handleTap(e.getX(), e.getY());
            }
            return true;
        });
        root.addView(touchLayer, match());

        topBar = new LinearLayout(this);
        topBar.setOrientation(LinearLayout.HORIZONTAL);
        topBar.setGravity(Gravity.CENTER_VERTICAL);
        topBar.setPadding(dp(12), dp(10), dp(12), dp(10));
        TextView exit = pill("‹ 退出", 0xB30A1B2A, 0xFFEAF6FF);
        exit.setOnClickListener(v -> finish());
        topBar.addView(exit);
        TextView title = new TextView(this);
        title.setText("AR 桌宠");
        title.setTextColor(0xFFEAF6FF);
        title.setTextSize(14);
        title.setGravity(Gravity.CENTER);
        titleView = title;
        LinearLayout.LayoutParams titleLp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        topBar.addView(title, titleLp);
        lookBtn = pill("识别场景", 0xCC2F8FA8, 0xFFFFFFFF);
        lookBtn.setOnClickListener(v -> lookNow());
        topBar.addView(lookBtn);
        root.addView(topBar, topParams());

        hintView = new TextView(this);
        hintView.setTextColor(0xFFEAF6FF);
        hintView.setTextSize(12);
        hintView.setGravity(Gravity.CENTER);
        hintView.setPadding(dp(14), dp(7), dp(14), dp(7));
        hintView.setBackground(round(0x8C0A1B2A, dp(18), 0));
        hintView.setOnClickListener(v -> {
            if (installAvailable) {
                requestArInstall();
            }
        });
        FrameLayout.LayoutParams hintLp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        hintLp.gravity = Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL;
        hintLp.bottomMargin = dp(150);
        root.addView(hintView, hintLp);

        root.setOnApplyWindowInsetsListener((v, insets) -> {
            int top = 0;
            int bottom = 0;
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets cut = insets.getInsets(WindowInsets.Type.displayCutout());
                top = cut.top;
                bottom = cut.bottom;
            } else {
                top = insets.getSystemWindowInsetTop();
                bottom = insets.getSystemWindowInsetBottom();
            }
            topBar.setPadding(dp(12), dp(10) + top, dp(12), dp(10));
            return insets;
        });

        setContentView(root);
    }

    private FrameLayout.LayoutParams match() {
        return new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
    }

    private FrameLayout.LayoutParams topParams() {
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.gravity = Gravity.TOP;
        return lp;
    }

    private TextView pill(String text, int bg, int fg) {
        TextView v = new TextView(this);
        v.setText(text);
        v.setTextColor(fg);
        v.setTextSize(13);
        v.setGravity(Gravity.CENTER);
        v.setPadding(dp(14), dp(8), dp(14), dp(8));
        v.setBackground(round(bg, dp(20), 0x33FFFFFF));
        v.setClickable(true);
        return v;
    }

    private GradientDrawable round(int color, int radius, int stroke) {
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(color);
        bg.setCornerRadius(radius);
        if (stroke != 0) {
            bg.setStroke(dp(1), stroke);
        }
        return bg;
    }

    private void enterImmersive() {
        Window w = getWindow();
        w.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (Build.VERSION.SDK_INT >= 30) {
            w.setDecorFitsSystemWindows(false);
            WindowInsetsController ic = w.getInsetsController();
            if (ic != null) {
                ic.hide(WindowInsets.Type.systemBars());
                ic.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        } else {
            w.getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        }
        w.setStatusBarColor(Color.TRANSPARENT);
        w.setNavigationBarColor(Color.TRANSPARENT);
    }

    // ------------------------------------------------------------------
    // 相机权限 / 模式
    // ------------------------------------------------------------------

    private void startModes() {
        if (Build.VERSION.SDK_INT >= 23
                && checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA);
            return;
        }
        startLiteMode();
        main.postDelayed(this::probeArCore, 350);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != REQ_CAMERA) {
            return;
        }
        if (grantResults != null && grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            startModes();
            return;
        }
        Toast.makeText(this, "AR 需要相机权限", Toast.LENGTH_SHORT).show();
        finish();
    }

    private void probeArCore() {
        if (arMode || destroying) {
            return;
        }
        ArCoreApk.Availability a;
        try {
            a = ArCoreApk.getInstance().checkAvailability(this);
        } catch (Throwable t) {
            a = null;
        }
        android.util.Log.i("GanFanYu", "AR availability=" + a);
        if (a == null || a.isTransient()) {
            if (probeTries < 5) {
                probeTries += 1;
                main.postDelayed(this::probeArCore, 400);
            } else {
                setHint(defaultLiteHint());
            }
            return;
        }
        if (a == ArCoreApk.Availability.SUPPORTED_INSTALLED) {
            switchToArCore();
            return;
        }
        if (a.isSupported()) {
            // 中国版 ROM 常见：ARCore 装了，但 GMS 被禁用、没有设备校准档案，
            // 服务会一直返回 APK_TOO_OLD，实际上跑不了。这种情况下不再引导安装。
            boolean playStore = playStoreEnabled()
                    && a == ArCoreApk.Availability.SUPPORTED_NOT_INSTALLED;
            installAvailable = playStore;
            if (playStore) {
                setHint("这台机器支持平面 AR，还没装「AR 支持」· 点这里安装");
            } else {
                setHint(defaultLiteHint());
            }
            return;
        }
        setHint(defaultLiteHint());
    }

    private boolean playStoreEnabled() {
        try {
            android.content.pm.ApplicationInfo ai = getPackageManager()
                    .getApplicationInfo("com.android.vending", 0);
            return ai != null && ai.enabled;
        } catch (Throwable t) {
            return false;
        }
    }

    private void setModeTitle(boolean arCore) {
        if (titleView == null) {
            return;
        }
        if (arCore) {
            titleView.setText("AR 桌宠 · ARCore");
        } else {
            titleView.setText(rotationSensor != null ? "AR 桌宠 · 3D" : "AR 桌宠 · 轻量");
        }
    }

    private void requestArInstall() {
        if (installAsked) {
            return;
        }
        installAsked = true;
        try {
            ArCoreApk.getInstance().requestInstall(this, true);
            setHint("装好「AR 支持」后回来，会自动切到平面锚定");
        } catch (Throwable t) {
            setHint("安装入口打不开，先用轻量 AR");
        }
    }

    private void startLiteMode() {
        if (liteStarted || arMode) {
            return;
        }
        liteStarted = true;
        previewView = new PreviewView(this);
        previewView.setImplementationMode(PreviewView.ImplementationMode.COMPATIBLE);
        previewView.setScaleType(PreviewView.ScaleType.FILL_CENTER);
        surfaceHost.addView(previewView, match());
        setupCameraLifecycle();
        setupQrScanner();
        setupSensors();
        setupPlaneTracker();
        bindLiteCamera();
        setModeTitle(false);
        setHint(defaultLiteHint());
        root.post(() -> {
            computeFocalPx();
            main.postDelayed(this::autoPlacePet, 650);
        });
    }

    private String defaultLiteHint() {
        return rotationSensor != null
                ? "重力锁定 · 转手机她会留在原处，点画面换位置"
                : "轻量 AR · 点画面把她放到想放的位置";
    }

    private boolean sensorsRegistered;

    private void setupSensors() {
        if (sensorsRegistered) {
            return;
        }
        try {
            if (sensorManager == null) {
                sensorManager = (SensorManager) getSystemService(SENSOR_SERVICE);
            }
            if (rotationSensor == null && sensorManager != null) {
                rotationSensor = sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR);
            }
            if (rotationSensor != null) {
                sensorManager.registerListener(rotationListener, rotationSensor,
                        SensorManager.SENSOR_DELAY_GAME);
                sensorsRegistered = true;
            }
        } catch (Throwable t) {
            rotationSensor = null;
        }
    }

    private void stopSensors() {
        try {
            if (sensorManager != null && sensorsRegistered) {
                sensorManager.unregisterListener(rotationListener);
            }
        } catch (Throwable ignored) {
        }
        sensorsRegistered = false;
    }

    private final SensorEventListener rotationListener = new SensorEventListener() {
        @Override
        public void onSensorChanged(SensorEvent event) {
            if (event.sensor.getType() != Sensor.TYPE_ROTATION_VECTOR || event.values.length < 3) {
                return;
            }
            try {
                SensorManager.getRotationMatrixFromVector(rotMatrix, event.values);
                hasRotation = true;
            } catch (Throwable ignored) {
                return;
            }
            if (qrLocked) {
                if (qrTrack != null && SystemClock.elapsedRealtime() - qrTrack.at > 1300) {
                    fallbackToSensor();
                }
                return;
            }
            if (planeActive || planePending) {
                return;
            }
            if (sensorAnchorValid) {
                projectSensorAnchor();
            } else if (!autoPlaced) {
                autoPlaced = true;
                float w = root == null ? 0 : root.getWidth();
                float h = root == null ? 0 : root.getHeight();
                if (w > 0 && h > 0) {
                    placePetLite(w * 0.5f, h * 0.68f, false);
                }
            }
        }

        @Override
        public void onAccuracyChanged(Sensor sensor, int accuracy) {
        }
    };

    private void setupQrScanner() {
        try {
            qrScanner = BarcodeScanning.getClient(new BarcodeScannerOptions.Builder()
                    .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                    .build());
        } catch (Throwable t) {
            qrScanner = null;
        }
    }

    private void setupPlaneTracker() {
        if (planeTracker != null) {
            return;
        }
        planeTracker = new PlaneTracker(new PlaneTracker.Listener() {
            @Override
            public void onInitResult(boolean ok) {
                handlePlaneInit(ok);
            }

            @Override
            public void onTrack(float x, float y, float scale, boolean visible) {
                if (planeActive) {
                    // 30fps 下再做一点平滑，去掉单帧抖动
                    applyScreenAnchor(x, y, scale, visible, false);
                }
            }

            @Override
            public void onLost() {
                handlePlaneLost();
            }
        });
        android.util.Log.i("GanFanYu", "OpenCV plane tracker=" + planeTracker.isAvailable());
    }

    private void handlePlaneInit(boolean ok) {
        planePending = false;
        if (ok) {
            planeActive = true;
            qrLocked = false;
            sensorAnchorValid = false;
            sensorSmInit = true;
            setHint("已锁定桌面 · 转手机/走两步都跟住");
            return;
        }
        planeActive = false;
        android.util.Log.i("GanFanYu", "plane init failed, fallback");
        QrTrack t = qrTrack;
        if (t != null && SystemClock.elapsedRealtime() - t.at < 1000) {
            placeOnQr(t, planeTapX, planeTapY);
            return;
        }
        if (hasRotation) {
            placeSensorAnchor(planeTapX, planeTapY);
            setHint("这块桌面特征太少 · 已用重力锁定");
            return;
        }
        fallbackScreenPlace(planeTapX, planeTapY);
        setHint("这块桌面特征太少 · 已用屏幕放置");
    }

    private void handlePlaneLost() {
        if (!planeActive) {
            return;
        }
        planeActive = false;
        if (hasRotation && petVisible && petScale > 0.01f) {
            float dist = 0.48f / petScale;
            dist = Math.max(0.3f, Math.min(6f, dist));
            sensorAnchorAtScreen(petX, petY, dist);
            sensorSmInit = false;
            projectSensorAnchor(true);
            setHint("跟踪丢了 · 已切回重力锁定");
        } else {
            setHint("跟踪丢了");
        }
    }

    private void computeFocalPx() {
        float longSide = root == null ? 0f : Math.max(root.getWidth(), root.getHeight());
        if (longSide <= 0) {
            return;
        }
        float fallback = longSide * 0.82f;
        try {
            CameraManager cm = (CameraManager) getSystemService(CAMERA_SERVICE);
            if (cm == null) {
                focalPx = fallback;
                return;
            }
            for (String id : cm.getCameraIdList()) {
                CameraCharacteristics ch = cm.getCameraCharacteristics(id);
                Integer facing = ch.get(CameraCharacteristics.LENS_FACING);
                if (facing == null || facing != CameraCharacteristics.LENS_FACING_BACK) {
                    continue;
                }
                float[] focals = ch.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS);
                SizeF physical = ch.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE);
                if (focals != null && focals.length > 0 && physical != null
                        && physical.getWidth() > 0) {
                    focalPx = longSide * focals[0] / physical.getWidth();
                    return;
                }
            }
        } catch (Throwable ignored) {
        }
        focalPx = fallback;
    }

    private void setupCameraLifecycle() {
        cameraOwner = new LifecycleOwner() {
            private final LifecycleRegistry registry = new LifecycleRegistry(this);

            @NonNull
            @Override
            public Lifecycle getLifecycle() {
                return registry;
            }
        };
        cameraLifecycle = (LifecycleRegistry) cameraOwner.getLifecycle();
        cameraLifecycle.setCurrentState(Lifecycle.State.RESUMED);
    }

    private void bindLiteCamera() {
        if (previewView == null) {
            return;
        }
        try {
            ProcessCameraProvider.getInstance(this).addListener(() -> {
                try {
                    cameraProvider = ProcessCameraProvider.getInstance(this).get();
                    Preview preview = new Preview.Builder()
                            .setTargetResolution(new Size(1280, 960))
                            .setTargetRotation(displayRotation())
                            .build();
                    preview.setSurfaceProvider(previewView.getSurfaceProvider());
                    analysis = new ImageAnalysis.Builder()
                            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                            .setTargetResolution(new Size(1280, 960))
                            .setTargetRotation(displayRotation())
                            .build();
                    analysis.setAnalyzer(captureExecutor, this::analyzeLite);
                    cameraProvider.bindToLifecycle(
                            cameraOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis);
                } catch (Throwable t) {
                    Toast.makeText(this, "相机没起来，稍后再试", Toast.LENGTH_SHORT).show();
                }
            }, main::post);
        } catch (Throwable t) {
            Toast.makeText(this, "相机没起来，稍后再试", Toast.LENGTH_SHORT).show();
        }
    }

    private void unbindLiteCamera() {
        try {
            if (analysis != null) {
                analysis.clearAnalyzer();
            }
        } catch (Throwable ignored) {
        }
        analysis = null;
        try {
            if (cameraProvider != null) {
                cameraProvider.unbindAll();
            }
        } catch (Throwable ignored) {
        }
    }

    private void switchToArCore() {
        if (arMode || destroying) {
            return;
        }
        unbindLiteCamera();
        if (cameraLifecycle != null) {
            cameraLifecycle.setCurrentState(Lifecycle.State.CREATED);
        }
        if (planeTracker != null) {
            planeTracker.reset();
        }
        planeActive = false;
        planePending = false;
        if (previewView != null) {
            surfaceHost.removeView(previewView);
            previewView = null;
        }
        hidePet();
        try {
            Session s = new Session(this);
            Config config = new Config(s);
            config.setPlaneFindingMode(Config.PlaneFindingMode.HORIZONTAL_AND_VERTICAL);
            config.setUpdateMode(Config.UpdateMode.LATEST_CAMERA_IMAGE);
            config.setFocusMode(Config.FocusMode.AUTO);
            config.setLightEstimationMode(Config.LightEstimationMode.DISABLED);
            s.configure(config);

            arView = new GLSurfaceView(this);
            arView.setEGLContextClientVersion(2);
            arView.setPreserveEGLContextOnPause(true);
            arView.setEGLConfigChooser(8, 8, 8, 8, 16, 0);
            renderer = new ArRenderer(s, this);
            arView.setRenderer(renderer);
            arView.setRenderMode(GLSurfaceView.RENDERMODE_CONTINUOUSLY);
            surfaceHost.addView(arView, 0, match());

            session = s;
            arMode = true;
            installAvailable = false;
            s.resume();
            arView.onResume();
            setModeTitle(true);
            setHint("慢慢移动手机找平面，点一下画面让她落地");
        } catch (Throwable t) {
            android.util.Log.w("GanFanYu", "ARCore start failed", t);
            session = null;
            if (arView != null) {
                surfaceHost.removeView(arView);
                arView = null;
            }
            renderer = null;
            arMode = false;
            liteStarted = false;
            startLiteMode();
            setHint("ARCore 没起来，已退回轻量 AR");
        }
    }

    private int displayRotation() {
        try {
            return getWindowManager().getDefaultDisplay().getRotation();
        } catch (Throwable t) {
            return 0;
        }
    }

    private float petBaseHeightPx() {
        int h = petBox == null ? 0 : petBox.getHeight();
        return h > 0 ? h : dp(PET_H_DP);
    }

    // ------------------------------------------------------------------
    // 生命周期
    // ------------------------------------------------------------------

    @Override
    protected void onResume() {
        super.onResume();
        if (arMode) {
            try {
                if (session != null) {
                    session.resume();
                }
            } catch (Throwable ignored) {
            }
            if (arView != null) {
                arView.onResume();
            }
        } else if (liteStarted) {
            if (cameraLifecycle != null) {
                cameraLifecycle.setCurrentState(Lifecycle.State.RESUMED);
            }
            bindLiteCamera();
            setupSensors();
        }
        if (petWeb != null) {
            petWeb.onResume();
        }
        if (!arMode) {
            main.postDelayed(this::probeArCore, 400);
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (arView != null) {
            arView.onPause();
        }
        try {
            if (session != null) {
                session.pause();
            }
        } catch (Throwable ignored) {
        }
        unbindLiteCamera();
        stopSensors();
        if (planeTracker != null) {
            planeTracker.reset();
        }
        planeActive = false;
        planePending = false;
        if (cameraLifecycle != null && cameraLifecycle.getCurrentState().isAtLeast(Lifecycle.State.CREATED)) {
            cameraLifecycle.setCurrentState(Lifecycle.State.CREATED);
        }
        if (petWeb != null) {
            petWeb.onPause();
        }
    }

    @Override
    public void onConfigurationChanged(@NonNull Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        if (root != null) {
            root.postDelayed(this::handleDisplayRotation, 100);
        } else {
            handleDisplayRotation();
        }
    }

    /** 横竖屏切换：重绑相机（新的 targetRotation），重置平面跟踪并把宠物留在原处。 */
    private void handleDisplayRotation() {
        if (destroying || arMode || !liteStarted || root == null) {
            return;
        }
        float w = root.getWidth();
        float h = root.getHeight();
        if (w <= 0 || h <= 0) {
            root.postDelayed(this::handleDisplayRotation, 220);
            return;
        }
        float[] carried = null;
        if (petVisible && hasRotation && worldAnchorValid) {
            carried = projectWorldAnchor(worldAnchor, displayRotationMatrix(), w, h);
        }
        computeFocalPx();
        if (planeTracker != null) {
            planeTracker.reset();
        }
        planeActive = false;
        planePending = false;
        qrLocked = false;
        qrHintShown = false;
        sensorAnchorValid = false;
        sensorSmInit = false;
        unbindLiteCamera();
        bindLiteCamera();
        if (carried != null) {
            applyScreenAnchor(carried[0], carried[1], carried[2], true, true);
            if (planeTracker != null && planeTracker.isAvailable()) {
                planeTapX = carried[0];
                planeTapY = carried[1];
                planePending = true;
                planeTracker.requestInit(carried[0], carried[1], (int) w, (int) h, carried[2]);
                setHint("已切屏 · 她还在原来的位置，转手机也不会倒");
            } else {
                setHint("已切屏 · 她还在原来的位置");
            }
            return;
        }
        if (hasRotation) {
            placeSensorAnchor(w * 0.5f, h * 0.62f);
        } else {
            fallbackScreenPlace(w * 0.5f, h * 0.62f);
        }
        setHint("已切屏 · 点画面可重新锁定桌面，转手机她也不会倒");
    }

    @Override
    protected void onDestroy() {
        destroying = true;
        FloatingOverlay.setArActive(false);
        try {
            if (petWeb != null) {
                petWeb.loadUrl("about:blank");
                petBox.removeView(petWeb);
                petWeb.destroy();
                petWeb = null;
            }
        } catch (Throwable ignored) {
        }
        try {
            if (renderer != null) {
                renderer.releaseAnchor();
            }
        } catch (Throwable ignored) {
        }
        try {
            if (session != null) {
                session.close();
                session = null;
            }
        } catch (Throwable ignored) {
        }
        unbindLiteCamera();
        stopSensors();
        if (planeTracker != null) {
            planeTracker.reset();
            planeTracker = null;
        }
        planeActive = false;
        planePending = false;
        if (qrScanner != null) {
            try {
                qrScanner.close();
            } catch (Throwable ignored) {
            }
            qrScanner = null;
        }
        if (cameraLifecycle != null) {
            cameraLifecycle.setCurrentState(Lifecycle.State.DESTROYED);
        }
        final String sid = worldSession;
        netExecutor.execute(() -> stopWorldSession(sid));
        netExecutor.shutdown();
        captureExecutor.shutdownNow();
        super.onDestroy();
    }

    @Override
    public void onBackPressed() {
        finish();
    }

    // ------------------------------------------------------------------
    // 摆放 / 触摸
    // ------------------------------------------------------------------

    private void handleTap(float x, float y) {
        if (petVisible && petBox != null) {
            float dx = x - petX;
            float dy = y - petY;
            float rad = (float) Math.toRadians(petRotationDeg);
            float cos = (float) Math.cos(rad);
            float sin = (float) Math.sin(rad);
            float lx = dx * cos + dy * sin;
            float ly = -dx * sin + dy * cos;
            float halfW = petBox.getWidth() * 0.5f;
            float h = petBox.getHeight();
            if (Math.abs(lx) <= halfW && ly <= 0 && ly >= -h) {
                try {
                    petWeb.evaluateJavascript("window.__petTap&&window.__petTap()", null);
                } catch (Throwable ignored) {
                }
                return;
            }
        }
        if (arMode) {
            if (renderer != null) {
                renderer.requestTap(x, y);
            }
            setHint("正在找平面…");
            return;
        }
        placePetLite(x, y);
    }

    private void autoPlacePet() {
        if (arMode || petVisible || qrLocked || root == null) {
            return;
        }
        if (root.getWidth() <= 0 || root.getHeight() <= 0) {
            return;
        }
        autoPlaced = true;
        placePetLite(root.getWidth() * 0.5f, root.getHeight() * 0.68f, false, false);
    }

    private void placePetLite(float x, float y) {
        placePetLite(x, y, true, true);
    }

    private void placePetLite(float x, float y, boolean allowQr) {
        placePetLite(x, y, allowQr, false);
    }

    private void placePetLite(float x, float y, boolean allowQr, boolean allowPlane) {
        if (root == null) {
            return;
        }
        float w = root.getWidth();
        float h = root.getHeight();
        if (w <= 0 || h <= 0) {
            return;
        }
        worldAnchorValid = false;
        if (allowPlane && planeTracker != null && planeTracker.isAvailable()) {
            planeTapX = x;
            planeTapY = y;
            planePending = true;
            planeActive = false;
            qrLocked = false;
            sensorAnchorValid = false;
            sensorSmInit = true;
            autoPlaced = true;
            setPetScreen(x, y, 0.8f, true);
            planeTracker.requestInit(x, y, (int) w, (int) h, 0.8f);
            setHint("正在锁定这块桌面…");
            return;
        }
        QrTrack t = qrTrack;
        if (allowQr && t != null && SystemClock.elapsedRealtime() - t.at < 1000) {
            placeOnQr(t, x, y);
            return;
        }
        if (hasRotation) {
            placeSensorAnchor(x, y);
            return;
        }
        fallbackScreenPlace(x, y);
    }

    private void fallbackScreenPlace(float x, float y) {
        if (root == null) {
            return;
        }
        float w = root.getWidth();
        float h = root.getHeight();
        if (w <= 0 || h <= 0) {
            return;
        }
        float marginX = dp(24);
        float marginTop = dp(90);
        float marginBottom = dp(110);
        petScale = 0.8f;
        sensorSmInit = false;
        applyScreenAnchor(
                Math.max(marginX, Math.min(w - marginX, x)),
                Math.max(marginTop, Math.min(h - marginBottom, y)),
                0.8f, true, true);
        setHint("已放下 · 再点画面可以挪位置");
    }

    private void placeOnQr(QrTrack t, float x, float y) {
        float[] p = t.pts;
        float cx = (p[0] + p[2] + p[4] + p[6]) * 0.25f;
        float cy = (p[1] + p[3] + p[5] + p[7]) * 0.25f;
        float rx = p[2] - p[0];
        float ry = p[3] - p[1];
        float dx = p[6] - p[0];
        float dy = p[7] - p[1];
        float det = rx * dy - ry * dx;
        if (Math.abs(det) < 1e-3f) {
            placeSensorAnchor(x, y);
            return;
        }
        qrA = ((x - cx) * dy - (y - cy) * dx) / det;
        qrB = (rx * (y - cy) - ry * (x - cx)) / det;
        qrSize0 = Math.max(1f, (float) Math.hypot(rx, ry) + (float) Math.hypot(dx, dy));
        // 让她的屏幕大小和二维码的远近大致成比例
        qrBaseScale = Math.max(0.3f, Math.min(1.6f, qrSize0 / 420f));
        qrLocked = true;
        qrHintShown = true;
        sensorAnchorValid = false;
        sensorSmInit = false;
        autoPlaced = true;
        applyQrTrack(t, true);
        setHint("已锁定二维码 · 她在码旁边，走两步也不掉");
        main.postDelayed(this::checkQrStale, 1600);
    }

    private void applyQrTrack(QrTrack t, boolean immediate) {
        if (root == null) {
            return;
        }
        float[] p = t.pts;
        float cx = (p[0] + p[2] + p[4] + p[6]) * 0.25f;
        float cy = (p[1] + p[3] + p[5] + p[7]) * 0.25f;
        float rx = p[2] - p[0];
        float ry = p[3] - p[1];
        float dx = p[6] - p[0];
        float dy = p[7] - p[1];
        float size = (float) Math.hypot(rx, ry) + (float) Math.hypot(dx, dy);
        float x = cx + qrA * rx + qrB * dx;
        float y = cy + qrA * ry + qrB * dy;
        float scale = qrBaseScale * size / Math.max(1f, qrSize0);
        scale = Math.max(0.22f, Math.min(1.8f, scale));
        float w = root.getWidth();
        float h = root.getHeight();
        boolean visible = x > -w * 0.25f && x < w * 1.25f && y > -h * 0.2f && y < h * 1.2f;
        applyScreenAnchor(x, y, scale, visible, immediate);
    }

    private void checkQrStale() {
        if (!qrLocked) {
            return;
        }
        if (qrTrack == null || SystemClock.elapsedRealtime() - qrTrack.at > 1600) {
            fallbackToSensor();
            return;
        }
        main.postDelayed(this::checkQrStale, 700);
    }

    /** 二维码离开画面：用当前屏幕位置反推一个固定距离锚点，切回重力锁定，避免她突然消失。 */
    private void fallbackToSensor() {
        if (!qrLocked) {
            return;
        }
        qrLocked = false;
        qrHintShown = false;
        if (hasRotation && petVisible && petScale > 0.01f) {
            float dist = 0.48f / petScale;
            dist = Math.max(0.3f, Math.min(6f, dist));
            sensorAnchorAtScreen(petX, petY, dist);
            sensorSmInit = false;
            projectSensorAnchor(true);
            setHint("二维码离开了 · 已切回重力锁定");
        } else {
            setHint("二维码离开了");
        }
    }

    /** 以相机为原点、把点击点投到“桌面高度”的假想地平面。 */
    private void placeSensorAnchor(float x, float y) {
        if (!hasRotation || root == null) {
            return;
        }
        if (focalPx <= 0 && root.getHeight() > 0) {
            focalPx = root.getHeight() * 0.82f;
        }
        float[] dir = screenRayToWorld(x, y);
        if (dir == null) {
            return;
        }
        float t;
        if (dir[2] < -0.05f) {
            t = 0.35f / (-dir[2]);
        } else {
            t = 1.2f;
        }
        t = Math.max(0.25f, Math.min(7f, t));
        sensorAnchor[0] = dir[0] * t;
        sensorAnchor[1] = dir[1] * t;
        sensorAnchor[2] = dir[2] * t;
        sensorAnchorValid = true;
        qrLocked = false;
        sensorSmInit = false;
        autoPlaced = true;
        android.util.Log.d("GanFanYu", String.format(Locale.US,
                "sensor anchor %.2f,%.2f,%.2f dirZ=%.2f", sensorAnchor[0], sensorAnchor[1],
                sensorAnchor[2], dir[2]));
        projectSensorAnchor(true);
        setHint("已放下 · 转手机她会留在原处（走远会漂）");
    }

    private void sensorAnchorAtScreen(float x, float y, float dist) {
        float[] dir = screenRayToWorld(x, y);
        if (dir == null) {
            return;
        }
        sensorAnchor[0] = dir[0] * dist;
        sensorAnchor[1] = dir[1] * dist;
        sensorAnchor[2] = dir[2] * dist;
        sensorAnchorValid = true;
        autoPlaced = true;
    }

    /** 屏幕方向对应的旋转矩阵：横屏时把设备坐标重映射到显示坐标。 */
    private float[] displayRotationMatrix() {
        int rotation = displayRotation();
        if (rotation == Surface.ROTATION_0) {
            return rotMatrix;
        }
        int axisX;
        int axisY;
        if (rotation == Surface.ROTATION_90) {
            axisX = SensorManager.AXIS_Y;
            axisY = SensorManager.AXIS_MINUS_X;
        } else if (rotation == Surface.ROTATION_180) {
            axisX = SensorManager.AXIS_MINUS_X;
            axisY = SensorManager.AXIS_MINUS_Y;
        } else if (rotation == Surface.ROTATION_270) {
            axisX = SensorManager.AXIS_MINUS_Y;
            axisY = SensorManager.AXIS_X;
        } else {
            return rotMatrix;
        }
        try {
            SensorManager.remapCoordinateSystem(rotMatrix, axisX, axisY, displayRot);
            return displayRot;
        } catch (Throwable t) {
            return rotMatrix;
        }
    }

    /** 屏幕点 → 设备坐标射线 → 世界坐标方向（ENU，z 向上）。 */
    private float[] screenRayToWorld(float x, float y) {
        if (root == null || !hasRotation) {
            return null;
        }
        float w = root.getWidth();
        float h = root.getHeight();
        if (w <= 0 || h <= 0) {
            return null;
        }
        float f = focalPx > 0 ? focalPx : Math.max(w, h) * 0.82f;
        float u = (x - w * 0.5f) / f;
        float v = -(y - h * 0.5f) / f;
        float len = (float) Math.sqrt(u * u + v * v + 1f);
        float dx = u / len;
        float dy = v / len;
        float dz = -1f / len;
        float[] R = displayRotationMatrix();
        float dwx = R[0] * dx + R[1] * dy + R[2] * dz;
        float dwy = R[3] * dx + R[4] * dy + R[5] * dz;
        float dwz = R[6] * dx + R[7] * dy + R[8] * dz;
        return new float[]{dwx, dwy, dwz};
    }

    private void projectSensorAnchor() {
        projectSensorAnchor(false);
    }

    private void projectSensorAnchor(boolean immediate) {
        if (!sensorAnchorValid || !hasRotation || qrLocked || root == null) {
            return;
        }
        float w = root.getWidth();
        float h = root.getHeight();
        if (w <= 0 || h <= 0) {
            return;
        }
        float ax = sensorAnchor[0];
        float ay = sensorAnchor[1];
        float az = sensorAnchor[2];
        float[] R = displayRotationMatrix();
        float cx = R[0] * ax + R[3] * ay + R[6] * az;
        float cy = R[1] * ax + R[4] * ay + R[7] * az;
        float cz = R[2] * ax + R[5] * ay + R[8] * az;
        if (cz > -0.05f) {
            setPetScreen(0f, 0f, 1f, false);
            return;
        }
        float f = focalPx > 0 ? focalPx : Math.max(w, h) * 0.82f;
        float sx = w * 0.5f + f * (cx / -cz);
        float sy = h * 0.5f - f * (cy / -cz);
        float dist = (float) Math.sqrt(ax * ax + ay * ay + az * az);
        float scale = 0.48f / Math.max(0.2f, dist);
        scale = Math.max(0.22f, Math.min(1.8f, scale));
        boolean visible = sx > -w * 0.3f && sx < w * 1.3f && sy > -h * 0.25f && sy < h * 1.25f;
        applyScreenAnchor(sx, sy, scale, visible, immediate);
    }

    private void applyScreenAnchor(float x, float y, float scale, boolean visible, boolean immediate) {
        if (!immediate && sensorSmInit) {
            /* 自适应平滑：慢速时压抖动，快速挥动时更跟手 */
            float dx = x - sensorSmX;
            float dy = y - sensorSmY;
            float dist = (float) Math.sqrt(dx * dx + dy * dy);
            float alpha = dist > 46f ? 0.78f : 0.44f;
            x = sensorSmX + dx * alpha;
            y = sensorSmY + dy * alpha;
            scale = sensorSmScale + (scale - sensorSmScale) * alpha;
        }
        sensorSmX = x;
        sensorSmY = y;
        sensorSmScale = scale;
        sensorSmInit = true;
        if (planeActive || qrLocked || sensorAnchorValid) {
            storeWorldAnchor(x, y, scale);
        }
        setPetScreen(x, y, scale, visible);
    }

    /** 把当前屏幕位置反推成世界方向上的锚点，转屏时用它把宠物留在原处。 */
    private void storeWorldAnchor(float x, float y, float scale) {
        if (!hasRotation || root == null) {
            return;
        }
        float w = root.getWidth();
        float h = root.getHeight();
        if (w <= 0 || h <= 0) {
            return;
        }
        float f = focalPx > 0 ? focalPx : Math.max(w, h) * 0.82f;
        float u = (x - w * 0.5f) / f;
        float v = -(y - h * 0.5f) / f;
        float len = (float) Math.sqrt(u * u + v * v + 1f);
        float dx = u / len;
        float dy = v / len;
        float dz = -1f / len;
        float[] R = displayRotationMatrix();
        float wx = R[0] * dx + R[1] * dy + R[2] * dz;
        float wy = R[3] * dx + R[4] * dy + R[5] * dz;
        float wz = R[6] * dx + R[7] * dy + R[8] * dz;
        float dist = 0.48f / Math.max(0.15f, scale);
        dist = Math.max(0.25f, Math.min(7f, dist));
        worldAnchor[0] = wx * dist;
        worldAnchor[1] = wy * dist;
        worldAnchor[2] = wz * dist;
        worldAnchorValid = true;
    }

    /** 世界锚点 → 当前屏幕坐标；相机背后返回 null。 */
    private float[] projectWorldAnchor(float[] a, float[] R, float w, float h) {
        float cx = R[0] * a[0] + R[3] * a[1] + R[6] * a[2];
        float cy = R[1] * a[0] + R[4] * a[1] + R[7] * a[2];
        float cz = R[2] * a[0] + R[5] * a[1] + R[8] * a[2];
        if (cz > -0.05f) {
            return null;
        }
        float f = focalPx > 0 ? focalPx : Math.max(w, h) * 0.82f;
        float sx = w * 0.5f + f * (cx / -cz);
        float sy = h * 0.5f - f * (cy / -cz);
        float dist = (float) Math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
        float scale = 0.48f / Math.max(0.2f, dist);
        scale = Math.max(0.22f, Math.min(1.8f, scale));
        return new float[]{sx, sy, scale};
    }

    /** 世界竖直方向在屏幕上的角度（只取 90° 的整数倍，横竖屏稳定不抖）。 */
    private float worldUprightDegrees() {
        if (!hasRotation) {
            return 0f;
        }
        float[] R = displayRotationMatrix();
        float deg = (float) Math.toDegrees(Math.atan2(R[6], R[7]));
        return Math.round(deg / 90f) * 90f;
    }

    private void setPetScreen(float x, float y, float scale, boolean visible) {
        petX = x;
        petY = y;
        petScale = scale;
        petVisible = visible;
        if (layoutQueued.compareAndSet(false, true)) {
            main.post(this::applyPetPosition);
        }
    }

    private void hidePet() {
        petVisible = false;
        applyPetPosition();
    }

    /**
     * GL 线程每帧算完锚点后回传屏幕坐标；只保留一次待处理的 UI 更新，避免刷屏。
     */
    void onPetProjected(float x, float y, float scale, boolean visible) {
        setPetScreen(x, y, scale, visible);
    }

    private void applyPetPosition() {
        layoutQueued.set(false);
        if (petBox == null) {
            return;
        }
        petBox.setAlpha(petVisible ? 1f : 0f);
        petBox.setClickable(false);
        if (!petVisible) {
            hidePetBubble();
            return;
        }
        int w = petBox.getWidth();
        int h = petBox.getHeight();
        if (w <= 0 || h <= 0) {
            petBox.post(this::applyPetPosition);
            return;
        }
        petBox.setPivotX(w * 0.5f);
        petBox.setPivotY(h);
        petRotationDeg = worldUprightDegrees();
        petBox.setRotation(petRotationDeg);
        petBox.setScaleX(petScale);
        petBox.setScaleY(petScale);
        petBox.setTranslationX(petX - w * 0.5f);
        petBox.setTranslationY(petY - h);
        positionPetBubble();
    }

    // ------------------------------------------------------------------
    // ARCore 回调（GL 线程）
    // ------------------------------------------------------------------

    void onAnchorPlaced() {
        main.post(() -> setHint("已落地 · 点画面可以换位置，点「识别场景」让我看看外面"));
    }

    void onAnchorMissed() {
        main.post(() -> setHint("还没找到平面，慢慢移动手机再点一下"));
    }

    void onTracking(boolean ok) {
        if (!ok) {
            main.post(() -> setHint("镜头没跟上，慢一点移动手机"));
        }
    }

    void onArCameraLost() {
        main.post(() -> Toast.makeText(this, "AR 相机被占用，稍后再试", Toast.LENGTH_SHORT).show());
    }

    // ------------------------------------------------------------------
    // 识别场景：抓一帧 → 本地 Python（G3/M13/M15/M16）
    // ------------------------------------------------------------------

    private void lookNow() {
        if (!looking.compareAndSet(false, true)) {
            return;
        }
        if (lookBtn != null) {
            lookBtn.setAlpha(0.55f);
        }
        if (arMode) {
            captureAr();
        } else {
            captureLite();
        }
        main.postDelayed(() -> {
            if (looking.get()) {
                wantFrame.set(false);
                finishLook("她这次没回应，再试一次");
            }
        }, 70000);
    }

    private void captureAr() {
        if (Build.VERSION.SDK_INT < 26 || arView == null) {
            finishLook("这个系统版本暂时抓不了帧");
            return;
        }
        int w = arView.getWidth();
        int h = arView.getHeight();
        if (w <= 0 || h <= 0) {
            finishLook("相机还没准备好");
            return;
        }
        final Bitmap bitmap;
        try {
            bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
        } catch (Throwable t) {
            finishLook("相机还没准备好");
            return;
        }
        try {
            android.view.PixelCopy.request(arView, bitmap, result -> {
                if (result == android.view.PixelCopy.SUCCESS) {
                    sendFrameAsync(bitmap);
                } else {
                    bitmap.recycle();
                    finishLook("这一帧没抓到，再试一次");
                }
            }, main);
        } catch (Throwable t) {
            bitmap.recycle();
            finishLook("这一帧没抓到，再试一次");
        }
    }

    private void captureLite() {
        if (analysis == null) {
            finishLook("相机还没准备好");
            return;
        }
        wantFrame.set(true);
    }

    /** CameraX 分析线程：平面跟踪直接读 Y 平面，不再每帧 toBitmap。 */
    private void analyzeLite(@NonNull ImageProxy image) {
        boolean snapshot = wantFrame.compareAndSet(true, false) && looking.get();
        if (snapshot) {
            int rotation = 0;
            Bitmap bitmap;
            try {
                rotation = image.getImageInfo().getRotationDegrees();
                bitmap = image.toBitmap();
            } catch (Throwable t) {
                bitmap = null;
            } finally {
                image.close();
            }
            if (bitmap == null) {
                finishLook("这一帧没抓到，再试一次");
                return;
            }
            Bitmap upright = rotate(bitmap, rotation);
            if (upright != bitmap) {
                bitmap.recycle();
            }
            sendFrameAsync(upright);
            return;
        }

        long now = SystemClock.elapsedRealtime();
        boolean track = planeTracker != null && (planeActive || planePending)
                && now - lastTrackAt >= 30;
        boolean qr = qrScanner != null && !destroying && !qrBusy.get() && !planeActive
                && now - lastQrScanAt >= 320;
        if (!track && !qr) {
            image.close();
            return;
        }

        int rotation = 0;
        Mat gray = null;
        Bitmap qrFrame = null;
        try {
            rotation = image.getImageInfo().getRotationDegrees();
            if (track) {
                Mat planeY = yPlaneToMat(image);
                if (planeY != null) {
                    gray = uprightGray(planeY, rotation, 560);
                }
            }
            if (qr) {
                Bitmap raw = image.toBitmap();
                Bitmap upright = rotate(raw, rotation);
                if (upright != raw) {
                    raw.recycle();
                }
                qrFrame = scaleDown(upright, 640);
                if (qrFrame != upright) {
                    upright.recycle();
                }
            }
        } catch (Throwable t) {
            if (gray != null) {
                gray.release();
                gray = null;
            }
        } finally {
            image.close();
        }

        if (gray != null) {
            lastTrackAt = now;
            planeTracker.onFrame(gray, gray.cols(), gray.rows());
            gray = null;
        }

        if (qr && qrFrame != null && qrBusy.compareAndSet(false, true)) {
            lastQrScanAt = now;
            final int uw = qrFrame.getWidth();
            final int uh = qrFrame.getHeight();
            final Bitmap frame = qrFrame;
            qrFrame = null;
            InputImage input = InputImage.fromBitmap(frame, 0);
            try {
                qrScanner.process(input)
                        .addOnSuccessListener(barcodes -> onQrDetected(barcodes, uw, uh))
                        .addOnCompleteListener(task -> {
                            if (!frame.isRecycled()) {
                                frame.recycle();
                            }
                            qrBusy.set(false);
                        });
            } catch (Throwable t) {
                if (!frame.isRecycled()) {
                    frame.recycle();
                }
                qrBusy.set(false);
            }
        }
        if (qrFrame != null) {
            qrFrame.recycle();
        }
    }

    /** ImageProxy 的 Y 平面 → 灰度 Mat（去掉 stride 填充，不经过 Bitmap）。 */
    private Mat yPlaneToMat(ImageProxy image) {
        try {
            ImageProxy.PlaneProxy plane = image.getPlanes()[0];
            if (plane.getPixelStride() != 1) {
                return null;
            }
            int w = image.getWidth();
            int h = image.getHeight();
            int stride = plane.getRowStride();
            if (w <= 0 || h <= 0 || stride < w) {
                return null;
            }
            java.nio.ByteBuffer buf = plane.getBuffer();
            buf.rewind();
            int need = h * stride;
            if (yPlaneBuffer == null || yPlaneBuffer.length < need) {
                yPlaneBuffer = new byte[need];
            }
            int n = Math.min(buf.remaining(), need);
            buf.get(yPlaneBuffer, 0, n);
            if (yRowBuffer == null || yRowBuffer.length != w) {
                yRowBuffer = new byte[w];
            }
            Mat gray = new Mat(h, w, CvType.CV_8UC1);
            for (int y = 0; y < h; y++) {
                int base = y * stride;
                if (base + w > n) {
                    break;
                }
                System.arraycopy(yPlaneBuffer, base, yRowBuffer, 0, w);
                gray.put(y, 0, yRowBuffer);
            }
            return gray;
        } catch (Throwable t) {
            return null;
        }
    }

    /** 旋转到当前屏幕方向并缩到最大宽度；所有权交给返回值。 */
    private Mat uprightGray(Mat src, int rotation, int maxWidth) {
        Mat rotated = new Mat();
        try {
            if (rotation == 90) {
                Core.rotate(src, rotated, Core.ROTATE_90_CLOCKWISE);
            } else if (rotation == 180) {
                Core.rotate(src, rotated, Core.ROTATE_180);
            } else if (rotation == 270) {
                Core.rotate(src, rotated, Core.ROTATE_90_COUNTERCLOCKWISE);
            } else {
                src.copyTo(rotated);
            }
        } finally {
            src.release();
        }
        int tw = rotated.cols();
        int th = rotated.rows();
        if (tw <= maxWidth) {
            return rotated;
        }
        int nw = maxWidth;
        int nh = Math.max(1, (int) Math.round(th * (double) maxWidth / tw));
        Mat small = new Mat();
        Imgproc.resize(rotated, small, new org.opencv.core.Size(nw, nh), 0, 0, Imgproc.INTER_LINEAR);
        rotated.release();
        return small;
    }

    private void onQrDetected(java.util.List<Barcode> barcodes, int uw, int uh) {
        if (destroying || arMode || root == null || barcodes == null || barcodes.isEmpty()) {
            return;
        }
        Barcode best = null;
        float bestArea = 0;
        for (Barcode b : barcodes) {
            android.graphics.Rect box = b.getBoundingBox();
            if (box == null) {
                continue;
            }
            float area = box.width() * box.height();
            if (area > bestArea) {
                bestArea = area;
                best = b;
            }
        }
        if (best == null) {
            return;
        }
        android.graphics.Point[] corners = best.getCornerPoints();
        if (corners == null || corners.length < 4) {
            android.graphics.Rect box = best.getBoundingBox();
            if (box == null) {
                return;
            }
            corners = new android.graphics.Point[]{
                    new android.graphics.Point(box.left, box.top),
                    new android.graphics.Point(box.right, box.top),
                    new android.graphics.Point(box.right, box.bottom),
                    new android.graphics.Point(box.left, box.bottom),
            };
        }
        int vw = root.getWidth();
        int vh = root.getHeight();
        if (vw <= 0 || vh <= 0 || uw <= 0 || uh <= 0) {
            return;
        }
        float scale = Math.max(vw / (float) uw, vh / (float) uh);
        float ox = (vw - uw * scale) * 0.5f;
        float oy = (vh - uh * scale) * 0.5f;
        QrTrack t = new QrTrack();
        for (int i = 0; i < 4; i++) {
            t.pts[i * 2] = ox + corners[i].x * scale;
            t.pts[i * 2 + 1] = oy + corners[i].y * scale;
        }
        t.at = SystemClock.elapsedRealtime();
        qrTrack = t;
        android.util.Log.d("GanFanYu", "QR center=" + (int) ((t.pts[0] + t.pts[2] + t.pts[4] + t.pts[6]) * 0.25f)
                + "," + (int) ((t.pts[1] + t.pts[3] + t.pts[5] + t.pts[7]) * 0.25f));
        if (qrLocked) {
            applyQrTrack(t, false);
        } else if (!qrHintShown) {
            qrHintShown = true;
            setHint("检测到二维码 · 点她旁边可以锁定到码上");
        }
    }

    private void sendFrameAsync(Bitmap bitmap) {
        netExecutor.execute(() -> {
            try {
                Bitmap scaled = scaleDown(bitmap, FRAME_MAX_WIDTH);
                ByteArrayOutputStream out = new ByteArrayOutputStream();
                scaled.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out);
                if (scaled != bitmap) {
                    scaled.recycle();
                }
                submitFrame(out.toByteArray());
            } catch (Throwable t) {
                finishLook("这一帧没抓到，再试一次");
            } finally {
                if (!bitmap.isRecycled()) {
                    bitmap.recycle();
                }
            }
        });
    }

    private void submitFrame(byte[] jpeg) {
        String response = "";
        try {
            ensureWorldSession();
            if (worldSession.isEmpty()) {
                finishLook("她还没连上，稍等一下");
                return;
            }
            JSONObject o = new JSONObject();
            o.put("session", worldSession);
            o.put("source", arMode ? "ar" : "lite");
            o.put("force", true);
            o.put("ts", System.currentTimeMillis() / 1000.0);
            JSONObject focus = new JSONObject();
            focus.put("on", false);
            focus.put("x", 0.5);
            focus.put("y", 0.5);
            o.put("focus", focus);
            o.put("image", Base64.encodeToString(jpeg, Base64.NO_WRAP));
            response = postJson("/api/world/frame", o.toString(), 45000);
        } catch (Throwable ignored) {
        }
        if (response.isEmpty()) {
            finishLook("她这次没回应，再试一次");
            return;
        }
        JSONObject r;
        try {
            r = new JSONObject(response);
        } catch (Throwable t) {
            finishLook("她这次没回应，再试一次");
            return;
        }
        if (!r.optBoolean("ok")) {
            String err = r.optString("error");
            if ("session_not_found".equals(err)) {
                worldSession = "";
            }
            finishLook("没看清，再试一次");
            return;
        }
        if (r.optBoolean("skipped")) {
            finishLook("");
            return;
        }
        final String text = r.optString("text");
        final String caption = r.optString("caption");
        final String place = r.optString("place");
        final double valence = r.optDouble("valence", 0.2);
        final double arousal = r.optDouble("arousal", 0.3);
        runOnUiThread(() -> {
            looking.set(false);
            if (lookBtn != null) {
                lookBtn.setAlpha(1f);
            }
            if (text.isEmpty() && caption.isEmpty()) {
                setHint("她这次没看清");
                return;
            }
            String bubble = text;
            if (bubble.isEmpty()) {
                bubble = caption.isEmpty() ? "她看了一会儿外面" : ("她看到：" + caption);
            }
            replyPet(bubble, valence, arousal);
        });
    }

    private void finishLook(String message) {
        runOnUiThread(() -> {
            looking.set(false);
            wantFrame.set(false);
            if (lookBtn != null) {
                lookBtn.setAlpha(1f);
            }
            if (message != null && !message.isEmpty()) {
                setHint(message);
            }
        });
    }

    private void showPetBubble(String text) {
        if (petBubbleNative == null) {
            return;
        }
        String t = text == null ? "" : text.trim();
        if (t.isEmpty()) {
            return;
        }
        main.post(() -> {
            petBubbleNative.setText(t);
            petBubbleNative.setVisibility(View.VISIBLE);
            petBubbleNative.measure(
                    View.MeasureSpec.makeMeasureSpec(dp(260), View.MeasureSpec.AT_MOST),
                    View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED));
            positionPetBubble();
            petBubbleNative.animate().alpha(1f).setDuration(140).start();
            if (petBubbleHide != null) {
                main.removeCallbacks(petBubbleHide);
            }
            petBubbleHide = () -> {
                if (petBubbleNative == null) {
                    return;
                }
                petBubbleNative.animate().alpha(0f).setDuration(180)
                        .withEndAction(() -> petBubbleNative.setVisibility(View.GONE)).start();
            };
            main.postDelayed(petBubbleHide, Math.max(4600, t.length() * 170));
        });
    }

    private void positionPetBubble() {
        if (petBubbleNative == null || root == null
                || petBubbleNative.getVisibility() != View.VISIBLE) {
            return;
        }
        int screenW = root.getWidth();
        if (screenW <= 0) {
            return;
        }
        int bw = petBubbleNative.getMeasuredWidth();
        int bh = petBubbleNative.getMeasuredHeight();
        if (bw <= 0 || bh <= 0) {
            return;
        }
        int visualTop = (int) (petY - dp(PET_H_DP) * petScale);
        int x = (int) (petX - bw / 2f);
        x = Math.max(dp(12), Math.min(screenW - bw - dp(12), x));
        int y = visualTop - bh - dp(8);
        /* 上方实在没空间就贴到顶部区域，至少不压住小鲸鱼 */
        y = Math.max(dp(66), y);
        petBubbleNative.setX(x);
        petBubbleNative.setY(y);
    }

    private void hidePetBubble() {
        if (petBubbleNative == null) {
            return;
        }
        if (petBubbleHide != null) {
            main.removeCallbacks(petBubbleHide);
        }
        petBubbleNative.setVisibility(View.GONE);
        petBubbleNative.setAlpha(0f);
    }

    private void replyPet(String text, double valence, double arousal) {
        if (petWeb == null) {
            return;
        }
        try {
            String js = "window.__petReply&&window.__petReply("
                    + JSONObject.quote(text) + ","
                    + String.format(Locale.US, "%.3f", valence) + ","
                    + String.format(Locale.US, "%.3f", arousal) + ")";
            petWeb.evaluateJavascript(js, null);
        } catch (Throwable ignored) {
        }
    }

    private void ensureWorldSession() {
        if (!worldSession.isEmpty()) {
            return;
        }
        String r = postJson("/api/world/start", "{}", 8000);
        try {
            JSONObject o = new JSONObject(r);
            if (o.optBoolean("ok")) {
                worldSession = o.optString("id");
            }
        } catch (Throwable ignored) {
        }
    }

    private void stopWorldSession(String sid) {
        if (sid == null || sid.isEmpty()) {
            return;
        }
        try {
            JSONObject o = new JSONObject();
            o.put("session", sid);
            postJson("/api/world/stop", o.toString(), 15000);
        } catch (Throwable ignored) {
        }
    }

    private String postJson(String path, String body, int readTimeout) {
        HttpURLConnection conn = null;
        try {
            URL url = new URL(BASE + path);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setConnectTimeout(3000);
            conn.setReadTimeout(readTimeout);
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            byte[] bytes = (body == null ? "{}" : body).getBytes(StandardCharsets.UTF_8);
            try (OutputStream os = conn.getOutputStream()) {
                os.write(bytes);
            }
            int code = conn.getResponseCode();
            InputStream in = (code >= 200 && code < 300) ? conn.getInputStream() : conn.getErrorStream();
            if (in == null) {
                return "";
            }
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            byte[] chunk = new byte[4096];
            int n;
            while ((n = in.read(chunk)) > 0) {
                buf.write(chunk, 0, n);
            }
            in.close();
            return buf.toString("UTF-8");
        } catch (Throwable t) {
            return "";
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private Bitmap rotate(Bitmap src, int degrees) {
        if (src == null || degrees == 0) {
            return src;
        }
        try {
            android.graphics.Matrix m = new android.graphics.Matrix();
            m.postRotate(degrees);
            return Bitmap.createBitmap(src, 0, 0, src.getWidth(), src.getHeight(), m, true);
        } catch (Throwable t) {
            return src;
        }
    }

    private Bitmap scaleDown(Bitmap src, int maxWidth) {
        if (src == null || src.getWidth() <= maxWidth) {
            return src;
        }
        float ratio = maxWidth / (float) src.getWidth();
        int h = Math.max(1, (int) (src.getHeight() * ratio));
        return Bitmap.createScaledBitmap(src, maxWidth, h, true);
    }

    // ------------------------------------------------------------------
    // 小工具
    // ------------------------------------------------------------------

    private void setHint(String text) {
        if (hintView == null || text == null) {
            return;
        }
        if (text.contentEquals(hintView.getText())) {
            return;
        }
        hintView.setText(text);
        hintView.setVisibility(View.VISIBLE);
        hintView.setClickable(installAvailable);
    }

    private int dp(int value) {
        return Math.max(1, (int) (value * getResources().getDisplayMetrics().density + 0.5f));
    }

    // ------------------------------------------------------------------
    // ARCore 背景渲染 + 锚点投影
    // ------------------------------------------------------------------

    static final class ArRenderer implements GLSurfaceView.Renderer {
        private static final float[] QUAD = new float[]{
                -1f, -1f,
                -1f, 1f,
                1f, -1f,
                1f, 1f,
        };

        private final Session session;
        private final ArPetActivity host;
        private final Handler ui = new Handler(Looper.getMainLooper());

        private int textureId;
        private int program;
        private int aPosition;
        private int aTexCoord;
        private int uTexture;
        private FloatBuffer posBuffer;
        private FloatBuffer uvBuffer;
        private final float[] uv = new float[8];
        private boolean uvDirty = true;
        private boolean firstFrame = true;
        private int viewW;
        private int viewH;

        private Anchor anchor;
        private volatile boolean tapPending;
        private volatile float tapX;
        private volatile float tapY;

        private final float[] proj = new float[16];
        private final float[] viewM = new float[16];
        private final float[] worldPt = new float[4];
        private final float[] camPt = new float[4];
        private final float[] clipPt = new float[4];
        private float smX = Float.NaN;
        private float smY = Float.NaN;
        private float smS = Float.NaN;
        private boolean lastTracking;

        ArRenderer(Session session, ArPetActivity host) {
            this.session = session;
            this.host = host;
        }

        void requestTap(float x, float y) {
            tapX = x;
            tapY = y;
            tapPending = true;
        }

        void releaseAnchor() {
            if (anchor != null) {
                anchor.detach();
                anchor = null;
            }
        }

        @Override
        public void onSurfaceCreated(GL10 gl, EGLConfig config) {
            GLES20.glClearColor(0f, 0f, 0f, 1f);
            int[] textures = new int[1];
            GLES20.glGenTextures(1, textures, 0);
            textureId = textures[0];
            GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textureId);
            GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,
                    GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR);
            GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,
                    GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR);
            GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,
                    GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE);
            GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,
                    GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE);
            try {
                session.setCameraTextureName(textureId);
            } catch (Throwable ignored) {
            }

            program = buildProgram();
            if (program == 0) {
                ui.post(() -> host.onArCameraLost());
                return;
            }
            aPosition = GLES20.glGetAttribLocation(program, "aPosition");
            aTexCoord = GLES20.glGetAttribLocation(program, "aTexCoord");
            uTexture = GLES20.glGetUniformLocation(program, "sTexture");
            posBuffer = floatBuffer(QUAD);
            uvBuffer = floatBuffer(new float[8]);
            uvDirty = true;
        }

        @Override
        public void onSurfaceChanged(GL10 gl, int width, int height) {
            viewW = width;
            viewH = height;
            GLES20.glViewport(0, 0, width, height);
            try {
                session.setDisplayGeometry(host.displayRotation(), width, height);
            } catch (Throwable ignored) {
            }
            uvDirty = true;
        }

        @Override
        public void onDrawFrame(GL10 gl) {
            GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT | GLES20.GL_DEPTH_BUFFER_BIT);
            Frame frame;
            try {
                frame = session.update();
            } catch (CameraNotAvailableException e) {
                ui.post(host::onArCameraLost);
                try {
                    session.pause();
                } catch (Throwable ignored) {
                }
                return;
            } catch (Throwable t) {
                return;
            }
            Camera camera = frame.getCamera();
            if (uvDirty || firstFrame || frame.hasDisplayGeometryChanged()) {
                try {
                    frame.transformCoordinates2d(
                            Coordinates2d.OPENGL_NORMALIZED_DEVICE_COORDINATES, QUAD,
                            Coordinates2d.TEXTURE_NORMALIZED, uv);
                    uvBuffer.position(0);
                    uvBuffer.put(uv);
                    uvBuffer.position(0);
                    uvDirty = false;
                } catch (Throwable ignored) {
                }
            }
            firstFrame = false;

            drawBackground();

            if (tapPending) {
                tapPending = false;
                hitTest(frame, tapX, tapY);
            }

            boolean tracking = camera.getTrackingState() == TrackingState.TRACKING;
            if (tracking != lastTracking) {
                lastTracking = tracking;
                ui.post(() -> host.onTracking(tracking));
            }
            if (!tracking) {
                host.onPetProjected(0f, 0f, 1f, false);
                return;
            }
            projectPet(frame, camera);
        }

        private void drawBackground() {
            if (program == 0 || uvBuffer == null) {
                return;
            }
            GLES20.glDisable(GLES20.GL_DEPTH_TEST);
            GLES20.glDepthMask(false);
            GLES20.glUseProgram(program);
            GLES20.glActiveTexture(GLES20.GL_TEXTURE0);
            GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textureId);
            GLES20.glUniform1i(uTexture, 0);

            posBuffer.position(0);
            GLES20.glVertexAttribPointer(aPosition, 2, GLES20.GL_FLOAT, false, 0, posBuffer);
            GLES20.glEnableVertexAttribArray(aPosition);
            uvBuffer.position(0);
            GLES20.glVertexAttribPointer(aTexCoord, 2, GLES20.GL_FLOAT, false, 0, uvBuffer);
            GLES20.glEnableVertexAttribArray(aTexCoord);

            GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);

            GLES20.glDisableVertexAttribArray(aPosition);
            GLES20.glDisableVertexAttribArray(aTexCoord);
            GLES20.glDepthMask(true);
            GLES20.glEnable(GLES20.GL_DEPTH_TEST);
        }

        private void hitTest(Frame frame, float x, float y) {
            Anchor next = null;
            List<HitResult> hits = frame.hitTest(x, y);
            for (HitResult h : hits) {
                Trackable t = h.getTrackable();
                if (t instanceof Plane) {
                    Plane plane = (Plane) t;
                    if (plane.getTrackingState() == TrackingState.TRACKING
                            && plane.isPoseInPolygon(h.getHitPose())) {
                        next = h.createAnchor();
                        break;
                    }
                }
            }
            if (next == null) {
                for (HitResult h : hits) {
                    Trackable t = h.getTrackable();
                    if (t.getTrackingState() != TrackingState.TRACKING) {
                        continue;
                    }
                    if (t instanceof Plane && !((Plane) t).isPoseInPolygon(h.getHitPose())) {
                        continue;
                    }
                    if (t instanceof Plane || t instanceof Point) {
                        next = h.createAnchor();
                        break;
                    }
                }
            }
            if (next == null) {
                ui.post(host::onAnchorMissed);
                return;
            }
            if (anchor != null) {
                anchor.detach();
            }
            anchor = next;
            smX = Float.NaN;
            smY = Float.NaN;
            smS = Float.NaN;
            ui.post(host::onAnchorPlaced);
        }

        private void projectPet(Frame frame, Camera camera) {
            if (anchor == null || anchor.getTrackingState() != TrackingState.TRACKING
                    || viewW <= 0 || viewH <= 0) {
                host.onPetProjected(0f, 0f, 1f, false);
                return;
            }
            Pose pose = anchor.getPose();
            worldPt[0] = pose.tx();
            worldPt[1] = pose.ty();
            worldPt[2] = pose.tz();
            worldPt[3] = 1f;
            camera.getViewMatrix(viewM, 0);
            Matrix.multiplyMV(camPt, 0, viewM, 0, worldPt, 0);
            if (camPt[2] > -0.05f) {
                host.onPetProjected(0f, 0f, 1f, false);
                return;
            }
            camera.getProjectionMatrix(proj, 0, 0.05f, 60f);
            Matrix.multiplyMV(clipPt, 0, proj, 0, camPt, 0);
            if (clipPt[3] <= 0.0001f) {
                host.onPetProjected(0f, 0f, 1f, false);
                return;
            }
            float nx = clipPt[0] / clipPt[3];
            float ny = clipPt[1] / clipPt[3];
            if (Math.abs(nx) > 1.35f || Math.abs(ny) > 1.35f) {
                host.onPetProjected(0f, 0f, 1f, false);
                return;
            }
            float x = (nx + 1f) * 0.5f * viewW;
            float y = (1f - ny) * 0.5f * viewH;
            float dist = (float) Math.sqrt(
                    camPt[0] * camPt[0] + camPt[1] * camPt[1] + camPt[2] * camPt[2]);
            float focalPx = Math.abs(proj[5]) * viewH * 0.5f;
            float scale = (focalPx * PET_REAL_HEIGHT_M / Math.max(0.2f, dist))
                    / Math.max(1f, host.petBaseHeightPx());
            scale = Math.max(0.16f, Math.min(2.6f, scale));

            if (Float.isNaN(smX)) {
                smX = x;
                smY = y;
                smS = scale;
            } else {
                smX = smX + (x - smX) * 0.18f;
                smY = smY + (y - smY) * 0.18f;
                smS = smS + (scale - smS) * 0.18f;
            }
            host.onPetProjected(smX, smY, smS, true);
        }

        private static FloatBuffer floatBuffer(float[] data) {
            ByteBuffer bb = ByteBuffer.allocateDirect(data.length * 4);
            bb.order(ByteOrder.nativeOrder());
            FloatBuffer fb = bb.asFloatBuffer();
            fb.put(data);
            fb.position(0);
            return fb;
        }

        private static int buildProgram() {
            String vertex = "attribute vec2 aPosition;\n"
                    + "attribute vec2 aTexCoord;\n"
                    + "varying vec2 vTexCoord;\n"
                    + "void main() {\n"
                    + "  gl_Position = vec4(aPosition, 0.0, 1.0);\n"
                    + "  vTexCoord = aTexCoord;\n"
                    + "}\n";
            String fragment = "#extension GL_OES_EGL_image_external : require\n"
                    + "precision mediump float;\n"
                    + "varying vec2 vTexCoord;\n"
                    + "uniform samplerExternalOES sTexture;\n"
                    + "void main() {\n"
                    + "  gl_FragColor = texture2D(sTexture, vTexCoord);\n"
                    + "}\n";
            int vs = loadShader(GLES20.GL_VERTEX_SHADER, vertex);
            int fs = loadShader(GLES20.GL_FRAGMENT_SHADER, fragment);
            if (vs == 0 || fs == 0) {
                return 0;
            }
            int p = GLES20.glCreateProgram();
            GLES20.glAttachShader(p, vs);
            GLES20.glAttachShader(p, fs);
            GLES20.glLinkProgram(p);
            int[] ok = new int[1];
            GLES20.glGetProgramiv(p, GLES20.GL_LINK_STATUS, ok, 0);
            GLES20.glDeleteShader(vs);
            GLES20.glDeleteShader(fs);
            if (ok[0] == 0) {
                GLES20.glDeleteProgram(p);
                return 0;
            }
            return p;
        }

        private static int loadShader(int type, String src) {
            int shader = GLES20.glCreateShader(type);
            GLES20.glShaderSource(shader, src);
            GLES20.glCompileShader(shader);
            int[] ok = new int[1];
            GLES20.glGetShaderiv(shader, GLES20.GL_COMPILE_STATUS, ok, 0);
            if (ok[0] == 0) {
                GLES20.glDeleteShader(shader);
                return 0;
            }
            return shader;
        }
    }
}
