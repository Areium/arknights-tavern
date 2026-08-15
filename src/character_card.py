"""
SillyTavern 角色卡解析与导入。

支持：
- PNG 角色卡（tEXt 块 "chara" 关键词内嵌 Base64 JSON）
- 纯 JSON 角色卡（v1 扁平字段 / v2 {spec, data} 包装）

产出：
- 规范化角色元数据（name/description/personality/scenario/first_mes/mes_example/tags/creator_notes）
- 干净的卡片图像字节（已剥离内嵌 JSON 块，可作头像）
- 内嵌世界书原始数据（若有 character_book，可交给世界书导入）
"""

import base64
import json
import logging
import re

logger = logging.getLogger(__name__)

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
    if book_data and not book_data.get("entries"):
        # v2 内嵌书也可能在 extensions.world / data.world
        ext = meta.get("extensions") or {}
        world = ext.get("world") if isinstance(ext.get("world"), dict) else None
        book_data = world or None
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
