package com.ganfanyu.app;

import android.app.AppOpsManager;
import android.app.usage.UsageStats;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Process;

import org.json.JSONObject;

import java.util.List;

/** 只读取“当前前台是哪个应用、用了多久”，不读取屏幕内容。 */
public final class UsageReader {
    private UsageReader() {
    }

    public static boolean hasAccess(Context ctx) {
        try {
            AppOpsManager ops = (AppOpsManager) ctx.getSystemService(Context.APP_OPS_SERVICE);
            if (ops == null) {
                return false;
            }
            int mode = ops.checkOpNoThrow(
                    AppOpsManager.OPSTR_GET_USAGE_STATS,
                    Process.myUid(),
                    ctx.getPackageName());
            return mode == AppOpsManager.MODE_ALLOWED;
        } catch (Throwable ignored) {
            return false;
        }
    }

    public static String currentAppJson() {
        try {
            Context ctx = AppState.context;
            if (ctx == null || !hasAccess(ctx)) {
                return new JSONObject().put("ok", false).put("reason", "no_access").toString();
            }
            UsageStatsManager usm =
                    (UsageStatsManager) ctx.getSystemService(Context.USAGE_STATS_SERVICE);
            if (usm == null) {
                return new JSONObject().put("ok", false).toString();
            }
            long now = System.currentTimeMillis();
            List<UsageStats> stats = usm.queryUsageStats(
                    UsageStatsManager.INTERVAL_DAILY, now - 6L * 3600 * 1000, now);
            UsageStats best = null;
            if (stats != null) {
                for (UsageStats s : stats) {
                    if (best == null || s.getLastTimeUsed() > best.getLastTimeUsed()) {
                        best = s;
                    }
                }
            }
            if (best == null) {
                return new JSONObject().put("ok", false).put("reason", "empty").toString();
            }
            String pkg = best.getPackageName();
            PackageManager pm = ctx.getPackageManager();
            String label = pkg;
            try {
                ApplicationInfo info = pm.getApplicationInfo(pkg, 0);
                label = String.valueOf(pm.getApplicationLabel(info));
            } catch (Throwable ignored) {
            }
            long minutes = Math.max(0, best.getTotalTimeInForeground() / 60000L);
            return new JSONObject()
                    .put("ok", true)
                    .put("package", pkg)
                    .put("label", label)
                    .put("minutes", minutes)
                    .put("last_used", best.getLastTimeUsed())
                    .toString();
        } catch (Throwable t) {
            try {
                return new JSONObject().put("ok", false).put("reason", "error").toString();
            } catch (Throwable ignored) {
                return "{\"ok\":false}";
            }
        }
    }
}
