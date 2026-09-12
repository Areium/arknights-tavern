"""验证：剧情会话开场时，玩家身份角色不应被加载为场景角色。"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

REPO = Path(__file__).resolve().parents[2]
PLOT_DIR = REPO / "data" / "plots" / "_test_identity_plot"
CHAR_DIR = REPO / "data" / "characters" / "龙门侦探"


def main():
    # 1. 创建临时剧情：initial_characters 包含一个非博士玩家身份
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    (PLOT_DIR / "index.md").write_text(
        """---
id: _test_identity_plot
name: 测试身份剧情
initial_location: 测试地点
initial_time: 黎明
initial_characters:
  - 阿米娅
  - 龙门侦探
---
开场设置：这里是测试开场。
""",
        encoding="utf-8",
    )

    # 2. 创建玩家身份角色（非博士）
    CHAR_DIR.mkdir(parents=True, exist_ok=True)
    (CHAR_DIR / "index.md").write_text(
        """---
name: 龙门侦探
summary: 测试玩家身份
tags: [侦探]
player_identity: true
---
龙门侦探的背景设定。
""",
        encoding="utf-8",
    )

    try:
        # 3. 创建会话，玩家身份为 龙门侦探
        from app import create_app
        app = create_app()
        client = app.test_client()
        resp = client.post("/api/sessions", json={
            "mode": "story",
            "plot_id": "_test_identity_plot",
            "identity": "龙门侦探",
        })
        assert resp.status_code == 201, resp.get_json()
        sess = resp.get_json()
        session_id = sess["id"]

        print("会话 ID:", session_id)
        print("玩家身份:", sess["player_identity"])
        print("场景角色:", sess["characters"])
        print("环境地点:", sess["environment"]["location"])
        print("环境时间:", sess["environment"]["time"])

        # 断言：玩家身份角色不应出现在场景角色中
        assert "龙门侦探" not in sess["characters"], \
            f'玩家身份角色被错误加载到场景: {sess["characters"]}'
        assert "阿米娅" in sess["characters"]
        assert sess["environment"]["location"] == "测试地点"
        assert sess["environment"]["time"] == "黎明"

        client.delete(f"/api/sessions/{session_id}")
        print("PASS: 玩家身份角色未混入场景，开场环境正确")
    finally:
        shutil.rmtree(PLOT_DIR, ignore_errors=True)
        shutil.rmtree(CHAR_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
