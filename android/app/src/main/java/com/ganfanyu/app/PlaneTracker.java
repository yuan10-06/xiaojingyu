package com.ganfanyu.app;

import android.os.Handler;
import android.os.Looper;

import org.opencv.android.OpenCVLoader;
import org.opencv.calib3d.Calib3d;
import org.opencv.core.Core;
import org.opencv.core.CvType;
import org.opencv.core.Mat;
import org.opencv.core.MatOfByte;
import org.opencv.core.MatOfFloat;
import org.opencv.core.MatOfPoint;
import org.opencv.core.MatOfPoint2f;
import org.opencv.core.Point;
import org.opencv.core.Scalar;
import org.opencv.core.Size;
import org.opencv.core.TermCriteria;
import org.opencv.imgproc.Imgproc;
import org.opencv.video.Video;

import java.util.ArrayList;
import java.util.List;

/**
 * 无标记平面跟踪：点击位置取角点，逐帧 LK 光流 + 单应，把二维桌宠钉在那块平面上。
 * 不依赖 ARCore/GMS；跟踪丢失时回调，让上层切回重力锁定。
 */
final class PlaneTracker {
    interface Listener {
        void onInitResult(boolean ok);

        void onTrack(float x, float y, float scale, boolean visible);

        void onLost();
    }

    private static final class Request {
        float screenX;
        float screenY;
        int viewW;
        int viewH;
        float baseScale;
    }

    private final Listener listener;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Object lock = new Object();
    private final boolean available;

    private volatile Request pending;

    private Mat prevGray;
    private MatOfPoint2f prevPts;
    private MatOfPoint2f refPts;
    private final float[] anchor = new float[2];
    private float baseScale = 0.8f;
    private int viewW;
    private int viewH;
    private boolean active;
    private int failStreak;
    private int framesSinceRebase;

    PlaneTracker(Listener listener) {
        this.listener = listener;
        boolean ok = false;
        try {
            ok = OpenCVLoader.initLocal();
        } catch (Throwable ignored) {
        }
        available = ok;
    }

    boolean isAvailable() {
        return available;
    }

    boolean isActive() {
        return active;
    }

    boolean requestInit(float screenX, float screenY, int vw, int vh, float base) {
        if (!available) {
            return false;
        }
        Request r = new Request();
        r.screenX = screenX;
        r.screenY = screenY;
        r.viewW = vw;
        r.viewH = vh;
        r.baseScale = base;
        pending = r;
        return true;
    }

    void reset() {
        synchronized (lock) {
            pending = null;
            active = false;
            release();
        }
    }

    /**
     * @param gray 已转正、缩放后的灰度图；所有权交给本类，不再由调用方释放。
     */
    void onFrame(Mat gray, int tw, int th) {
        if (!available || gray == null) {
            return;
        }
        synchronized (lock) {
            if (pending != null) {
                Request req = pending;
                pending = null;
                boolean ok = init(req, gray, tw, th);
                main.post(() -> listener.onInitResult(ok));
                return;
            }
            if (!active) {
                gray.release();
                return;
            }
            update(gray, tw, th);
        }
    }

    private boolean init(Request req, Mat first, int tw, int th) {
        try {
            release();
            active = false;
            viewW = req.viewW;
            viewH = req.viewH;
            baseScale = req.baseScale;
            double s = Math.max(viewW / (double) tw, viewH / (double) th);
            double ox = (viewW - tw * s) * 0.5;
            double oy = (viewH - th * s) * 0.5;
            float tx = (float) ((req.screenX - ox) / s);
            float ty = (float) ((req.screenY - oy) / s);
            if (tx < 20 || ty < 20 || tx > tw - 20 || ty > th - 20) {
                first.release();
                return false;
            }
            Mat mask = new Mat(first.size(), CvType.CV_8UC1, new Scalar(0));
            int radius = Math.min(130, Math.min(tw, th) / 3);
            Imgproc.circle(mask, new Point(tx, ty), radius, new Scalar(255), -1);
            MatOfPoint corners = new MatOfPoint();
            Imgproc.goodFeaturesToTrack(first, corners, 220, 0.01, 10, mask, 7, false, 0.04);
            mask.release();
            if (corners.rows() < 20) {
                corners.release();
                Mat mask2 = new Mat(first.size(), CvType.CV_8UC1, new Scalar(0));
                int radius2 = Math.min(170, Math.min(tw, th) / 2);
                Imgproc.circle(mask2, new Point(tx, ty), radius2, new Scalar(255), -1);
                corners = new MatOfPoint();
                Imgproc.goodFeaturesToTrack(first, corners, 220, 0.006, 8, mask2, 7, false, 0.04);
                mask2.release();
            }
            int n = corners.rows();
            if (n < 15) {
                corners.release();
                first.release();
                return false;
            }
            prevGray = first;
            prevPts = new MatOfPoint2f(corners.toArray());
            refPts = new MatOfPoint2f(prevPts.toArray());
            corners.release();
            anchor[0] = tx;
            anchor[1] = ty;
            failStreak = 0;
            framesSinceRebase = 0;
            active = true;
            android.util.Log.i("GanFanYu", "plane init features=" + n);
            return true;
        } catch (Throwable t) {
            first.release();
            active = false;
            return false;
        }
    }

    private void update(Mat current, int tw, int th) {
        MatOfPoint2f next = new MatOfPoint2f();
        MatOfByte status = new MatOfByte();
        MatOfFloat err = new MatOfFloat();
        Mat h = null;
        try {
            Video.calcOpticalFlowPyrLK(prevGray, current, prevPts, next, status, err,
                    new Size(21, 21), 3,
                    new TermCriteria(TermCriteria.EPS | TermCriteria.COUNT, 30, 0.01),
                    0, 0.001);

            byte[] st = status.toArray();
            float[] er = err.toArray();
            Point[] pp = prevPts.toArray();
            Point[] np = next.toArray();
            Point[] rp = refPts.toArray();
            int count = Math.min(st.length, Math.min(pp.length, np.length));
            List<Point> nextKeep = new ArrayList<>(count);
            List<Point> refKeep = new ArrayList<>(count);
            for (int i = 0; i < count; i++) {
                if (st[i] == 0 || er[i] > 30f) {
                    continue;
                }
                Point p = np[i];
                if (p.x < -12 || p.y < -12 || p.x > tw + 12 || p.y > th + 12) {
                    continue;
                }
                nextKeep.add(np[i]);
                refKeep.add(rp[i]);
            }

            if (nextKeep.size() < 10) {
                failStreak++;
                if (failStreak >= 12) {
                    lost(current);
                } else {
                    // 宽容期：保留上一组参考点，只把灰度参考帧换成当前帧，
                    // 让她在桌面反光/手挡住一下时不会立刻掉
                    prevGray.release();
                    prevGray = current;
                }
                return;
            }

            Mat hmask = new Mat();
            h = Calib3d.findHomography(
                    new MatOfPoint2f(refKeep.toArray(new Point[0])),
                    new MatOfPoint2f(nextKeep.toArray(new Point[0])),
                    Calib3d.RANSAC, 3.0, hmask, 300, 0.995);
            int inliers = Core.countNonZero(hmask);
            hmask.release();
            if (h == null || h.empty() || inliers < 8) {
                failStreak++;
                if (failStreak >= 12) {
                    lost(current);
                    return;
                }
                prevPts.release();
                prevPts = new MatOfPoint2f(nextKeep.toArray(new Point[0]));
                refPts.release();
                refPts = new MatOfPoint2f(refKeep.toArray(new Point[0]));
                prevGray.release();
                prevGray = current;
                return;
            }
            failStreak = 0;

            MatOfPoint2f a = new MatOfPoint2f(new Point(anchor[0], anchor[1]));
            MatOfPoint2f aOut = new MatOfPoint2f();
            Core.perspectiveTransform(a, aOut, h);
            Point ap = aOut.toArray()[0];

            MatOfPoint2f b = new MatOfPoint2f(new Point(anchor[0] + 12f, anchor[1]));
            MatOfPoint2f bOut = new MatOfPoint2f();
            Core.perspectiveTransform(b, bOut, h);
            Point bp = bOut.toArray()[0];
            float localScale = (float) (Math.hypot(bp.x - ap.x, bp.y - ap.y) / 12f);

            double vs = Math.max(viewW / (double) tw, viewH / (double) th);
            double ox = (viewW - tw * vs) * 0.5;
            double oy = (viewH - th * vs) * 0.5;
            float sx = (float) (ox + ap.x * vs);
            float sy = (float) (oy + ap.y * vs);
            float scale = baseScale * localScale;
            scale = Math.max(0.15f, Math.min(2.6f, scale));
            boolean visible = sx > -viewW * 0.3f && sx < viewW * 1.3f
                    && sy > -viewH * 0.25f && sy < viewH * 1.25f;

            final float fx = sx;
            final float fy = sy;
            final float fs = scale;
            final boolean fv = visible;
            main.post(() -> listener.onTrack(fx, fy, fs, fv));

            framesSinceRebase++;
            if (refKeep.size() < 60 || framesSinceRebase > 150) {
                // 特征少了或跑了太久：以当前帧为新参考，位置/大小连续，避免点耗尽后直接丢失
                android.util.Log.d("GanFanYu", "plane rebase refs=" + refKeep.size());
                anchor[0] = (float) ap.x;
                anchor[1] = (float) ap.y;
                baseScale = scale;
                prevPts.release();
                prevPts = new MatOfPoint2f(nextKeep.toArray(new Point[0]));
                refPts.release();
                refPts = new MatOfPoint2f(nextKeep.toArray(new Point[0]));
                framesSinceRebase = 0;
            } else {
                prevPts.release();
                prevPts = new MatOfPoint2f(nextKeep.toArray(new Point[0]));
                refPts.release();
                refPts = new MatOfPoint2f(refKeep.toArray(new Point[0]));
            }
            prevGray.release();
            prevGray = current;
        } catch (Throwable t) {
            lost(current);
        } finally {
            next.release();
            status.release();
            err.release();
            if (h != null) {
                h.release();
            }
        }
    }

    private void lost(Mat current) {
        active = false;
        release();
        current.release();
        android.util.Log.i("GanFanYu", "plane lost");
        main.post(listener::onLost);
    }

    private void release() {
        if (prevGray != null) {
            prevGray.release();
            prevGray = null;
        }
        if (prevPts != null) {
            prevPts.release();
            prevPts = null;
        }
        if (refPts != null) {
            refPts.release();
            refPts = null;
        }
    }
}
