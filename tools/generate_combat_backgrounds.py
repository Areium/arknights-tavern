#!/usr/bin/env python3
"""generate_combat_backgrounds.py — 战斗背景 AI 生成工具。

工作流（详见 docs/combat-background-prompts.md）：

  --scaffold   扫描遭遇战(background)与地点(combat_bg)引用了、但
               data/combat/backgrounds/ 下还不存在的背景 ID，自动创建
               index.md 并按地点文档拼好提示词草稿，供人工审修。
  --dry-run    打印所有缺图背景的完整提示词，方便粘贴到任意生图工具。
  （无参数）   读取 config/image_config.json，调用 OpenAI 兼容的
               images/generations 接口为所有缺图背景批量出图。

常用附加参数：
  --only <bg_id>   只处理指定背景
  --force          已有图也重新生成（默认只处理缺图的）
"""

import argparse
import base64
import json
import logging
import re
import sys
from pathlib import Path

import frontmatter
import httpx

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BG_ROOT = _PROJECT_ROOT / "data" / "combat" / "backgrounds"
_ENC_ROOT = _PROJECT_ROOT / "data" / "combat" / "encounters"
_LOC_ROOT = _PROJECT_ROOT / "data" / "environment" / "Location"
_CONFIG_PATH = _PROJECT_ROOT / "config" / "image_config.json"

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")

_NEGATIVE_PROMPT = (
    "people, characters, text, watermark, logo, UI elements, "
    "bright sunny colors, close-up, first-person view"
)

# 与 docs/combat-background-prompts.md 第 2 节模板保持一致
_PROMPT_TEMPLATE = (
    "Arknights style anime background art, {scene}, "
    "slightly elevated camera angle looking down at an open empty "
    "ground plane in the center, muted cold grey-blue palette, "
    "dark atmospheric lighting, heavy vignette, "
    "no characters, no text, no UI, painterly matte painting quality, 16:9"
)


# ── 背景条目读写 ──

def list_backgrounds() -> list[Path]:
    if not _BG_ROOT.is_dir():
        return []
    return sorted(p for p in _BG_ROOT.iterdir() if (p / "index.md").is_file())


def has_image(bg_dir: Path) -> bool:
    try:
        meta = frontmatter.load(bg_dir / "index.md").metadata
    except Exception:
        meta = {}
    image = str(meta.get("image") or "")
    if image and (bg_dir / image).is_file():
        return True
    return any(p.suffix.lower() in _IMAGE_EXTS for p in bg_dir.iterdir() if p.is_file())


def load_prompt(bg_dir: Path) -> str:
    meta = frontmatter.load(bg_dir / "index.md").metadata
    return str(meta.get("prompt") or "")


def set_image_field(bg_dir: Path, filename: str):
    index = bg_dir / "index.md"
    post = frontmatter.load(index)
    post.metadata["image"] = filename
    with open(index, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))


# ── --scaffold：为被引用但缺失的背景建草稿 ──

def _referenced_bg_ids() -> dict[str, str]:
    """收集被引用的背景 ID → 来源描述（encounter 文件或 location index.md 路径）。"""
    refs: dict[str, str] = {}
    for enc in sorted(_ENC_ROOT.glob("*.md")):
        try:
            bg = str(frontmatter.load(enc).metadata.get("background") or "")
        except Exception:
            continue
        if bg:
            refs.setdefault(bg, f"encounter:{enc.stem}")
    if _LOC_ROOT.is_dir():
        for index in sorted(_LOC_ROOT.rglob("index.md")):
            try:
                meta = frontmatter.load(index).metadata
            except Exception:
                continue
            bg = str(meta.get("combat_bg") or "")
            if bg:
                refs.setdefault(bg, f"location:{index}")
    return refs


def _scene_text_from_location(index_path: Path) -> str:
    """取地点文档的「描述」第一段 + 「视觉」段落，拼成场景草稿。"""
    try:
        content = frontmatter.load(index_path).content
    except Exception:
        return ""
    desc = ""
    m = re.search(r"# 描述\s*\n+(.+?)(?:\n\s*\n|$)", content, re.S)
    if m:
        desc = m.group(1).strip().replace("\n", "")
    visual = ""
    m = re.search(r"### 视觉\s*\n+(.+?)(?:\n\s*\n|$)", content, re.S)
    if m:
        visual = m.group(1).strip().replace("\n", "")
    return "。".join(t for t in (desc, visual) if t)


def scaffold() -> int:
    refs = _referenced_bg_ids()
    created = 0
    for bg_id, source in sorted(refs.items()):
        bg_dir = _BG_ROOT / bg_id
        if (bg_dir / "index.md").is_file():
            continue
        bg_dir.mkdir(parents=True, exist_ok=True)

        scene = ""
        if source.startswith("location:"):
            scene = _scene_text_from_location(Path(source[len("location:"):]))
        if not scene:
            scene = "TODO: 用 1-2 句英文描述场景主体与远景地标"

        post = frontmatter.Post("", handler=None)
        post.metadata = {
            "name": bg_id,
            "summary": "TODO: 一句话摘要（≤50 字）",
            "type": "combat_background",
            "image": "",
            # 中文场景描述多数生图模型也能读，但建议人工改为英文
            "prompt": _PROMPT_TEMPLATE.format(scene=scene),
            "negative_prompt": _NEGATIVE_PROMPT,
            "source": "ai",
            "size": "1920x1080",
        }
        with open(bg_dir / "index.md", "w", encoding="utf-8") as f:
            f.write(frontmatter.dumps(post))
        logger.info("已创建 %s（来源 %s）", bg_dir, source)
        created += 1

    if not created:
        logger.info("没有缺失的背景条目")
    return created


# ── --dry-run：打印提示词 ──

def dry_run(targets: list[Path]):
    for bg_dir in targets:
        prompt = load_prompt(bg_dir)
        print(f"\n{'=' * 70}\n[{bg_dir.name}]  →  {bg_dir}\n{'=' * 70}")
        print(prompt or "（prompt 字段为空，请先填写 index.md）")
        print(f"\n-- negative --\n{_NEGATIVE_PROMPT}")


# ── API 生成 ──

def _load_config() -> dict:
    if not _CONFIG_PATH.is_file():
        sys.exit(
            f"未找到 {_CONFIG_PATH}\n"
            "请复制 config/image_config.example.json 并填写 API 信息，"
            "或使用 --dry-run 导出提示词手动生成。"
        )
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_one(cfg: dict, bg_dir: Path):
    prompt = load_prompt(bg_dir)
    if not prompt:
        logger.warning("[%s] prompt 为空，跳过", bg_dir.name)
        return

    resp = httpx.post(
        f"{cfg['base_url'].rstrip('/')}/images/generations",
        headers={"Authorization": f"Bearer {cfg['api_key']}"},
        json={
            "model": cfg["model"],
            "prompt": prompt,
            "size": cfg.get("size", "1920x1080"),
            "response_format": cfg.get("response_format", "b64_json"),
        },
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()["data"][0]

    if data.get("b64_json"):
        raw = base64.b64decode(data["b64_json"])
        filename = "bg.png"
    elif data.get("url"):
        raw = httpx.get(data["url"], timeout=180).content
        filename = "bg.png"
    else:
        raise ValueError(f"接口返回缺少图片数据: {list(data.keys())}")

    (bg_dir / filename).write_bytes(raw)
    set_image_field(bg_dir, filename)
    logger.info("[%s] 已生成 %s", bg_dir.name, filename)


# ── 入口 ──

def main():
    parser = argparse.ArgumentParser(description="战斗背景 AI 生成工具")
    parser.add_argument("--scaffold", action="store_true", help="为被引用但缺失的背景建提示词草稿")
    parser.add_argument("--dry-run", action="store_true", help="只打印提示词，不调用 API")
    parser.add_argument("--only", metavar="BG_ID", help="只处理指定背景")
    parser.add_argument("--force", action="store_true", help="已有图也重新生成")
    args = parser.parse_args()

    if args.scaffold:
        scaffold()
        # 单独使用 --scaffold 时只建草稿，不进入生成流程
        if not (args.dry_run or args.only or args.force):
            return

    targets = list_backgrounds()
    if args.only:
        targets = [d for d in targets if d.name == args.only]
        if not targets:
            sys.exit(f"背景不存在: {args.only}")
    if not args.force:
        targets = [d for d in targets if not has_image(d)]

    if not targets:
        logger.info("没有待处理的背景（缺图条目）")
        return

    if args.dry_run:
        dry_run(targets)
        return

    cfg = _load_config()
    for bg_dir in targets:
        try:
            generate_one(cfg, bg_dir)
        except Exception as e:
            logger.error("[%s] 生成失败: %s", bg_dir.name, e)


if __name__ == "__main__":
    main()
