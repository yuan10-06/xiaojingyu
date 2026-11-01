package com.ganfanyu.app;

import android.content.Context;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/** 首次启动把配置、表情包和记忆库解到应用私有目录；之后的聊天数据不再覆盖。 */
final class Seed {
    private Seed() {
    }

    static void ensure(Context ctx) throws IOException {
        File root = ctx.getFilesDir();
        try (ZipInputStream zis = new ZipInputStream(ctx.getAssets().open("seed.zip"))) {
            byte[] buf = new byte[8192];
            ZipEntry entry;
            while ((entry = zis.getNextEntry()) != null) {
                String name = entry.getName();
                if (name.contains("..")) {
                    continue;
                }
                File out = new File(root, name);
                if (entry.isDirectory()) {
                    out.mkdirs();
                    continue;
                }
                boolean isWeb = name.startsWith("web/");
                if (out.exists() && !isWeb) {
                    continue;
                }
                // 大块动画素材（webm）大小没变就不重写；小的页面/脚本永远覆盖，避免同类改动被漏掉
                long size = entry.getSize();
                if (out.exists() && size >= 1024 * 1024 && out.length() == size) {
                    continue;
                }
                File parent = out.getParentFile();
                if (parent != null) {
                    parent.mkdirs();
                }
                try (FileOutputStream fos = new FileOutputStream(out)) {
                    int n;
                    while ((n = zis.read(buf)) > 0) {
                        fos.write(buf, 0, n);
                    }
                }
            }
        }
    }
}
