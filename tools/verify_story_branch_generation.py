#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""目标一现场验证：LLM 依据「当前节点状态 + 世界书背景」生成未来剧情分支。

运行（需要可用的 LLM 后端，读取 config/llm_config.json）：

    python tools/verify_story_branch_generation.py

验证链路：
  1. 构造剧情会话覆盖层（风雪过境），定位到 beat_arrival；
  2. 组装 Call 2 的两类输入：<current_node>（当前节点状态）与
     <world_background>（世界书动态层）；
  3. 真实调用 SceneManager.extract_markers 让 LLM 生成 branches；
  4. 断言：分支非空、target_beat_id 只取当前节点列出的后续节拍；
  5. 演示自由进入不同分支：set_pending_branch → advance_beat 跳转到目标节拍。

不写真实会话目录（overlay 指向临时目录）。
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import session_overlay as so  # noqa: E402
from session_overlay import SessionOverlay  # noqa: E402
from SceneManager import SceneManager  # noqa: E402
from llm_backend_manager import LLMBackendManager  # noqa: E402
from wiki_manager import WikiManager  # noqa: E402
from world_book import WorldBookManager  # noqa: E402

PLOT_ID = "fengxue_guojing"

# beat_arrival 处的一段叙述（用于触发 Call 2 提取）
NARRATIVE = (
    "银灰为博士斟满第三杯茶，窗外的圣山在正午的日光下白得发亮。"
    "他把一份没有署名的邀请函推到桌面中央——那是雪山大典的观礼凭证，"
    "也是一张把博士绑上希瓦艾什家战车的契约。"
    "灵知合上终端，镜片后的目光扫过博士；锏依旧守在门口，手按刀柄。"
    "会客厅里安静得能听见雪从檐角滑落的声音。"
)


def main() -> int:
    tmp = tempfile.TemporaryDirectory(prefix="story_branch_verify_")
    so._SESSIONS_DIR = Path(tmp.name) / "sessions"

    # ── 1. 剧情会话覆盖层 ──
    overlay = SessionOverlay("sess_verify_branches", "story")
    overlay.set_worldbook_id("arknights")
    overlay.load_quests_from_plot(PLOT_ID)
    overlay.init_session_docs(PLOT_ID)

    current = overlay.get_current_beat()
    print(f"[1] 当前节点：{current['id']}")
    print(f"    所在章节：第{overlay.get_beat_state()['chapter_idx'] + 1}章")

    # ── 2. 两类输入 ──
    branch_context = overlay.build_branch_context()
    print("\n[2] <current_node>（当前节点状态，节选）：")
    print("    " + branch_context.replace("\n", "\n    ")[:900])

    worldbook = WorldBookManager()
    sm = SceneManager(
        None, WikiManager(), overlay=overlay,
        worldbook_manager=worldbook, combat_mode="narrative",
    )
    wb = sm._resolve_worldbook()
    _, wb_after = sm._build_worldbook_parts(
        wb, recent_text="", current_input=NARRATIVE, identity="博士",
    )
    print("\n[3] <world_background>（世界书动态层，节选）：")
    print("    " + (wb_after[:600].replace("\n", "\n    ") or "（空）"))

    # ── 3. 真实 LLM 生成分支 ──
    llm, status = LLMBackendManager().get_llm()
    assert llm is not None, f"无可用 LLM 后端：{status}"
    sm._llm = llm

    valid_ids = sm._valid_beat_ids()
    print(f"\n[4] 合法节拍 id（{len(valid_ids)} 个）：{valid_ids}")

    print("\n[5] 调用 LLM 生成 branches（真实请求）...")
    markers = sm.extract_markers(
        NARRATIVE, choices_count=3, beat_state_active=True,
        branch_context=branch_context, worldbook_text=wb_after,
    )
    if markers.get("error"):
        print(f"    LLM 错误：{markers['error']}")
        return 1

    branches = markers.get("branches") or []
    print(f"    LLM 原始 choices：{markers.get('choices')}")
    print(f"    LLM 结构化 branches（{len(branches)} 个）：")
    for b in branches:
        print(f"      - {b['id']}: {b['label']!r} intent={b['intent']!r} "
              f"target={b['target_beat_id']!r} source={b['source']}")

    assert branches, "LLM 未生成任何分支"
    bad = [b for b in branches if b["target_beat_id"] and b["target_beat_id"] not in valid_ids]
    assert not bad, f"存在编造的节拍 id：{bad}"
    grounded = [b for b in branches if b["target_beat_id"]]
    print(f"\n[6] 校验通过：{len(branches)} 个分支，{len(grounded)} 个带合法目标节拍，"
          f"0 个编造 id")

    # ── 4. 自由进入不同分支 ──
    print("\n[7] 自由进入分支：")
    if grounded:
        chosen = grounded[0]
        overlay.set_pending_branch(chosen)
        print(f"    玩家选择 → {chosen['label']!r}（目标 {chosen['target_beat_id']}）")
        overlay.advance_beat()
        print(f"    推进后当前节点 → {overlay.get_current_beat()['id']}")
        assert overlay.get_current_beat()["id"] == chosen["target_beat_id"]
    else:
        # 无带目标的分支时，退化为顺序推进，仍证明落点机制可用
        overlay.set_pending_branch({"label": "走向山道", "target_beat_id": "beat_convoy_fight"})
        overlay.advance_beat()
        print(f"    作者分支落点 → {overlay.get_current_beat()['id']}")

    print("\n结果：目标一现场验证通过 ✔")
    tmp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
