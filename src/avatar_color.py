"""从角色头像中提取主题配色。"""

import os
import logging
from collections import Counter
from pathlib import Path

import frontmatter
from PIL import Image

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def extract_theme_color(image_path: str | Path) -> str:
    """从 PNG 头像中提取主导饱和色，返回 hex 字符串。

    跳过透明、近白、近黑和低饱和度像素，在剩余像素中
    取出现频率最高的颜色。无法提取时返回默认紫色。
    """
    try:
        img = Image.open(image_path).convert("RGBA")
    except Exception:
        return "#8b5ca8"

    # 缩小到 32x32 以提升性能和降噪
    img = img.resize((32, 32), Image.LANCZOS)
    pixels = list(img.getdata())

    filtered: list[tuple[int, int, int]] = []
    for r, g, b, a in pixels:
        if a < 128:
            continue
        if r > 240 and g > 240 and b > 240:
            continue
        if r < 15 and g < 15 and b < 15:
            continue
        max_c = max(r, g, b)
        min_c = min(r, g, b)
        if max_c - min_c < 30:
            continue
        filtered.append((r, g, b))

    if not filtered:
        # 回退：放宽饱和度限制
        for r, g, b, a in pixels:
            if a < 128:
                continue
            if r > 245 and g > 245 and b > 245:
                continue
            if r < 10 and g < 10 and b < 10:
                continue
            filtered.append((r, g, b))

    if not filtered:
        return "#8b5ca8"

    counter = Counter(filtered)
    (r, g, b), _ = counter.most_common(1)[0]
    return f"#{r:02x}{g:02x}{b:02x}"


def find_avatar_path(name: str) -> str | None:
    """在角色目录下查找默认头像文件（最短文件名的 .png）。"""
    avatar_dir = _REPO_ROOT / "data" / "characters" / name / "avatar"
    if not avatar_dir.is_dir():
        return None
    pngs = sorted(
        [f for f in os.listdir(avatar_dir) if f.lower().endswith(".png")],
        key=lambda f: len(f),
    )
    return str(avatar_dir / pngs[0]) if pngs else None


def find_skin_path(name: str) -> str | None:
    """在角色目录下查找默认立绘文件（最短文件名的 .png）。"""
    skin_dir = _REPO_ROOT / "data" / "characters" / name / "skin"
    if not skin_dir.is_dir():
        return None
    pngs = sorted(
        [f for f in os.listdir(skin_dir) if f.lower().endswith(".png")],
        key=lambda f: len(f),
    )
    return str(skin_dir / pngs[0]) if pngs else None


def get_theme_color(name: str) -> str | None:
    """读取角色文档中已保存的 theme_color（不自动提取）。"""
    index_path = _REPO_ROOT / "data" / "characters" / name / "index.md"
    if not index_path.exists():
        return None
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            raw = f.read()
        post = frontmatter.loads(raw)
        return post.metadata.get("theme_color", "").strip() or None
    except Exception:
        return None


def ensure_theme_color(name: str) -> str | None:
    """确保角色文档中有 theme_color 字段。

    如果已有则直接返回；如果没有则从头像提取并写入 index.md。
    无法处理时返回 None。
    """
    index_path = _REPO_ROOT / "data" / "characters" / name / "index.md"
    if not index_path.exists():
        return None

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            raw = f.read()
        post = frontmatter.loads(raw)
    except Exception:
        logger.warning("无法读取角色文档: %s", name)
        return None

    existing = post.metadata.get("theme_color", "").strip()
    if existing:
        return existing

    avatar = find_avatar_path(name)
    if not avatar:
        return None

    color = extract_theme_color(avatar)
    post.metadata["theme_color"] = color

    try:
        out = frontmatter.dumps(post)
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(out)
        logger.info("已为 %s 提取主题色: %s", name, color)
    except Exception:
        logger.warning("无法写入主题色到 %s", index_path)

    return color
