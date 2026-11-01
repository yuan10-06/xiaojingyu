package com.ganfanyu.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.PowerManager;

/** 她发消息时在手机屏幕上弹通知；App 在前台且屏幕亮着时不打扰。 */
public final class Notifier {
    private static final String CHANNEL = "messages";
    private static final int ID = 2;
    private static Context context;

    private Notifier() {
    }

    public static void init(Context ctx) {
        context = ctx.getApplicationContext();
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = context.getSystemService(NotificationManager.class);
            if (nm != null) {
                NotificationChannel ch = new NotificationChannel(
                        CHANNEL, "小鲸鱼消息", NotificationManager.IMPORTANCE_HIGH);
                ch.setDescription("她发来的消息和主动消息");
                ch.enableVibration(true);
                ch.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
                nm.createNotificationChannel(ch);
            }
        }
    }

    public static boolean canNotify() {
        if (context == null) {
            return false;
        }
        try {
            NotificationManager nm = (NotificationManager)
                    context.getSystemService(Context.NOTIFICATION_SERVICE);
            return nm != null && nm.areNotificationsEnabled();
        } catch (Throwable ignored) {
            return false;
        }
    }

    public static void show(String title, String text) {
        if (context == null) {
            return;
        }
        // 只有“正在看聊天页”才不打扰；设置页/后台/桌宠浮在桌面时都正常弹通知。
        // 桌宠头顶的小气泡与系统通知是两条并行通道，互不抑制。
        if (AppState.activityVisible && AppState.chatFocused && isScreenOn()) {
            return;
        }
        post(title, text);
    }

    /** 设置页的测试按钮：不受前台状态限制，确保通知通道真的能用。 */
    public static void showTest(String title, String text) {
        if (context == null) {
            return;
        }
        post(title, text);
    }

    /** 通知诊断：设置页显示权限/渠道状态。 */
    public static int channelImportance() {
        if (context == null || Build.VERSION.SDK_INT < 26) {
            return 3;
        }
        try {
            NotificationManager nm = context.getSystemService(NotificationManager.class);
            if (nm == null) {
                return 0;
            }
            NotificationChannel ch = nm.getNotificationChannel(CHANNEL);
            return ch == null ? 0 : ch.getImportance();
        } catch (Throwable ignored) {
            return 0;
        }
    }

    public static boolean permissionGranted() {
        if (context == null) {
            return false;
        }
        if (Build.VERSION.SDK_INT < 33) {
            return true;
        }
        try {
            return context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)
                    == android.content.pm.PackageManager.PERMISSION_GRANTED;
        } catch (Throwable ignored) {
            return false;
        }
    }

    private static boolean isScreenOn() {
        try {
            PowerManager pm = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
            return pm != null && pm.isInteractive();
        } catch (Throwable ignored) {
            return true;
        }
    }

    private static void post(String title, String text) {
        try {
            Intent open = new Intent(context, MainActivity.class);
            open.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP
                    | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            open.putExtra("open", "chat");
            PendingIntent pi = PendingIntent.getActivity(
                    context, 0, open,
                    Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);
            Notification.Builder b;
            if (Build.VERSION.SDK_INT >= 26) {
                b = new Notification.Builder(context, CHANNEL);
            } else {
                b = new Notification.Builder(context);
            }
            b.setContentTitle(title == null || title.isEmpty() ? "小鲸鱼" : title)
                    .setContentText(text == null ? "" : text)
                    .setStyle(new Notification.BigTextStyle().bigText(text == null ? "" : text))
                    .setSmallIcon(com.ganfanyu.app.R.drawable.ic_stat_whale)
                    .setContentIntent(pi)
                    .setAutoCancel(true)
                    .setPriority(Notification.PRIORITY_HIGH)
                    .setCategory(Notification.CATEGORY_MESSAGE)
                    .setVisibility(Notification.VISIBILITY_PUBLIC)
                    .setDefaults(Notification.DEFAULT_ALL);
            NotificationManager nm = (NotificationManager)
                    context.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null) {
                nm.notify(ID, b.build());
            }
        } catch (Throwable ignored) {
        }
    }
}
