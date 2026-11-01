package com.ganfanyu.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import android.util.Log;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class BrainService extends Service {
    private static final String CHANNEL = "ganfanyu";
    private static final int NOTICE_ID = 1;
    public static final String ACTION_SHOW_FLOATING = "com.ganfanyu.app.SHOW_FLOATING";
    public static final String ACTION_HIDE_FLOATING = "com.ganfanyu.app.HIDE_FLOATING";
    public static volatile String lastError = "";
    private static Thread worker;
    private PowerManager.WakeLock wake;

    @Override
    public void onCreate() {
        super.onCreate();
        AppState.context = getApplicationContext();
        Notifier.init(this);
        createChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForegroundCompat(buildNotice());
        if (intent != null) {
            String action = intent.getAction();
            if (ACTION_SHOW_FLOATING.equals(action)) {
                FloatingOverlay.show(this);
            } else if (ACTION_HIDE_FLOATING.equals(action)) {
                FloatingOverlay.hide();
            }
        }
        if (wake == null) {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            wake = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "GanFanYu::brain");
            wake.setReferenceCounted(false);
            wake.acquire();
        }
        if (worker == null) {
            worker = new Thread(this::startPython, "brainn-python");
            worker.setDaemon(true);
            worker.start();
        }
        return START_STICKY;
    }

    private void startPython() {
        try {
            Seed.ensure(this);
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }
            Python.getInstance()
                    .getModule("mobile_server")
                    .callAttr("start", getFilesDir().getAbsolutePath());
            Log.i("GanFanYu", "python service started");
            FloatingOverlay.restore(this);
        } catch (Throwable t) {
            lastError = t.getClass().getSimpleName() + ": " + String.valueOf(t.getMessage());
            Log.e("GanFanYu", "python start failed", t);
        }
    }

    private void startForegroundCompat(Notification notice) {
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTICE_ID, notice, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(NOTICE_ID, notice);
        }
    }

    private Notification buildNotice() {
        Intent open = new Intent(this, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        open.putExtra("open", "chat");
        PendingIntent pi = PendingIntent.getActivity(
                this, 0, open,
                Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);
        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= 26) {
            b = new Notification.Builder(this, CHANNEL);
        } else {
            b = new Notification.Builder(this);
        }
        return b.setContentTitle("小鲸鱼")
                .setContentText("正在后台陪着你")
                .setSmallIcon(com.ganfanyu.app.R.drawable.ic_stat_whale)
                .setContentIntent(pi)
                .setOngoing(true)
                .setPriority(Notification.PRIORITY_LOW)
                .build();
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(
                    CHANNEL, "小鲸鱼运行状态", NotificationManager.IMPORTANCE_LOW);
            ch.setShowBadge(false);
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) {
                nm.createNotificationChannel(ch);
            }
        }
    }

    @Override
    public void onDestroy() {
        FloatingOverlay.hide();
        try {
            if (Python.isStarted()) {
                Python.getInstance().getModule("mobile_server").callAttr("shutdown");
            }
        } catch (Throwable ignored) {
        }
        if (wake != null && wake.isHeld()) {
            wake.release();
        }
        worker = null;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
