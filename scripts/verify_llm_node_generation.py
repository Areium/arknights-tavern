#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""真实 LLM 端到端冒烟：验证「LLM 生成剧情节点」在完整剧情流程下的可行性。

与 tests/test_story_tree_full_flow.py（脚本化 LLM，确定性单测）互补：本脚本
把**真实 LLM**（Call 1 叙述 + Call 2 标记提取）接入一条完整剧情流程——

    根节点填充 → 同节点推进 → 选分支生成子节点 → 多层展开
    → 回档分叉 → 复访复用

逐轮记录 LLM 提取结果（node_title / branches / degraded）与树结构变化，
最终给出可行性结论与明细报告。这不是 pytest 用例（需联网 + API key、
分钟级耗时），而是入库前的人工/CI-optional 冒烟工具。

用法（仓库根目录）：
    python scripts/verify_llm_node_generation.py [--plot fengxue_guojing] [--out PATH]

前置：config/llm_config.json 含可用 API key（或可连通的 Ollama）。
会话数据全部写入系统临时目录，不触碰 data/memory/。
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import session_overlay as so  # noqa: E402
import session_manager as sm_mod  # noqa: E402


def build_tree_ascii(session) -> str:
    """把剧情树渲染成缩进 ASCII（* 标记当前节点）。"""
    tv = session.overlay.build_tree_state()
    lines = []
    for n in tv["nodes"]:
        mark = "*" if n["id"] == tv["current_id"] else " "
        branches = ",".join(b["label"] for b in n["branches"])
        lines.append(
            f"{mark} {'  ' * n['depth']}{n['title']}"
            f"  [d{n['depth']} {n['branch_label'] or '入口'}]"
            f"  轮{n['round_start']}-{n['round_end']}  分支[{branches}]"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plot", default="fengxue_guojing")
    ap.add_argument("--out", default=str(ROOT / ".tmp" / "llm_node_verify_report.json"))
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 隔离：会话数据写临时目录，不动 data/memory/ ──
    tmp = Path(tempfile.mkdtemp(prefix="llm_node_verify_"))
    so._SESSIONS_DIR = tmp / "sessions"
    sm_mod._SESSIONS_DIR = tmp / "sessions"

    from app import create_app
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    # 配置：沿用真实 llm_config，仅收索单轮篇幅/关掉回忆生成以聚焦节点验证
    real_get_config = app._managers["llm_backend"].get_config

    def get_config():
        cfg = dict(real_get_config())
        cfg.update({
            "memory_interval": 999, "word_limit": 300,
            "dialogue_bubble_mode": False, "narration_reasoning_effort": "none",
            "max_output_tokens": 4096, "auto_generate_choices": True,
            "choice_count": 3,
        })
        return cfg

    app._managers["llm_backend"].get_config = get_config

    res = client.post("/api/sessions", json={
        "mode": "story", "plot_id": args.plot, "name": "LLM节点可行性冒烟",
    })
    if res.status_code != 201:
        print(f"[FATAL] 会话创建失败: {res.status_code} {res.get_json()}")
        return 2
    sid = res.get_json()["id"]
    session = app._managers["session"].get_session(sid)
    sm = session.scene_manager

    # 计时与提取结果采集（真实方法外层包计时，不改变行为）
    timings: list[tuple[str, float]] = []
    extracts: list[dict] = []
    orig_narrate, orig_extract = sm.narrate, sm.extract_markers

    def timed_narrate(*a, **k):
        t0 = time.monotonic()
        r = orig_narrate(*a, **k)
        timings.append(("narrate", time.monotonic() - t0))
        return r

    def timed_extract(*a, **k):
        t0 = time.monotonic()
        r = orig_extract(*a, **k)
        timings.append(("extract", time.monotonic() - t0))
        extracts.append(r)
        return r

    sm.narrate, sm.extract_markers = timed_narrate, timed_extract

    checks: list[dict] = []
    rounds: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> bool:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" —— {detail}" if detail else ""))
        return ok

    def play(step: str, action: str = "", branch_id: str | None = None,
             branch_label: str = "") -> dict | None:
        """跑一轮真实叙述，返回响应 JSON（失败返回 None）。"""
        payload = {"action": action}
        if branch_id:
            payload["branch_id"] = branch_id
        t0 = time.monotonic()
        r = client.post(f"/api/sessions/{sid}/narrate-continue", json=payload)
        dt = time.monotonic() - t0
        if r.status_code != 200:
            print(f"\n[ROUND {step}] HTTP {r.status_code}: {r.get_json()}")
            return None
        body = r.get_json()
        tree = session.overlay.get_story_tree()
        cur = tree["nodes"].get(tree["current_id"], {})
        rec = {
            "step": step, "action": action, "branch": branch_label,
            "http_ok": True, "latency_s": round(dt, 1),
            "narrative_chars": len(body.get("narrative") or ""),
            "emitted_branches": body.get("branches", []),
            "node_now": {
                "id": tree["current_id"], "title": cur.get("title"),
                "depth": cur.get("depth"), "round_end": (cur.get("state") or {}).get("round_end"),
            },
            "tree_size": len(tree["nodes"]),
        }
        rounds.append(rec)
        print(f"\n[ROUND {step}] {dt:.0f}s 叙述{rec['narrative_chars']}字 → "
              f"节点「{cur.get('title')}」(d{cur.get('depth')}) 树={len(tree['nodes'])}节点")
        m = extracts[-1] if extracts else {}
        print(f"  提取: title={m.get('node_title')!r} degraded={m.get('degraded')} "
              f"branches={[(b.get('label'), b.get('source')) for b in (m.get('branches') or [])]}")
        return body

    def pick(branches: list[dict], exclude: set[str]) -> dict | None:
        """挑一个非作者来源、未走过的分支；没有则放宽。"""
        pool = [b for b in branches
                if b.get("source") != "author" and b["label"] not in exclude]
        pool = pool or [b for b in branches if b["label"] not in exclude]
        return pool[0] if pool else None

    print(f"=== LLM 生成节点可行性冒烟（plot={args.plot}）===")
    used_labels: set[str] = set()

    # ── R1 首轮：根节点填充 ──
    r1 = play("R1 首轮")
    if r1 is None:
        return dump_and_exit(checks, rounds, session, out_path, 1)
    t = session.overlay.get_story_tree()
    root = t["nodes"]["n_root"]
    check("R1 根节点被 LLM 内容填充",
          bool(root.get("content")) and (root.get("state") or {}).get("round_end") == 1,
          f"title={root.get('title')!r}")
    check("R1 LLM 给出可用分支", bool(r1.get("branches")),
          f"{[b['label'] for b in r1.get('branches', [])][:5]}")

    # ── R2 同节点内继续 ──
    content_before = root.get("content", "")
    r2 = play("R2 同节点推进")
    if r2 is None:
        return dump_and_exit(checks, rounds, session, out_path, 1)
    t = session.overlay.get_story_tree()
    root = t["nodes"]["n_root"]
    check("R2 同节点推进不新建节点", len(t["nodes"]) == 1, f"树={len(t['nodes'])}")
    check("R2 节点内容随轮推进", root["content"] != content_before and
          (root.get("state") or {}).get("round_end", 0) >= 2,
          f"round_end={(root.get('state') or {}).get('round_end')}")

    # ── R3 选分支 → 分支节点 ──
    b3 = pick(r2.get("branches", []), used_labels)
    if not b3:
        check("R3 存在可选分支", False, "LLM 未给出任何分支")
        return dump_and_exit(checks, rounds, session, out_path, 1)
    used_labels.add(b3["label"])
    r3 = play("R3 选分支", branch_id=b3.get("id"), branch_label=b3["label"])
    if r3 is None:
        return dump_and_exit(checks, rounds, session, out_path, 1)
    t = session.overlay.get_story_tree()
    node3_id = t["current_id"]
    node3 = t["nodes"][node3_id]
    check("R3 分支生成新子节点", len(t["nodes"]) == 2 and
          node3["parent_id"] == "n_root" and node3["depth"] == 1,
          f"id={node3_id} label={node3.get('branch_label')!r} title={node3.get('title')!r}")
    check("R3 分支节点内容来自 LLM", bool(node3.get("content")), f"{len(node3.get('content') or '')}字")

    # ── R4 子节点下再选分支 → depth 2 ──
    b4 = pick(r3.get("branches", []), used_labels)
    if not b4:
        check("R4 存在可选分支", False, "子节点无分支")
        return dump_and_exit(checks, rounds, session, out_path, 1)
    used_labels.add(b4["label"])
    r4 = play("R4 深层分支", branch_id=b4.get("id"), branch_label=b4["label"])
    if r4 is None:
        return dump_and_exit(checks, rounds, session, out_path, 1)
    t = session.overlay.get_story_tree()
    node4 = t["nodes"][t["current_id"]]
    check("R4 多层展开 depth=2", len(t["nodes"]) == 3 and
          node4["parent_id"] == node3_id and node4["depth"] == 2,
          f"title={node4.get('title')!r}")

    # ── R5 回档到根 → 走另一分支 → 分叉 ──
    rb = client.post(f"/api/sessions/{sid}/rollback-node", json={"node_id": "n_root"})
    if rb.status_code != 200:
        check("R5 回档到根成功", False, str(rb.get_json()))
        return dump_and_exit(checks, rounds, session, out_path, 1)
    b5 = pick(rb.get_json().get("story_state", {}).get("emitted_branches",
              session.overlay.get_emitted_branches()), used_labels)
    if not b5:
        check("R5 回档后存在另一分支", False,
              f"emitted={[b['label'] for b in session.overlay.get_emitted_branches()]}")
        return dump_and_exit(checks, rounds, session, out_path, 1)
    r5 = play("R5 回档分叉", branch_id=b5.get("id"), branch_label=b5["label"])
    if r5 is None:
        return dump_and_exit(checks, rounds, session, out_path, 1)
    t = session.overlay.get_story_tree()
    node5_id = t["current_id"]
    root_children = set(t["nodes"]["n_root"]["children"])
    check("R5 回档后走另一分支生成节点（分叉）", len(t["nodes"]) == 4 and
          node5_id in root_children and root_children == {node3_id, node5_id},
          f"根的子节点={sorted(root_children)}")

    # ── R6 再回档 → 重走同一分支 → 复用 ──
    assert client.post(f"/api/sessions/{sid}/rollback-node",
                       json={"node_id": "n_root"}).status_code == 200
    b6 = next((b for b in session.overlay.get_emitted_branches()
               if b["label"] == b5["label"]), None)
    if not b6:
        check("R6 回档后原分支仍可选", False)
        return dump_and_exit(checks, rounds, session, out_path, 1)
    r6 = play("R6 复访复用", branch_id=b6.get("id"), branch_label=b6["label"])
    if r6 is None:
        return dump_and_exit(checks, rounds, session, out_path, 1)
    t = session.overlay.get_story_tree()
    check("R6 重走同一分支复用节点", len(t["nodes"]) == 4 and
          t["current_id"] == node5_id,
          f"树={len(t['nodes'])} current={t['current_id']}")

    # ── 汇总 ──
    ok = all(c["ok"] for c in checks)
    narrate_t = [d for kind, d in timings if kind == "narrate"]
    extract_t = [d for kind, d in timings if kind == "extract"]
    degraded = [i for i, m in enumerate(extracts) if m.get("degraded")]
    print("\n=== 汇总 ===")
    print(f"通过 {sum(c['ok'] for c in checks)}/{len(checks)} 项检查 → "
          f"{'可行性验证通过' if ok else '存在问题，见上方 FAIL'}")
    if narrate_t:
        print(f"Call1 叙述: {len(narrate_t)}轮 平均{sum(narrate_t)/len(narrate_t):.0f}s")
    if extract_t:
        print(f"Call2 提取: {len(extract_t)}次 平均{sum(extract_t)/len(extract_t):.0f}s"
              f"  degraded轮次: {degraded or '无'}")
    print("\n--- 最终剧情树 ---")
    print(build_tree_ascii(session))
    return dump_and_exit(checks, rounds, session, out_path, 0 if ok else 1,
                         final=True)


def dump_and_exit(checks, rounds, session, out_path: str, code: int,
                  final: bool = False) -> int:
    report = {
        "verdict": ("pass" if code == 0 else "fail"),
        "checks": checks,
        "rounds": rounds,
        "timings": None,
        "tree": session.overlay.build_tree_state() if final else None,
    }
    Path(out_path).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"\n报告已写入: {out_path}")
    return code


if __name__ == "__main__":
    sys.exit(main())
