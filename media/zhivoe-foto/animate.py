#!/usr/bin/env python3
"""
"Оживление" фотографии: мягкая лицевая анимация (дыхание, моргание, взгляд,
микродвижение головы) на основе warp-поля + сборка видео через ffmpeg.

Работаем на половинном разрешении исходника (1536x2048), отдаём 1080x1440.
"""
import math
import subprocess
import sys

import numpy as np
from PIL import Image, ImageFilter
from scipy.ndimage import map_coordinates

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

SRC = "photo/original.jpg"
OUT_MP4 = "photo/portrait_alive.mp4"
OUT_GIF = "photo/portrait_alive_preview.gif"

S = 2                      # downscale factor for processing
T = 6.0                    # loop duration, sec
FPS = 24
NF = int(T * FPS)
OUT_SIZE = (1080, 1440)    # final video size

img = Image.open(SRC).convert("RGB")
W, H = img.size[0] // S, img.size[1] // S          # 1536 x 2048
base = np.asarray(img.resize((W, H), Image.LANCZOS), dtype=np.float32) / 255.0

# ---------------------------------------------------------------- landmarks
# (полуразрешение: исходные координаты поделены на 2)
EYE_R = (581.5, 990.5)     # правый глаз (со стороны зрителя), зрачок
EYE_L = (892.0, 991.0)     # левый глаз
IRIS_R = 19.0              # радиус радужки, px
PUPIL_R = 8.0

yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ------------------------------------------------------------- маски/веса
# голова (шлем + лицо + волосы) — мягкий суперэллипс
hx, hy = 700.0, 880.0
hd = np.sqrt(((xx - hx) / 470.0) ** 2 + ((yy - hy) / 610.0) ** 2)
W_HEAD = np.exp(-(hd ** 4) * 1.6) * smoothstep(1600.0, 1430.0, yy)
W_HEAD = W_HEAD.astype(np.float32)

# торс/плечи — дыхание
W_TORSO = smoothstep(1500.0, 1720.0, yy).astype(np.float32)

# чёлка — очень лёгкое покачивание
W_HAIR = (np.exp(-(((yy - 830.0) / 190.0) ** 2)) *
          smoothstep(300.0, 470.0, np.abs(xx - 730.0)) * 0.0).astype(np.float32)
W_HAIR = (np.exp(-(((yy - 830.0) / 170.0) ** 2)) *
          np.exp(-(((xx - 730.0) / 330.0) ** 4))).astype(np.float32)


def eye_weights(cx, cy, ax=72.0, ay=58.0):
    u = (xx - cx) / ax
    v = (yy - cy) / ay
    return np.exp(-(u ** 6) - (v ** 4) * 0.9).astype(np.float32)


W_EYE_R = eye_weights(*EYE_R)
W_EYE_L = eye_weights(*EYE_L)


def iris_weight(cx, cy, r=IRIS_R):
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    return (1.0 / (1.0 + np.exp(np.clip((d - r) / 4.0, -30, 30)))).astype(np.float32)


W_IRIS_R = iris_weight(*EYE_R)
W_IRIS_L = iris_weight(*EYE_L)


def pupil_weight(cx, cy, r=PUPIL_R):
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    return (1.0 / (1.0 + np.exp(np.clip((d - r) / 3.0, -30, 30)))).astype(np.float32)


# рот: уголки + центр (координаты полуразрешения)
MOUTH_C = (740.0, 1262.0)
MOUTH_L = (628.0, 1252.0)
MOUTH_R = (860.0, 1250.0)


def blob(cx, cy, sx, sy):
    return np.exp(-(((xx - cx) / sx) ** 2 + ((yy - cy) / sy) ** 2)).astype(np.float32)


W_MOUTH = (blob(*MOUTH_L, 20.0, 16.0) + blob(*MOUTH_R, 20.0, 16.0))
W_MOUTH_UP = blob(*MOUTH_L, 26.0, 15.0) + blob(*MOUTH_R, 26.0, 15.0)
W_JAW = blob(745.0, 1330.0, 85.0, 34.0)
W_CHEEK = blob(640.0, 1160.0, 62.0, 48.0) + blob(850.0, 1160.0, 62.0, 48.0)

# ---------------------------------------------------------------- анимация
BLINKS = (0.85, 3.85)       # моменты моргания (не на границе цикла)


def blink_amount(t):
    k = 0.0
    for s in BLINKS:
        p = (t - s) / 0.26
        if 0.0 < p < 1.0:
            k = max(k, math.sin(math.pi * p) ** 1.4)
    return k


def render(t, seed=0):
    if True:
        ph = 2.0 * math.pi * t / T

        # --- голова: микродвижение + наклон -----------------------------
        tx = 2.9 * math.sin(ph) + 0.9 * math.sin(ph * 2.0 + 0.9)
        ty = 2.1 * math.sin(ph * 2.0 + 1.7) - 1.0 * math.sin(ph)
        th = 0.0034 * math.sin(ph + 0.5)

        dxs = -(tx - th * (yy - hy)) * W_HEAD
        dys = -(ty + th * (xx - hx)) * W_HEAD

        # --- дыхание ----------------------------------------------------
        br = 1.9 * math.sin(ph * 2.0) + 0.5 * math.sin(ph)
        dys = dys - br * W_TORSO
        dxs = dxs - 0.35 * br * (xx - 760.0) / 600.0 * W_TORSO

        # --- чёлка ------------------------------------------------------
        sw = 1.1 * np.sin(ph * 3.0 + (xx - 730.0) * 0.004) + 0.4 * math.sin(ph * 2.0)
        dxs = dxs - sw * W_HAIR

        # --- взгляд -----------------------------------------------------
        gx = 3.4 * math.sin(ph) + 1.3 * math.sin(ph * 2.0 + 1.1)
        gy = 0.9 * math.sin(ph * 2.0 + 0.4)
        dxs = dxs - gx * W_IRIS_R - gx * W_IRIS_L
        dys = dys - gy * W_IRIS_R - gy * W_IRIS_L

        # --- зрачок: сужение/расширение ---------------------------------
        dl = 0.045 * math.sin(ph + 2.2) + 0.02 * math.sin(ph * 3.0)
        for (cx, cy) in (EYE_R, EYE_L):
            pw = pupil_weight(cx, cy)
            dxs = dxs - (xx - cx) * dl * pw
            dys = dys - (yy - cy) * dl * pw

        # --- микро-улыбка / рот ----------------------------------------
        sm = 0.5 + 0.5 * math.sin(ph * 2.0 - 0.6)          # 0..1
        lifting = 0.85 * sm                                 # подъём уголков
        dxs = dxs - 0.28 * sm * (xx - 740.0) / 130.0 * W_MOUTH
        dys = dys - lifting * W_MOUTH_UP
        dys = dys - 0.40 * sm * W_CHEEK
        dys = dys + 0.35 * sm * W_JAW                       # лёгкое раскрытие

        # --- моргание ---------------------------------------------------
        k = 0.75 * blink_amount(t) + 0.05 + 0.03 * math.sin(ph * 2.0 + 0.7)
        k = min(k, 0.95)
        for w_eye, (cx, cy) in ((W_EYE_R, EYE_R), (W_EYE_L, EYE_L)):
            dys = dys + k * 15.0 * np.tanh((cy - yy) / 21.0) * w_eye

        # --- сэмплирование ----------------------------------------------
        map_x = xx + dxs
        map_y = yy + dys
        out = np.empty_like(base)
        for c in range(3):
            out[..., c] = map_coordinates(base[..., c], [map_y, map_x],
                                          order=1, mode="nearest")

        # --- свет: лёгкое «шевеление» освещения -------------------------
        light = 1.0 + 0.016 * math.sin(ph + 0.3) + 0.010 * math.sin(ph * 2.0 + 1.9)
        grad = (1.0 + 0.020 * math.sin(ph + 1.2) * (xx / W - 0.5) * 2.0)
        out *= light
        out *= grad[..., None]

        # микро-улыбка: чуть больше света на губах
        out *= (1.0 + 0.030 * sm * W_CHEEK + 0.020 * sm * W_JAW)[..., None]

        # тень от опускающегося века — «полуприкрытый» взгляд
        if k > 0.02:
            for (cx, cy) in (EYE_R, EYE_L):
                lid = np.exp(-((yy - (cy - 9.0 * k)) ** 2) / (7.0 ** 2)) * \
                      np.exp(-(((xx - cx) / 26.0) ** 4))
                out *= (1.0 - 0.35 * k * lid)[..., None]

        # тонкая «плёнка»: зерно + микро-дрожание, чтобы кадр не был стерильным
        rng = np.random.default_rng(1000 + seed)
        grain = rng.normal(0.0, 0.0055, (H, W, 1)).astype(np.float32)
        out += grain

        frame = Image.fromarray(np.clip(out * 255.0, 0, 255).astype(np.uint8))
        frame = frame.resize(OUT_SIZE, Image.LANCZOS)
        frame = frame.filter(ImageFilter.UnsharpMask(radius=1.6, percent=55, threshold=2))
        return frame, (k, gx, tx, ty)


def frames():
    for i in range(NF):
        yield render(i / FPS, i)[0]


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        for t in [0.0, 1.0, 1.15, 3.0]:
            fr, dbg = render(t, int(t * 100))
            fr.save(f"photo/test_{t:.2f}.png")
            print(t, dbg)
        return
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{OUT_SIZE[0]}x{OUT_SIZE[1]}", "-r", str(FPS), "-i", "-",
           "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "16",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           OUT_MP4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i, fr in enumerate(frames()):
        proc.stdin.write(fr.tobytes())
        if i % 24 == 0:
            print(f"frame {i}/{NF}", flush=True)
    proc.stdin.close()
    proc.wait()
    print("mp4 done", proc.returncode)


if __name__ == "__main__":
    main()
