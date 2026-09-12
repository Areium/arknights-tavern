"""复现角色卡导入问题：验证 parse_character_card / parse_lorebook / PNG 提取行为。"""
import base64
import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from character_card import parse_character_card
from world_book import parse_lorebook

# ── 模拟"妮芙芙"风格 v2 角色卡 ──
CARD = {
    "spec": "chara_card_v2",
    "spec_version": "2.0",
    "data": {
        "name": "妮芙芙",
        "description": "阿卡迪亚魔法学院的学生，性格活泼。",
        "personality": "开朗、好奇、偶尔冒失。",
        "scenario": "深夜的阿卡迪亚魔法学院走廊，妮芙芙抱着魔法书与你相遇。",
        "first_mes": "「啊！这个时间还有人在学院里游荡……你也是睡不着吗？」她抱着书歪了歪头。",
        "mes_example": "<START>\n{{user}}: 你好\n{{char}}: 你好呀！",
        "creator": "test",
        "character_version": "1.0",
        "character_book": {
            "name": "阿卡迪亚魔法学院",
            "entries": [
                {
                    "keys": ["阿卡迪亚", "学院"],
                    "content": "阿卡迪亚魔法学院核心设定：四大塔学舍，禁忌魔法研究。",
                    "comment": "阿卡迪亚魔法学院核心设定",
                    "constant": False,
                    "selective": True,
                    "insertion_order": 1,
                    "depth": 4,
                    "scanDepth": 4,
                    "probability": 100,
                    "useProbability": True,
                    "extensions": {},
                },
                {
                    "keys": ["炎之塔"],
                    "content": "炎之塔学舍：火系魔法专精。",
                    "comment": "炎之塔学舍设定",
                    "constant": False,
                    "insertion_order": 1,
                },
            ],
        },
        "extensions": {},
    },
}


def make_png_with_chara(card_json: dict) -> bytes:
    """构造含 chara tEXt 块的合法 PNG（1x1 像素）。"""
    def chunk(ctype: str, cdata: bytes) -> bytes:
        return (struct.pack(">I", len(cdata)) + ctype.encode("latin-1")
                + cdata + zlib.crc32(ctype.encode("latin-1") + cdata).to_bytes(4, "big"))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1 RGB
    raw = b"\x00" + b"\xff\x00\x00"  # filter 0 + 1 px
    idat = zlib.compress(raw)
    text = "chara\x00" + base64.b64encode(json.dumps(card_json, ensure_ascii=False).encode("utf-8")).decode("latin-1")
    return (b"\x89PNG\r\n\x1a\n" + chunk("IHDR", ihdr) + chunk("tEXt", text.encode("latin-1"))
            + chunk("IDAT", idat) + chunk("IEND", b""))


def main():
    print("=== 1. JSON 角色卡 parse_character_card ===")
    parsed = parse_character_card(json.dumps(CARD, ensure_ascii=False).encode("utf-8"))
    print("meta keys:", sorted(parsed["meta"].keys()))
    print("name:", parsed["meta"]["name"])
    print("first_mes:", parsed["meta"]["first_mes"][:30])
    print("book_data entries:", len(parsed["book_data"]["entries"]) if parsed["book_data"] else None)

    print("\n=== 2. PNG 角色卡 parse_character_card ===")
    png = make_png_with_chara(CARD)
    parsed_png = parse_character_card(png)
    print("image_bytes:", len(parsed_png["image_bytes"]), "bytes (应为 PNG)")
    print("name:", parsed_png["meta"]["name"])
    print("book entries:", len(parsed_png["book_data"]["entries"]))

    print("\n=== 3. parse_lorebook(角色卡内嵌书) ===")
    entries, report = parse_lorebook(parsed["book_data"])
    print("imported:", report.imported, "source_format:", report.source_format)
    for e in entries:
        print(" -", e.name, "| keys:", e.trigger_keys)

    print("\n=== 4. parse_lorebook(整张角色卡 JSON) ===")
    entries2, report2 = parse_lorebook(CARD)
    print("imported:", report2.imported, "source_format:", report2.source_format)

    print("\n=== 5. 模拟当前 /api/worldbook/import 对 PNG 的处理（文本解码）===")
    text = png.decode("utf-8", errors="replace")
    entries3, report3 = parse_lorebook(text)
    print("imported:", report3.imported, "warnings:", report3.warnings[:2])

    print("\n=== 6. /api/characters 字段形态（DocumentInfo.to_dict）===")
    print("字段:", sorted(parsed["meta"].keys()))
    print("注意: list_documents 返回 title 而非 name —— 前端 c.name 为 undefined")


if __name__ == "__main__":
    main()
