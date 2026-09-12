"""角色卡导入测试：PNG/JSON 解析 + 导入到 characters 目录。"""

import io
import json
import os
import struct
import zlib

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from character_card import CharacterCardError, parse_character_card, slugify


def _png_with_card(card: dict) -> bytes:
    """构造 1x1 PNG，tEXt 块内嵌 base64 角色卡 JSON。"""

    def chunk(ctype, cdata):
        return (struct.pack(">I", len(cdata)) + ctype + cdata
                + struct.pack(">I", zlib.crc32(ctype + cdata) & 0xFFFFFFFF))

    import base64
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
    png += chunk(b"IEND", b"")
    tex = b"chara\x00" + base64.b64encode(json.dumps(card, ensure_ascii=False).encode("utf-8"))
    return png[:8] + chunk(b"tEXt", tex) + png[8:]


CARD = {
    "spec": "chara_card_v2",
    "spec_version": "2.0",
    "data": {
        "name": "测试角色A",
        "description": "测试角色描述。\n第二行。",
        "personality": "活泼",
        "scenario": "测试场景",
        "first_mes": "你好！",
        "tags": ["测试", "干员"],
        "creator": "tester",
        "character_book": {
            "name": "test_book",
            "entries": {"1": {"keys": ["测试角色A"], "content": "测试设定。"}},
        },
    },
}


def test_parse_json_card():
    raw = json.dumps(CARD, ensure_ascii=False).encode("utf-8")
    parsed = parse_character_card(raw)
    assert parsed["meta"]["name"] == "测试角色A"
    assert parsed["meta"]["tags"] == ["测试", "干员"]
    assert parsed["image_bytes"] is None
    assert parsed["book_data"]["entries"]["1"]["content"] == "测试设定。"


def test_parse_png_card():
    png = _png_with_card(CARD)
    parsed = parse_character_card(png)
    assert parsed["meta"]["name"] == "测试角色A"
    assert parsed["image_bytes"] is not None
    assert b"chara" not in parsed["image_bytes"]  # 内嵌 JSON 块已剥离
    assert parsed["book_data"] is not None


def test_parse_invalid():
    with pytest.raises(CharacterCardError):
        parse_character_card(b"not json at all")
    with pytest.raises(CharacterCardError):
        parse_character_card(json.dumps({"data": {}}).encode("utf-8"))


def test_slugify():
    assert slugify("阿米娅") == "阿米娅"
    # 全部非法字符转下划线，且去掉首尾下划线
    assert slugify('a/b:c*?"<>|') == "a_b_c"
    assert slugify("   ") == "imported_character"


def test_import_creates_character(tmp_path, monkeypatch):
    import app as app_mod
    import world_book as wb_mod
    import character_card as cc_mod

    # 隔离数据目录：角色写入 character_card._DEFAULT_CHARS_DIR；世界书同样隔离
    from pathlib import Path
    tmp_char = tmp_path / "data" / "characters"
    tmp_char.mkdir(parents=True)
    monkeypatch.setattr(wb_mod, "_WORLDBOOKS_DIR", tmp_path / "worldbooks")

    monkeypatch.setattr(cc_mod, "_DEFAULT_CHARS_DIR", tmp_char)
    client = app_mod.create_app().test_client()
    raw = json.dumps(CARD, ensure_ascii=False).encode("utf-8")
    resp = client.post(
        "/api/characters/import",
        data={"file": (io.BytesIO(raw), "card.json")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["character"]["source"] == "imported"
    assert body["worldbook"] is not None
    index = tmp_char / body["character"]["slug"] / "index.md"
    assert index.is_file()
    text = index.read_text(encoding="utf-8")
    assert "source: imported" in text
    assert "测试角色A" in text
