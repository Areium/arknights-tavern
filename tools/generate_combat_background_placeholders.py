#!/usr/bin/env python3
"""程序化生成战斗背景占位图（无需 AI 生图接口）。

为 data/combat/backgrounds/ 下的剧情背景生成与主题一致的程序化图：
渐变天空 + 剪影地标 + 中央开阔地面 + 重暗角 + 氛围粒子。
用于在未配置 config/image_config.json（AI 生图接口）时，替换掉测试/占位图，
让战斗背景至少与剧情（风雪过境 · 谢拉格雪山 / 整合运动 · 荒野废墟）匹配。

用法：
    python tools/generate_combat_background_placeholders.py [--only <bg_id>] [--seed N]
"""

import argparse
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
BG_ROOT = ROOT / "data" / "combat" / "backgrounds"
W, H = 1920, 1080


# ── 基础工具 ──

def _vignette(arr: np.ndarray, strength: float = 0.85) -> np.ndarray:
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w * 0.5, h * 0.46
    d = np.sqrt(((xx - cx) / (w * 0.5)) ** 2 + ((yy - cy) / (h * 0.5)) ** 2)
    mask = 1.0 - strength * np.clip((d - 0.28) / 1.05, 0.0, 1.0)
    return (arr.astype(np.float32) * mask[..., None]).clip(0, 255).astype(np.uint8)


def _gradient(top, bottom, h=H, w=W) -> np.ndarray:
    t = np.linspace(0.0, 1.0, h).reshape(h, 1, 1)
    top = np.array(top, dtype=np.float32).reshape(1, 1, 3)
    bottom = np.array(bottom, dtype=np.float32).reshape(1, 1, 3)
    col = top * (1.0 - t) + bottom * t  # (h, 1, 3)
    return np.repeat(col, w, axis=1)  # (h, w, 3)


def _to_image(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _skyline(rng, n, base_y, amp, min_y):
    pts = []
    step = W / (n - 1)
    for i in range(n):
        x = i * step
        y = base_y - rng.uniform(0, amp)
        pts.append((x, max(min_y, y)))
    return pts


def _draw_skyline(draw, rng, n, base_y, amp, min_y, color):
    pts = _skyline(rng, n, base_y, amp, min_y)
    pts += [(W, H), (0, H)]
    draw.polygon(pts, fill=color)


def _ground_texture(arr, y0, color_a, color_b, rng, n_streaks=60):
    """在 y0 以下铺一层带水平雪纹/尘纹的地面。"""
    h = arr.shape[0]
    band = np.linspace(0.0, 1.0, h - y0)[:, None, None]
    base = np.array(color_a, dtype=np.float32)
    grad = np.array(color_b, dtype=np.float32)
    arr[y0:] = base[None, None, :] * (1 - band) + grad[None, None, :] * band
    for _ in range(n_streaks):
        y = rng.randint(y0, h - 4)
        x0 = rng.randint(0, W)
        length = rng.randint(80, 320)
        alpha = rng.uniform(0.04, 0.12)
        arr[y:y + 2, x0:x0 + length] = arr[y:y + 2, x0:x0 + length] * (1 - alpha) +             np.array([255, 255, 255], dtype=np.float32) * alpha
    return arr


def _cracks(arr, y0, rng, n=70, color=(20, 20, 20), alpha=0.25):
    h = arr.shape[0]
    for _ in range(n):
        x = rng.randint(0, W)
        y = rng.randint(y0, h - 1)
        length = rng.randint(30, 160)
        dy = rng.choice([-1, 1]) if rng.random() < 0.5 else 0
        for i in range(length):
            xx = int(x + rng.uniform(-1.5, 1.5))
            yy = int(y + i * 0.15 * dy)
            if 0 <= xx < W and y0 <= yy < h:
                arr[yy, xx] = arr[yy, xx] * (1 - alpha) + np.array(color) * alpha
    return arr


def _snow(arr, rng, n=500, color=(255, 255, 255)):
    h, w = arr.shape[:2]
    for _ in range(n):
        x = rng.randint(0, w - 1)
        y = rng.randint(0, h - 1)
        r = rng.uniform(0.5, 2.0)
        yy, xx = np.ogrid[:h, :w]
        mask = (xx - x) ** 2 + (yy - y) ** 2 <= r ** 2
        arr[mask] = arr[mask] * 0.7 + np.array(color) * 0.3
    return arr


def _glow(arr, x, y, r, color, strength=0.5):
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
    mask = np.clip(1.0 - d / r, 0.0, 1.0) * strength
    return arr * (1 - mask[..., None]) + np.array(color, dtype=np.float32) * mask[..., None]


# ── 场景 ──

def make_snow_mountain(seed):
    rng = random.Random(seed)
    arr = _gradient((92, 108, 128), (176, 192, 206))
    img = _to_image(arr)
    draw = ImageDraw.Draw(img)
    # 远景雪山 + 圣山主峰
    _draw_skyline(draw, rng, 24, int(H * 0.60), 240, int(H * 0.30), (128, 142, 158))
    _draw_skyline(draw, rng, 20, int(H * 0.64), 200, int(H * 0.34), (96, 112, 132))
    _draw_skyline(draw, rng, 16, int(H * 0.68), 150, int(H * 0.40), (68, 84, 104))
    # 中央圣山主峰（高耸）
    draw.polygon([(W * 0.42, H * 0.62), (W * 0.50, H * 0.20), (W * 0.58, H * 0.62)],
                 fill=(74, 90, 108))
    draw.polygon([(W * 0.46, H * 0.58), (W * 0.50, H * 0.20), (W * 0.54, H * 0.58)],
                 fill=(220, 230, 240))  # 雪顶
    # 两侧雪松
    for x in [W * 0.04, W * 0.08, W * 0.13, W * 0.88, W * 0.92, W * 0.96]:
        hgt = rng.uniform(120, 200)
        wdt = rng.uniform(46, 72)
        draw.polygon([(x, H * 0.68 - hgt), (x - wdt, H * 0.68), (x + wdt, H * 0.68)],
                     fill=(42, 56, 66))
        draw.polygon([(x, H * 0.68 - hgt * 0.55), (x - wdt * 0.7, H * 0.68 - hgt * 0.25),
                      (x + wdt * 0.7, H * 0.68 - hgt * 0.25)], fill=(52, 68, 80))
    arr = np.asarray(img, dtype=np.float32)
    # 中央开阔雪地（网格区）
    arr = _ground_texture(arr, int(H * 0.66), (196, 206, 218), (224, 232, 240), rng, 50)
    arr = _snow(arr, rng, 420)
    arr = _vignette(arr, 0.82)
    return _to_image(arr)


def make_wasteland_ruins(seed):
    rng = random.Random(seed)
    arr = _gradient((62, 56, 50), (148, 128, 106))
    img = _to_image(arr)
    draw = ImageDraw.Draw(img)
    # 远景废墟剪影（坍塌建筑 + 锈蚀机械）
    _draw_skyline(draw, rng, 26, int(H * 0.60), 180, int(H * 0.34), (70, 62, 54))
    for bx, bw, bh in [(W * 0.16, 90, 160), (W * 0.30, 130, 200), (W * 0.52, 70, 120),
                       (W * 0.66, 110, 170), (W * 0.82, 80, 130)]:
        top = H * 0.62 - bh
        draw.rectangle([bx, top, bx + bw, H * 0.62], fill=(48, 42, 37))
        # 断口
        for _ in range(3):
            nx = bx + rng.uniform(0, bw - 10)
            ny = top + rng.uniform(0, bh * 0.5)
            draw.rectangle([nx, ny, nx + 8, ny + rng.uniform(4, 14)], fill=(94, 84, 72))
    # 起重机/天线剪影
    cx = W * 0.42
    draw.line([(cx, H * 0.62), (cx, H * 0.40)], fill=(40, 36, 32), width=6)
    draw.line([(cx, H * 0.42), (cx + 90, H * 0.52)], fill=(40, 36, 32), width=6)
    arr = np.asarray(img, dtype=np.float32)
    # 中央开裂地面（网格区）
    arr = _ground_texture(arr, int(H * 0.64), (74, 66, 58), (96, 86, 74), rng, 40)
    arr = _cracks(arr, int(H * 0.64), rng, 80)
    # 橙色警示灯
    arr = _glow(arr, W * 0.30, H * 0.56, 40, (210, 130, 40), 0.55)
    arr = _glow(arr, W * 0.68, H * 0.52, 30, (200, 120, 40), 0.5)
    # 尘雾带
    arr[int(H * 0.55):int(H * 0.62)] *= 0.82
    arr = _vignette(arr, 0.85)
    return _to_image(arr)


def make_default_wilderness(seed):
    rng = random.Random(seed)
    arr = _gradient((66, 72, 82), (138, 142, 146))
    img = _to_image(arr)
    draw = ImageDraw.Draw(img)
    # 远景碎石 + 工业残骸
    _draw_skyline(draw, rng, 22, int(H * 0.62), 150, int(H * 0.38), (58, 64, 70))
    for bx, bw, bh in [(W * 0.12, 70, 90), (W * 0.36, 100, 120), (W * 0.62, 80, 100), (W * 0.84, 60, 80)]:
        draw.ellipse([bx, H * 0.62 - bh, bx + bw, H * 0.62], fill=(50, 56, 62))
    arr = np.asarray(img, dtype=np.float32)
    arr = _ground_texture(arr, int(H * 0.64), (78, 74, 68), (100, 96, 88), rng, 40)
    arr = _cracks(arr, int(H * 0.64), rng, 60, (30, 30, 28), 0.3)
    # 琥珀色地平线微光
    arr = _glow(arr, W * 0.5, H * 0.60, 500, (180, 120, 50), 0.18)
    arr = _vignette(arr, 0.85)
    return _to_image(arr)


SCENES = {
    "snow_mountain": (make_snow_mountain, "雪山战场"),
    "wasteland_ruins": (make_wasteland_ruins, "荒野废墟"),
    "default": (make_default_wilderness, "默认战场"),
}


def _set_image(bg_dir: Path, filename: str):
    """精确替换 image/source 行，保留 frontmatter 注释块与正文。"""
    import re
    index = bg_dir / "index.md"
    text = index.read_text(encoding="utf-8")
    if re.search(r"(?m)^image:", text):
        text = re.sub(r"(?m)^image:.*$", 'image: "' + filename + '"', text, count=1)
    else:
        text = text.replace("---\n", '---\nimage: "' + filename + '"\n', 1)
    if re.search(r"(?m)^source:", text):
        text = re.sub(r"(?m)^source:.*$", "source: placeholder", text, count=1)
    index.write_text(text, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", metavar="BG_ID")
    ap.add_argument("--seed", type=int, default=20260815)
    args = ap.parse_args()

    targets = [k for k in SCENES if not args.only or k == args.only]
    for bg_id in targets:
        bg_dir = BG_ROOT / bg_id
        bg_dir.mkdir(parents=True, exist_ok=True)
        fn, name = SCENES[bg_id]
        img = fn(args.seed + hash(bg_id) % 1000)
        out = bg_dir / "bg.jpg"
        img.save(out, "JPEG", quality=90)
        _set_image(bg_dir, "bg.jpg")
        print(f"[{bg_id}] {name} -> {out}")


if __name__ == "__main__":
    main()
