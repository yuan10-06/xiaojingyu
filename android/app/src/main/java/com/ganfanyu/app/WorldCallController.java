package com.ganfanyu.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.graphics.Bitmap;
import android.graphics.Matrix;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Base64;
import android.view.MotionEvent;
import android.util.Size;
import android.view.Gravity;
import android.view.View;
import android.view.ViewOutlineProvider;
import android.view.ViewGroup;
import android.webkit.WebView;
import android.widget.FrameLayout;

import androidx.annotation.NonNull;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ExperimentalGetImage;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageProxy;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.lifecycle.Lifecycle;
import androidx.lifecycle.LifecycleOwner;
import androidx.lifecycle.LifecycleRegistry;

import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.face.Face;
import com.google.mlkit.vision.face.FaceDetection;
import com.google.mlkit.vision.face.FaceDetector;
import com.google.mlkit.vision.face.FaceDetectorOptions;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Random;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 小鲸鱼 2D 页里的视频通话：只在前台、只在通话层打开时占用相机。
 * - 前置相机：ML Kit 人脸，驱动 Live2D 眼珠/头部。
 * - 每 3~5 秒抓一帧，交给本地 Python 做场景理解。
 * - 后置相机：看外面，不做人脸跟随。
 */
public final class WorldCallController {
    private static final int REQ_CAMERA = 9001;
    private static final long FACE_INTERVAL_MS = 90;
    private static final long FRAME_MIN_MS = 3000;
    private static final long FRAME_MAX_MS = 5000;
    private static final long FACE_LOST_MS = 900;
    private static final int FRAME_MAX_WIDTH = 960;
    private static final int JPEG_QUALITY = 72;

    private final Activity activity;
    private final FrameLayout host;
    private final WebView web;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService analysisExecutor = Executors.newSingleThreadExecutor();
    private final ExecutorService netExecutor = Executors.newSingleThreadExecutor();
    private final Random random = new Random();
    private final AtomicBoolean faceBusy = new AtomicBoolean(false);
    private final AtomicBoolean sending = new AtomicBoolean(false);

    private final LifecycleOwner cameraOwner;
    private final LifecycleRegistry cameraLifecycle;
    private final FrameLayout box;
    private final PreviewView previewView;

    private ProcessCameraProvider cameraProvider;
    private Preview preview;
    private ImageAnalysis analysis;
    private FaceDetector faceDetector;

    private volatile boolean active;
    private volatile boolean userPaused;
    private volatile boolean appPaused;
    private volatile boolean front = true;
    private volatile String sessionId = "";
    private volatile boolean forceSnapshot;
    private volatile boolean hasFocus;
    private volatile float focusX = 0.5f;
    private volatile float focusY = 0.5f;
    private volatile boolean faceCleared = true;
    private volatile long lastFaceSent;
    private volatile long lastFaceSeen;
    private volatile long nextFrameAt;
    private volatile int topInsetPx;

    public WorldCallController(@NonNull Activity activity, @NonNull FrameLayout host, @NonNull WebView web) {
        this.activity = activity;
        this.host = host;
        this.web = web;
        this.cameraOwner = new LifecycleOwner() {
            private final LifecycleRegistry registry = new LifecycleRegistry(this);

            @NonNull
            @Override
            public Lifecycle getLifecycle() {
                return registry;
            }
        };
        this.cameraLifecycle = (LifecycleRegistry) cameraOwner.getLifecycle();
        this.cameraLifecycle.setCurrentState(Lifecycle.State.CREATED);

        this.previewView = new PreviewView(activity);
        this.previewView.setImplementationMode(PreviewView.ImplementationMode.COMPATIBLE);
        this.previewView.setScaleType(PreviewView.ScaleType.FILL_CENTER);

        this.box = new FrameLayout(activity);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(0xCC0A1B2A);
        bg.setCornerRadius(dp(18));
        bg.setStroke(dp(2), 0x884FC3E0);
        box.setBackground(bg);
        box.setClipToOutline(true);
        box.setOutlineProvider(new ViewOutlineProvider() {
            @Override
            public void getOutline(View view, android.graphics.Outline outline) {
                outline.setRoundRect(0, 0, view.getWidth(), view.getHeight(), dp(18));
            }
        });
        FrameLayout.LayoutParams plp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
        int inset = dp(3);
        plp.setMargins(inset, inset, inset, inset);
        box.addView(previewView, plp);
        box.setVisibility(View.GONE);
        host.addView(box, buildBoxParams());
        previewView.setOnTouchListener((v, event) -> {
            if (event.getAction() == MotionEvent.ACTION_UP) {
                float x = Math.max(0f, Math.min(1f, event.getX() / Math.max(1, v.getWidth())));
                float y = Math.max(0f, Math.min(1f, event.getY() / Math.max(1, v.getHeight())));
                requestSnapshotAt(x, y);
                sendFocus(x, y);
            }
            return true;
        });
    }

    public boolean isActive() {
        return active;
    }

    public void setTopInset(int px) {
        topInsetPx = Math.max(0, px);
        if (box != null) {
            main.post(() -> {
                FrameLayout.LayoutParams lp = buildBoxParams();
                box.setLayoutParams(lp);
            });
        }
    }

    public void start(@NonNull String session) {
        main.post(() -> {
            sessionId = session == null ? "" : session;
            active = true;
            userPaused = false;
            appPaused = false;
            faceCleared = true;
            lastFaceSeen = SystemClock.elapsedRealtime();
            lastFaceSent = 0;
            nextFrameAt = SystemClock.elapsedRealtime() + FRAME_MIN_MS;
            box.setVisibility(View.VISIBLE);
            previewView.setVisibility(View.VISIBLE);
            cameraLifecycle.setCurrentState(Lifecycle.State.RESUMED);
            startCamera(front);
            sendJs("onReady", "{}");
        });
    }

    public void stop() {
        main.post(() -> {
            active = false;
            userPaused = false;
            sessionId = "";
            forceSnapshot = false;
            cancelCamera();
            if (box != null) {
                box.setVisibility(View.GONE);
            }
            previewView.setVisibility(View.VISIBLE);
        });
    }

    public void setUserPaused(boolean paused) {
        main.post(() -> {
            userPaused = paused;
            if (!active) {
                return;
            }
            if (paused) {
                cancelCamera();
                previewView.setVisibility(View.INVISIBLE);
            } else if (!appPaused) {
                previewView.setVisibility(View.VISIBLE);
                startCamera(front);
            }
        });
    }

    public void setFront(boolean useFront) {
        main.post(() -> {
            front = useFront;
            faceCleared = true;
            if (active && !userPaused && !appPaused) {
                startCamera(front);
            }
            sendFaceGone();
        });
    }

    public void requestSnapshot(boolean forceReply) {
        hasFocus = false;
        forceSnapshot = true;
        ensureCameraForSnapshot();
    }

    private void requestSnapshotAt(float x, float y) {
        focusX = Math.max(0f, Math.min(1f, x));
        focusY = Math.max(0f, Math.min(1f, y));
        hasFocus = true;
        forceSnapshot = true;
        ensureCameraForSnapshot();
    }

    private void ensureCameraForSnapshot() {
        main.post(() -> {
            if (active && !userPaused && !appPaused) {
                if (previewView.getVisibility() != View.VISIBLE) {
                    previewView.setVisibility(View.VISIBLE);
                }
                if (cameraProvider == null || analysis == null) {
                    startCamera(front);
                }
            }
        });
    }

    public void onActivityResume() {
        appPaused = false;
        if (active && !userPaused) {
            cameraLifecycle.setCurrentState(Lifecycle.State.RESUMED);
            previewView.setVisibility(View.VISIBLE);
            startCamera(front);
        }
    }

    public void onActivityPause() {
        appPaused = true;
        if (active) {
            cancelCamera();
            previewView.setVisibility(View.INVISIBLE);
        }
    }

    public void destroy() {
        main.post(() -> {
            active = false;
            cancelCamera();
            if (faceDetector != null) {
                try {
                    faceDetector.close();
                } catch (Throwable ignored) {
                }
                faceDetector = null;
            }
            analysisExecutor.shutdownNow();
            netExecutor.shutdownNow();
            if (box != null && box.getParent() == host) {
                host.removeView(box);
            }
        });
    }

    public void failPermission() {
        sendJs("onError", "{\"code\":\"camera_denied\"}");
    }

    private FrameLayout.LayoutParams buildBoxParams() {
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(dp(112), dp(152));
        lp.gravity = Gravity.TOP | Gravity.END;
        lp.topMargin = topInsetPx + dp(62);
        lp.rightMargin = dp(12);
        return lp;
    }

    private void startCamera(boolean useFront) {
        if (!active) {
            return;
        }
        try {
            ProcessCameraProvider.getInstance(activity).addListener(() -> {
                try {
                    cameraProvider = ProcessCameraProvider.getInstance(activity).get();
                } catch (Throwable t) {
                    sendError("camera_busy");
                    return;
                }
                bindUseCases(useFront);
            }, main::post);
        } catch (Throwable t) {
            sendError("camera_busy");
        }
    }

    private void bindUseCases(boolean useFront) {
        if (!active || cameraProvider == null) {
            return;
        }
        try {
            cancelCamera();
            preview = new Preview.Builder().build();
            preview.setSurfaceProvider(previewView.getSurfaceProvider());

            analysis = new ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .setTargetResolution(new Size(640, 480))
                    .build();
            analysis.setAnalyzer(analysisExecutor, this::analyze);

            CameraSelector selector = useFront
                    ? CameraSelector.DEFAULT_FRONT_CAMERA
                    : CameraSelector.DEFAULT_BACK_CAMERA;
            cameraProvider.bindToLifecycle(cameraOwner, selector, preview, analysis);
            lastFaceSeen = SystemClock.elapsedRealtime();
            nextFrameAt = SystemClock.elapsedRealtime() + FRAME_MIN_MS;
            if (useFront) {
                ensureFaceDetector();
            }
        } catch (Throwable t) {
            sendError("camera_busy");
        }
    }

    private void cancelCamera() {
        try {
            if (analysis != null) {
                analysis.clearAnalyzer();
            }
        } catch (Throwable ignored) {
        }
        try {
            if (cameraProvider != null) {
                cameraProvider.unbindAll();
            }
        } catch (Throwable ignored) {
        }
        preview = null;
        analysis = null;
    }

    private void ensureFaceDetector() {
        if (faceDetector != null) {
            return;
        }
        FaceDetectorOptions options = new FaceDetectorOptions.Builder()
                .setPerformanceMode(FaceDetectorOptions.PERFORMANCE_MODE_FAST)
                .setLandmarkMode(FaceDetectorOptions.LANDMARK_MODE_NONE)
                .setClassificationMode(FaceDetectorOptions.CLASSIFICATION_MODE_NONE)
                .setMinFaceSize(0.12f)
                .build();
        faceDetector = FaceDetection.getClient(options);
    }

    @SuppressLint("UnsafeOptInUsageError")
    @androidx.annotation.OptIn(markerClass = ExperimentalGetImage.class)
    private void analyze(@NonNull ImageProxy image) {
        if (!active || userPaused || appPaused) {
            image.close();
            return;
        }
        long now = SystemClock.elapsedRealtime();
        boolean snapshot = false;
        boolean forced = forceSnapshot;
        if (forced || now >= nextFrameAt) {
            snapshot = true;
            forceSnapshot = false;
            nextFrameAt = now + FRAME_MIN_MS + random.nextInt((int) (FRAME_MAX_MS - FRAME_MIN_MS + 1));
        }

        Bitmap bitmap = null;
        final int rotation = image.getImageInfo().getRotationDegrees();
        final boolean useFocus = hasFocus;
        final float useFocusX = focusX;
        final float useFocusY = focusY;
        if (useFocus) {
            hasFocus = false;
        }
        if (snapshot) {
            try {
                bitmap = image.toBitmap();
            } catch (Throwable ignored) {
                bitmap = null;
            }
        }

        boolean faceStarted = false;
        if (front && now - lastFaceSent >= FACE_INTERVAL_MS) {
            if (faceBusy.compareAndSet(false, true)) {
                try {
                    ensureFaceDetector();
                    android.media.Image media = image.getImage();
                    if (media != null && faceDetector != null) {
                        lastFaceSent = now;
                        faceStarted = true;
                        InputImage input = InputImage.fromMediaImage(media, image.getImageInfo().getRotationDegrees());
                        faceDetector.process(input)
                                .addOnSuccessListener(faces -> handleFaces(faces, image.getWidth(), image.getHeight()))
                                .addOnFailureListener(e -> { })
                                .addOnCompleteListener(task -> {
                                    faceBusy.set(false);
                                    image.close();
                                });
                    }
                } catch (Throwable ignored) {
                    // 出错时不要卡住 faceBusy
                }
                if (!faceStarted) {
                    faceBusy.set(false);
                }
            }
        }

        if (!faceStarted) {
            image.close();
            if (front && now - lastFaceSeen > FACE_LOST_MS && !faceCleared) {
                faceCleared = true;
                sendFaceGone();
            }
        }

        if (bitmap != null) {
            final boolean isFront = front;
            final boolean forceReply = forced;
            final boolean focusOn = useFocus;
            final float focusPX = useFocusX;
            final float focusPY = useFocusY;
            final Bitmap raw = bitmap;
            netExecutor.execute(() -> {
                try {
                    Bitmap upright = upright(raw, rotation);
                    Bitmap focused = focusOn && upright != null
                            ? cropFocus(upright, focusPX, focusPY) : upright;
                    Bitmap scaled = scaleDown(focused, FRAME_MAX_WIDTH);
                    ByteArrayOutputStream out = new ByteArrayOutputStream();
                    scaled.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out);
                    postFrame(out.toByteArray(), isFront, forceReply, focusOn, focusPX, focusPY);
                    if (scaled != focused) {
                        scaled.recycle();
                    }
                    if (focused != upright) {
                        focused.recycle();
                    }
                    if (upright != raw) {
                        upright.recycle();
                    }
                } catch (Throwable ignored) {
                } finally {
                    raw.recycle();
                }
            });
        }
    }

    private void handleFaces(List<Face> faces, int width, int height) {
        Face best = null;
        float bestArea = 0;
        for (Face f : faces) {
            float area = f.getBoundingBox().width() * f.getBoundingBox().height();
            if (area > bestArea) {
                bestArea = area;
                best = f;
            }
        }
        if (best == null || width <= 0 || height <= 0) {
            if (!faceCleared) {
                faceCleared = true;
                sendFaceGone();
            }
            return;
        }
        faceCleared = false;
        lastFaceSeen = SystemClock.elapsedRealtime();
        float cx = best.getBoundingBox().centerX() / (float) width;
        float cy = best.getBoundingBox().centerY() / (float) height;
        // 前置预览是镜像的：网页看到的左右和 analysis 图相反。
        if (front) {
            cx = 1f - cx;
        }
        try {
            JSONObject o = new JSONObject();
            o.put("visible", true);
            o.put("x", Math.max(-1f, Math.min(1f, (cx - 0.5f) * 2f)));
            o.put("y", Math.max(-1f, Math.min(1f, (cy - 0.5f) * 2f)));
            o.put("ax", best.getHeadEulerAngleX());
            o.put("ay", best.getHeadEulerAngleY());
            o.put("az", best.getHeadEulerAngleZ());
            sendJs("onFace", o.toString());
        } catch (Throwable ignored) {
        }
    }

    private void sendFaceGone() {
        sendJs("onFace", "{\"visible\":false}");
    }

    private void postFrame(byte[] jpeg, boolean isFront, boolean forceReply, boolean focusOn, float focusPX, float focusPY) {
        if (!active || jpeg == null || jpeg.length == 0) {
            return;
        }
        if (!sending.compareAndSet(false, true)) {
            return;
        }
        final String sid = sessionId;
        netExecutor.execute(() -> {
            String response = "";
            HttpURLConnection conn = null;
            try {
                URL url = new URL("http://127.0.0.1:8765/api/world/frame");
                conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setConnectTimeout(3000);
                conn.setReadTimeout(45000);
                conn.setDoOutput(true);
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                JSONObject o = new JSONObject();
                o.put("session", sid);
                o.put("source", isFront ? "front" : "back");
                o.put("force", forceReply);
                o.put("ts", System.currentTimeMillis() / 1000.0);
                JSONObject focus = new JSONObject();
                focus.put("on", focusOn);
                focus.put("x", focusPX);
                focus.put("y", focusPY);
                o.put("focus", focus);
                o.put("image", Base64.encodeToString(jpeg, Base64.NO_WRAP));
                byte[] body = o.toString().getBytes(StandardCharsets.UTF_8);
                try (OutputStream os = conn.getOutputStream()) {
                    os.write(body);
                }
                int code = conn.getResponseCode();
                InputStream in = (code >= 200 && code < 300) ? conn.getInputStream() : conn.getErrorStream();
                if (in != null) {
                    java.io.ByteArrayOutputStream buf = new java.io.ByteArrayOutputStream();
                    byte[] chunk = new byte[4096];
                    int n;
                    while ((n = in.read(chunk)) > 0) {
                        buf.write(chunk, 0, n);
                    }
                    in.close();
                    response = buf.toString("UTF-8");
                }
            } catch (Throwable ignored) {
            } finally {
                if (conn != null) {
                    conn.disconnect();
                }
                sending.set(false);
            }
            if (!response.isEmpty()) {
                sendJs("onScene", response);
            }
        });
    }

    private Bitmap cropFocus(Bitmap src, float fx, float fy) {
        if (src == null) {
            return null;
        }
        int w = src.getWidth();
        int h = src.getHeight();
        int size = Math.max(1, (int) (Math.min(w, h) * 0.55f));
        int cx = (int) (fx * w);
        int cy = (int) (fy * h);
        int left = Math.max(0, Math.min(w - size, cx - size / 2));
        int top = Math.max(0, Math.min(h - size, cy - size / 2));
        try {
            return Bitmap.createBitmap(src, left, top, size, size);
        } catch (Throwable ignored) {
            return src;
        }
    }

    private void sendFocus(float x, float y) {
        try {
            JSONObject o = new JSONObject();
            o.put("x", x);
            o.put("y", y);
            sendJs("onFocus", o.toString());
        } catch (Throwable ignored) {
        }
    }

    private Bitmap upright(Bitmap src, int degrees) {
        if (src == null) {
            return null;
        }
        if (degrees == 0) {
            return src;
        }
        try {
            Matrix m = new Matrix();
            m.postRotate(degrees);
            return Bitmap.createBitmap(src, 0, 0, src.getWidth(), src.getHeight(), m, true);
        } catch (Throwable ignored) {
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

    private void sendJs(String method, String json) {
        if (web == null) {
            return;
        }
        String body = json == null || json.isEmpty() ? "{}" : json;
        String script = "window.__worldCall&&window.__worldCall." + method
                + "&&window.__worldCall." + method + "(" + body + ")";
        web.post(() -> {
            try {
                web.evaluateJavascript(script, null);
            } catch (Throwable ignored) {
            }
        });
    }

    private void sendError(String code) {
        String safe = code == null ? "unknown" : code.replace("\"", "");
        sendJs("onError", "{\"code\":\"" + safe + "\"}");
    }

    private int dp(int value) {
        return Math.max(1, (int) (value * activity.getResources().getDisplayMetrics().density + 0.5f));
    }
}
