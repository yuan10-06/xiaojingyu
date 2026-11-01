package com.ganfanyu.app;

import android.content.Context;

/** 记录 App 是否在前台；通知只在她不在眼前时弹。 */
public final class AppState {
    public static volatile boolean activityVisible = false;
    public static volatile boolean chatFocused = false;
    public static volatile boolean floatingVisible = false;
    public static volatile Context context;
    public static volatile android.app.Activity activity;

    private AppState() {
    }
}
