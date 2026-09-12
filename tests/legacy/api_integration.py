"""Flask 集成测试：世界书导入 PNG/角色卡、会话创建带玩家身份、叙述注入。"""
import base64
import io
import json
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from app import create_app
from SceneManager import SceneManager

CARD = {
    "spec": "chara_card_v2",
    "spec_version": "2.0",
    "data": {
        "name": "集成测试卡",
        "description": "集成测试用角色。",
        "personality": "测试性格",
        "scenario": "测试场景：黄昏的训练场。",
        "first_mes": "「测试开场白：你来了。」",
        "character_book": {
            "entries": [
                {"keys": ["测试场景"], "content": "训练场设定内容。", "comment": "训练场"},
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


app = create_app()
client = app.test_client()
REPO = Path(__file__).resolve().parents[2]
created_chars = []
created_sessions = []

try:
    # ── 1. 世界书导入 PNG 角色卡（问题 1&2 的修复）──
    png = make_png_with_chara(CARD)
    resp = client.post("/api/worldbook/import", data={
        "name": "集成测试书",
        "file": (io.BytesIO(png), "集成测试卡.png"),
    }, content_type="multipart/form-data")
    body = resp.get_json()
    check("worldbook/import PNG 状态", resp.status_code == 201, f"{resp.status_code} {body}")
    check("worldbook/import PNG 导入书", body and body.get("book") and body["report"]["imported"] == 1)
    check("worldbook/import PNG 连带角色", body and body.get("character") and body["character"]["name"] == "集成测试卡",
          body and body.get("character"))
    if body and body.get("character"):
        created_chars.append(body["character"]["slug"])
    if body and body.get("book"):
        created_sessions.append(("book", body["book"]["id"]))

    # 书中条目可检索
    if body and body.get("book"):
        detail = client.get(f"/api/worldbook/{body['book']['id']}").get_json()
        check("导入书条目可用", detail["entry_count"] == 1 and detail["entries"][0]["trigger_keys"] == ["测试场景"])

    # ── 2. 纯世界书 JSON 不受影响（无角色）──
    resp = client.post("/api/worldbook/import", json={
        "name": "纯书",
        "data": {"entries": {"e1": {"key": "kk", "content": "cc"}}},
    })
    body = resp.get_json()
    check("纯 JSON 书导入", resp.status_code == 201 and body["report"]["imported"] == 1 and body.get("character") is None)
    if body and body.get("book"):
        created_sessions.append(("book", body["book"]["id"]))

    # ── 3. 角色卡 JSON 上传到 /api/characters/import（原功能不回归）──
    resp = client.post("/api/characters/import", data={
        "file": (io.BytesIO(json.dumps(CARD, ensure_ascii=False).encode("utf-8")), "集成测试卡.json"),
    }, content_type="multipart/form-data")
    body = resp.get_json()
    check("characters/import JSON", resp.status_code == 201 and body["character"]["name"] == "集成测试卡",
          f"{resp.status_code}")
    check("characters/import 内嵌书", body["worldbook"] and body["worldbook"]["entry_count"] == 1)
    created_chars.append(body["character"]["slug"])
    if body and body.get("worldbook"):
        created_sessions.append(("book", body["worldbook"]["id"]))

    # ── 4. 创建会话带玩家身份 ──
    resp = client.post("/api/sessions", json={
        "mode": "free", "name": "身份测试会话", "identity": "博士",
    })
    body = resp.get_json()
    check("创建会话带身份", resp.status_code == 201 and body["player_identity"] == "博士")
    sid = body["id"]
    created_sessions.append(("session", sid))

    # ── 4b. 纯 JSON 书导入（记录待清理）──
    resp = client.post("/api/worldbook/import", json={
        "name": "纯书",
        "data": {"entries": {"e2": {"key": "kk", "content": "cc"}}},
    })
    body = resp.get_json()
    if body and body.get("book"):
        created_sessions.append(("book", body["book"]["id"]))

    # ── 5. 叙述消息注入：开场白/场景 + 玩家档案 ──
    class FakeAgent:
        def __init__(self, meta):
            self.metadata = meta

    sm = SceneManager(llm=None, registry=None)
    sm._agents = {"集成测试卡": FakeAgent({
        "first_mes": "「测试开场白：你来了。」",
        "scenario": "测试场景：黄昏的训练场。",
    })}
    msgs = sm._build_narration_messages({"identity": "博士"}, "位置：训练场", is_first_turn=True)
    user = msgs[-1]["content"]
    check("首轮注入开场设定", "<opening_setup>" in user and "开场白" in user and "场景设定：测试场景" in user)
    check("首轮注入玩家档案", "<player_profile>" in user and "玩家身份：博士" in user)
    check("非首轮不注入开场设定", "<opening_setup>" not in sm._build_narration_messages(
        {"identity": "博士"}, "位置：训练场", is_first_turn=False)[-1]["content"])
    check("非首轮仍注入玩家档案", "<player_profile>" in sm._build_narration_messages(
        {"identity": "博士"}, "位置：训练场", is_first_turn=False)[-1]["content"])

    # ── 6. 角色列表含 name 字段（问题 4 根因修复）──
    chars = client.get("/api/characters").get_json()
    check("角色列表含 name", all("name" in c for c in chars))

finally:
    # ── 清理测试产物 ──
    for kind, key in created_sessions:
        if kind == "book":
            client.delete(f"/api/worldbook/{key}")
    char_dir = REPO / "data" / "characters"
    # 导入会按重名自动加后缀（集成测试卡_2 …），因此按前缀兜底清理，
    # 避免中断/异常路径把测试角色留在 data/ 里。
    candidates = set(created_chars)
    if char_dir.is_dir():
        candidates |= {p.name for p in char_dir.iterdir()
                       if p.is_dir() and p.name.startswith("集成测试卡")}
    for slug in sorted(candidates):
        target = char_dir / slug
        if target.is_dir() and (target / "index.md").exists():
            import shutil
            shutil.rmtree(target, ignore_errors=True)
            print(f"已清理测试角色目录: {slug}")
    for kind, key in created_sessions:
        if kind == "session":
            client.delete(f"/api/sessions/{key}")
            print(f"已清理测试会话: {key}")

print()
print("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}")
sys.exit(1 if fails else 0)
