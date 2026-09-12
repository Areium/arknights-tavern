"""全流程验证：角色卡导入（PNG/JSON）→ 世界书 + 角色 → 玩家身份注入。"""
import base64
import json
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from character_card import (CharacterCardError, import_character_card,
                            parse_character_card, write_character_dir)
from document_manager import DocumentManager
from player_profile import load_player_profile
from world_book import WorldBookManager, parse_lorebook

CARD = {
    "spec": "chara_card_v2",
    "spec_version": "2.0",
    "data": {
        "name": "妮芙芙",
        "description": "阿卡迪亚魔法学院的学生，性格活泼。",
        "personality": "开朗、好奇、偶尔冒失。",
        "scenario": "深夜的阿卡迪亚魔法学院走廊，妮芙芙抱着魔法书与你相遇。",
        "first_mes": "「啊！这个时间还有人在学院里游荡……你也是睡不着吗？」",
        "mes_example": "<START>\n{{user}}: 你好\n{{char}}: 你好呀！",
        "creator": "test",
        "character_version": "1.0",
        "character_book": {
            "name": "阿卡迪亚魔法学院",
            "entries": [
                {"keys": ["阿卡迪亚", "学院"], "content": "阿卡迪亚魔法学院核心设定。",
                 "comment": "阿卡迪亚魔法学院核心设定", "insertion_order": 1},
                {"keys": ["炎之塔"], "content": "炎之塔学舍：火系魔法专精。",
                 "comment": "炎之塔学舍设定", "insertion_order": 1},
            ],
        },
        "extensions": {},
    },
}


def make_png_with_chara(card_json: dict) -> bytes:
    def chunk(ctype: str, cdata: bytes) -> bytes:
        return (struct.pack(">I", len(cdata)) + ctype.encode("latin-1")
                + cdata + zlib.crc32(ctype.encode("latin-1") + cdata).to_bytes(4, "big"))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00" + b"\xff\x00\x00")
    text = "chara\x00" + base64.b64encode(
        json.dumps(card_json, ensure_ascii=False).encode("utf-8")).decode("latin-1")
    return (b"\x89PNG\r\n\x1a\n" + chunk("IHDR", ihdr) + chunk("tEXt", text.encode("latin-1"))
            + chunk("IDAT", idat) + chunk("IEND", b""))


fails = []


def check(label, cond, extra=""):
    print(("PASS" if cond else "FAIL"), label, extra)
    if not cond:
        fails.append(label)


with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    wb = WorldBookManager(tmp / "worldbooks")

    # ── 1. PNG 角色卡全流程（模拟 /api/worldbook/import 与 /api/characters/import 共用管道）──
    png = make_png_with_chara(CARD)
    result = import_character_card(png, wb_mgr=wb, chars_dir=tmp / "chars",
                                   book_name="妮芙芙")
    check("PNG 导入角色", result["character"]["name"] == "妮芙芙", result["character"])
    check("PNG 导入内嵌世界书", result["worldbook"] and result["worldbook"]["entry_count"] == 2)
    book = wb.load(result["worldbook"]["id"])
    check("世界书条目解析", len(book.entries) == 2 and book.entries[0].trigger_keys == ["阿卡迪亚", "学院"])

    # 角色 index.md frontmatter 含 first_mes/scenario
    index_md = (tmp / "chars" / "妮芙芙" / "index.md").read_text(encoding="utf-8")
    check("frontmatter 含 first_mes", "first_mes:" in index_md)
    check("frontmatter 含 scenario", "scenario:" in index_md)
    check("正文含开场白分节", "## 开场白" in index_md and "## 场景" in index_md)
    check("头像已写入", (tmp / "chars" / "妮芙芙" / "avatar").is_dir())

    # ── 2. 玩家身份档案加载（博士 = data/characters 已有）──
    profile = load_player_profile("博士")
    check("玩家身份档案（博士）", profile and "玩家身份：博士" in profile and "身份简介" in profile)
    check("玩家身份档案缓存", load_player_profile("博士") is profile)

    # 不存在身份 → None（不崩）
    check("不存在的身份返回 None", load_player_profile("不存在的角色999") is None)

    # ── 3. 角色卡 JSON 直接解析（v1 扁平卡也支持）──
    v1 = {"name": "测试卡", "description": "x", "first_mes": "你好",
          "character_book": {"entries": [{"key": "测试", "content": "内容"}]}}
    parsed = parse_character_card(json.dumps(v1, ensure_ascii=False).encode("utf-8"))
    check("v1 扁平卡解析", parsed["meta"]["name"] == "测试卡" and len(parsed["book_data"]["entries"]) == 1)

    # ── 4. 无内嵌世界书的角色卡 → 只导入角色 ──
    no_book = {"name": "无书卡", "data": {"name": "无书卡", "description": "d", "first_mes": "hi"}}
    r2 = import_character_card(json.dumps(no_book, ensure_ascii=False).encode("utf-8"),
                               wb_mgr=wb, chars_dir=tmp / "chars")
    check("无书卡仅导入角色", r2["worldbook"] is None and r2["character"]["name"] == "无书卡")

    # ── 5. 坏文件 → 明确报错 ──
    try:
        parse_character_card(b"not a png or json")
        check("坏文件抛错", False)
    except CharacterCardError:
        check("坏文件抛错", True)

    # ── 6. DocumentInfo name 别名 ──
    doc_mgr = DocumentManager()
    docs = doc_mgr.list_documents("characters", include_content=True)
    check("角色列表含 name 字段", all("name" in d for d in docs) and any(d["name"] == "博士" for d in docs))

    # ── 7. 纯世界书 JSON 导入不受影响 ──
    plain = {"entries": {"e1": {"key": "k", "content": "c"}}}
    entries, report = parse_lorebook(plain)
    check("纯世界书导入", report.imported == 1 and entries[0].trigger_keys == ["k"])

print()
print("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}")
sys.exit(1 if fails else 0)
