"""
SillyTavern 角色卡解析与导入。

支持：
- PNG 角色卡（tEXt 块 "chara" 关键词内嵌 Base64 JSON）
- 纯 JSON 角色卡（v1 扁平字段 / v2 {spec, data} 包装）

产出：
- 规范化角色元数据（name/description/personality/scenario/first_mes/mes_example/tags/creator_notes）
- 干净的卡片图像字节（已剥离内嵌 JSON 块，可作头像）
- 内嵌世界书原始数据（若有 character_book，可交给世界书导入）

导入流水线（/api/characters/import 与 /api/worldbook/import 共用）：
- write_character_dir() — 写入 data/characters/<slug>/index.md（frontmatter 含
  first_mes/scenario，供首轮叙述注入）+ 头像
- import_character_card() — 解析 + 写角色 + 导入内嵌世界书
"""

import base64
import json
import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CHARS_DIR = _REPO_ROOT / "data" / "characters"

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class CharacterCardError(ValueError):
    """角色卡解析失败。"""


# ── PNG tEXt 块解析 ──


def _parse_png_chunks(data: bytes):
    """遍历 PNG 块，产出 (type, chunk_data)；支持剥离指定块。"""
    if not data.startswith(_PNG_SIGNATURE):
        return None
    pos = 8
    chunks = []
    while pos + 8 <= len(data):
        (length,) = __import__("struct").unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8].decode("latin-1")
        cdata = data[pos + 8:pos + 8 + length]
        chunks.append((ctype, cdata))
        pos += 12 + length
        if ctype == "IEND":
            break
    return chunks


def _extract_card_from_png(data: bytes):
    """从 PNG 中提取 "chara" tEXt 块并剥离内嵌 JSON，返回 (card_json, clean_png)。"""
    import struct
    import zlib

    chunks = _parse_png_chunks(data)
    if chunks is None:
        return None, None
    card_json = None
    kept = bytearray(_PNG_SIGNATURE)
    for ctype, cdata in chunks:
        if ctype == "tEXt":
            try:
                text = cdata.decode("latin-1")
                if "\x00" in text:
                    keyword, value = text.split("\x00", 1)
                    if keyword == "chara":
                        card_json = json.loads(base64.b64decode(value).decode("utf-8"))
                        continue  # 剥离内嵌 JSON 块
            except Exception:
                pass
        kept += struct.pack(">I", len(cdata)) + ctype.encode("latin-1") + cdata
        kept += zlib.crc32(ctype.encode("latin-1") + cdata).to_bytes(4, "big")
    return card_json, bytes(kept)


# ── JSON 规范化 ──


def _normalize_card(raw: dict) -> dict:
    """ST v1（扁平）/ v2（{spec, data}）统一为扁平元数据字典。"""
    if not isinstance(raw, dict):
        raise CharacterCardError("角色卡 JSON 必须是对象")
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    if not isinstance(data, dict):
        raise CharacterCardError("无法识别角色卡结构（无 data 字段）")
    name = str(data.get("name") or raw.get("name") or "").strip()
    if not name:
        raise CharacterCardError("角色卡缺少 name 字段")
    return {
        "name": name,
        "description": str(data.get("description", "") or ""),
        "personality": str(data.get("personality", "") or ""),
        "scenario": str(data.get("scenario", "") or ""),
        "first_mes": str(data.get("first_mes", "") or ""),
        "mes_example": str(data.get("mes_example", "") or ""),
        "creator_notes": str(data.get("creator_notes", "") or ""),
        "system_prompt": str(data.get("system_prompt", "") or ""),
        "post_history_instructions": str(data.get("post_history_instructions", "") or ""),
        "tags": [str(t) for t in (data.get("tags") or []) if str(t).strip()],
        "creator": str(data.get("creator", "") or ""),
        "character_version": str(data.get("character_version", "") or ""),
        "character_book": data.get("character_book") if isinstance(data.get("character_book"), dict) else None,
        "extensions": data.get("extensions") if isinstance(data.get("extensions"), dict) else None,
    }


# ── 公开入口 ──


def parse_character_card(raw: bytes) -> dict:
    """解析角色卡文件字节，返回规范化元数据 + 干净图像字节。

    Returns:
        {
          "meta": {...扁平字段...},
          "image_bytes": bytes | None,   # 剥离内嵌 JSON 的 PNG（可作头像）
          "book_data": dict | None,      # 内嵌世界书（character_book），可导入
        }
    """
    card_json = None
    image_bytes = None
    if raw.startswith(_PNG_SIGNATURE):
        card_json, image_bytes = _extract_card_from_png(raw)
        if card_json is None:
            raise CharacterCardError("PNG 角色卡中未找到内嵌 chara JSON")
    else:
        # 文本 JSON（可能带 BOM / 前后空白）
        text = raw.decode("utf-8-sig", errors="replace").strip()
        try:
            card_json = json.loads(text)
        except json.JSONDecodeError as e:
            raise CharacterCardError(f"JSON 解析失败: {e}") from e

    meta = _normalize_card(card_json)
    book_data = meta.get("character_book")
    if not (book_data and book_data.get("entries")):
        # v2 内嵌书也可能在 extensions.world / data.world
        ext = meta.get("extensions") or {}
        world = ext.get("world") if isinstance(ext.get("world"), dict) else None
        book_data = (book_data if (book_data and book_data.get("entries"))
                     else (world or None))
    return {
        "meta": meta,
        "image_bytes": image_bytes,
        "book_data": book_data,
    }


def slugify(name: str) -> str:
    """角色目录名：保留中文/字母/数字，其余转下划线，去首尾空白。"""
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", name.strip())
    s = s.strip("._")
    return s or "imported_character"


# ── 角色目录写入（/api/characters/import 与 /api/worldbook/import 共用） ──


def build_index_md(meta: dict) -> str:
    """把规范化角色元数据渲染为 index.md（frontmatter + 正文分节）。

    frontmatter 额外写入 scenario / first_mes：供会话首轮叙述注入
    （开场白与场景设定对应），正文分节保留供角色卡阅读。
    """
    summary = " ".join(meta["description"].split())[:160]
    fm = {"name": meta["name"], "summary": summary, "source": "imported"}
    if meta.get("tags"):
        fm["tags"] = meta["tags"]
    if meta.get("creator"):
        fm["creator"] = meta["creator"]
    if meta.get("character_version"):
        fm["character_version"] = meta["character_version"]
    if meta.get("scenario"):
        fm["scenario"] = meta["scenario"]
    if meta.get("first_mes"):
        fm["first_mes"] = meta["first_mes"]

    parts = []
    if meta["description"]:
        parts.append("# 角色背景\n\n" + meta["description"].strip())
    if meta["personality"]:
        parts.append("## 性格\n\n" + meta["personality"].strip())
    if meta["scenario"]:
        parts.append("## 场景\n\n" + meta["scenario"].strip())
    if meta["first_mes"]:
        parts.append("## 开场白\n\n" + meta["first_mes"].strip())
    if meta["mes_example"]:
        parts.append("## 对话示例\n\n" + meta["mes_example"].strip())
    if meta["creator_notes"]:
        parts.append("## 作者备注\n\n" + meta["creator_notes"].strip())

    return (
        "---\n"
        + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
        + "\n---\n\n"
        + "\n\n".join(parts)
        + "\n"
    )


def write_character_dir(meta: dict, image_bytes: bytes | None,
                        chars_dir: str | Path | None = None) -> dict:
    """把角色卡元数据写入 data/characters/<slug>/ 目录（index.md + 头像）。

    Returns:
        {"name", "slug", "path", "source", "has_avatar"}
    """
    base_dir = Path(chars_dir) if chars_dir else _DEFAULT_CHARS_DIR
    name = meta["name"]
    slug = slugify(name)
    target = base_dir / slug
    if target.exists():
        i = 2
        while (base_dir / f"{slug}_{i}").exists():
            i += 1
        target = base_dir / f"{slug}_{i}"
        slug = target.name
    target.mkdir(parents=True, exist_ok=True)
    (target / "index.md").write_text(build_index_md(meta), encoding="utf-8")

    # 玩家身份档案缓存失效（该角色可能被用作玩家身份）
    try:
        from player_profile import invalidate_profile_cache
        invalidate_profile_cache(name)
    except Exception:
        pass

    avatar_path = None
    if image_bytes:
        avatar_dir = target / "avatar"
        avatar_dir.mkdir(exist_ok=True)
        avatar_path = avatar_dir / f"{slug}.png"
        avatar_path.write_bytes(image_bytes)

    return {
        "name": name,
        "slug": slug,
        "path": f"characters/{slug}",
        "source": "imported",
        "has_avatar": avatar_path is not None,
    }


def import_character_card(raw: bytes, wb_mgr=None, chars_dir: str | Path | None = None,
                          book_name: str | None = None) -> dict:
    """解析角色卡文件并完整导入：角色目录 + 头像 + 内嵌世界书。

    Args:
        raw: 角色卡文件字节（PNG 或 JSON）。
        wb_mgr: WorldBookManager 实例（可空，为空则不导入内嵌世界书）。
        chars_dir: 角色数据目录（默认 data/characters）。
        book_name: 内嵌世界书命名（默认 "<角色名>（角色卡）"）。

    Returns:
        {"character": {...}, "worldbook": {...} | None}
    """
    parsed = parse_character_card(raw)
    meta = parsed["meta"]
    character = write_character_dir(meta, parsed["image_bytes"], chars_dir=chars_dir)

    book_summary = None
    if parsed["book_data"] and wb_mgr is not None:
        book, _report = wb_mgr.import_book(
            book_name or f"{meta['name']}（角色卡）", parsed["book_data"])
        book_summary = {
            "id": book.id,
            "name": book.name,
            "source": book.source,
            "entry_count": len(book.entries),
        }
    return {"character": character, "worldbook": book_summary}
