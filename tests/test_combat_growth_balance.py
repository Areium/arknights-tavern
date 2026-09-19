"""批次 3：升级属性点成长、威胁模型、阶段带缩放与"生成→校验→试跑"闭环。"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "perf_tests"))

from app import create_app  # noqa: E402
from combat_balance import classify_enemy, node_budget_report, recommend_band  # noqa: E402
from combat_rules import band_scaling, difficulty_rules, growth_rules  # noqa: E402
from combat_settlement import (  # noqa: E402
    build_writeback_payload, compute_character_growth, pick_growth_attribute,
)

ATTRS = {
    "物理强度": 6, "战场机动": 5, "生理耐受": 8, "战术规划": 6,
    "战斗技巧": 6, "源石技艺适应性": 6, "情绪稳定性": 6,
}


# ── 成长：属性点 ──

def test_level_up_grants_attribute_points_and_auto_allocates():
    result = compute_character_growth("测试", ATTRS, {"level": 1, "xp": 0}, 800)
    assert result["level_delta"] == 3
    assert result["attribute_points_gained"] == 3
    assert result["attribute_points_allocated"] == 3
    assert result["attribute_points_pending"] == 0
    assert len(result["attribute_changes"]) == 3
    # 自动分配到最低属性（战场机动 5 起），且逐点递增
    lowest = result["attribute_changes"][0]
    assert lowest["name"] == "战场机动"
    assert (lowest["before"], lowest["after"]) == (5, 6)
    assert all(c["reason"] == "level_up" for c in result["attribute_changes"])


def test_repeated_points_flow_to_next_lowest_attribute():
    result = compute_character_growth("测试", ATTRS, {"level": 1}, 800)
    names = [c["name"] for c in result["attribute_changes"]]
    # 战场机动 5→6→7 后应转向其它 6 点属性，而不是死磕一个
    assert names.count("战场机动") == 2
    assert len(set(names)) >= 2


def test_writeback_payload_carries_attributes():
    result = compute_character_growth("测试", ATTRS, {"level": 1}, 800)
    payload = build_writeback_payload(result)
    assert payload["progress"]["level"] == 4
    assert payload["progress"]["specialization_points"] == 3
    assert payload["metadata"]["attributes"], "属性变化必须写回存档"
    assert set(payload["metadata"]["attributes"]) == {c["name"] for c in result["attribute_changes"]}


def test_manual_allocation_accumulates_pending_points():
    result = compute_character_growth(
        "测试", ATTRS, {"level": 1, "attribute_points": 2}, 800,
        growth_rules_override={"auto_allocate_attribute_points": False})
    assert result["attribute_changes"] == []
    assert result["attribute_points_pending"] == 5      # 2 存量 + 3 新增
    payload = build_writeback_payload(result)
    assert payload["progress"]["attribute_points"] == 5


def test_attribute_point_rate_is_configurable():
    result = compute_character_growth(
        "测试", ATTRS, {"level": 1}, 800,
        growth_rules_override={"attribute_points_per_level": 2})
    assert result["attribute_points_gained"] == 6


def test_capped_attributes_stop_allocation():
    full = {**{k: 10 for k in ATTRS}, "魅力": 10}
    result = compute_character_growth("满属性", full, {"level": 1}, 800)
    assert result["level_delta"] == 3
    assert result["attribute_changes"] == []
    assert result["attribute_points_allocated"] == 0


def test_pick_growth_attribute_respects_cap():
    attrs = {**ATTRS, "战场机动": 10}
    assert pick_growth_attribute(attrs, cap=10) != "战场机动"
    assert pick_growth_attribute({k: 10 for k in ATTRS}, cap=10) == "魅力"


def test_growth_rules_come_from_config_file():
    rules = growth_rules()
    assert rules["attribute_points_per_level"] >= 0
    assert isinstance(rules["auto_allocate_attribute_points"], bool)
    assert rules["attr_cap"] == 10


# ── 威胁模型 / 阶段带 ──

def test_classify_enemy_matches_shipped_layering():
    info = classify_enemy({"hp": 90, "patk": 24, "defense": 5})
    assert info["role"] == "standard"
    assert info["threat_points"] == 1.6
    assert info["action_slots"] == 1


def test_classify_respects_declared_role_and_tier():
    info = classify_enemy({"hp": 500, "patk": 40, "defense": 10},
                          level=5, declared_role="boss", declared_tier="T4")
    assert info["role"] == "boss" and info["threat_points"] == 7.0
    assert info["power_tier"] == "T4"


def test_recommend_band_tracks_threat_ranges():
    assert recommend_band(2.0) == "T0"
    assert recommend_band(4.5) == "T1"
    assert recommend_band(8.0) == "T2"
    assert recommend_band(12.0) == "T3"
    assert recommend_band(20.0) == "T4"


def test_node_budget_report_flags_budget_and_band_mismatch():
    node = {
        "waves": [{"enemies": [{"enemy": "整合运动士兵", "count": 6}]}],  # 9.6 威胁
        "difficulty": {"band": "T0", "threat_budget": 3.0},
    }
    report = node_budget_report(node)
    assert report["total"] == pytest.approx(9.6, abs=0.2)
    joined = " ".join(report["warnings"])
    assert "超出声明预算" in joined
    assert "明显偏离声明阶段带" in joined


def test_node_budget_report_quiet_when_consistent():
    node = {
        "waves": [{"enemies": [{"enemy": "整合运动士兵", "count": 3,
                                "positions": [[3, 5], [4, 5], [5, 5]]}]}],
        "difficulty": {"band": "T1", "threat_budget": 4.8},
    }
    report = node_budget_report(node)
    assert report["warnings"] == []


def test_stats_override_changes_threat():
    base = {"waves": [{"enemies": [{"enemy": "整合运动士兵", "count": 1}]}]}
    buffed = {"waves": [{"enemies": [{"enemy": "整合运动士兵", "count": 1,
                                      "stats": {"hp": 400, "patk": 45}}]}]}
    assert node_budget_report(buffed)["total"] > node_budget_report(base)["total"]


def test_band_scaling_reads_config():
    assert band_scaling("T2") == (1.2, 1.15)
    assert band_scaling("unknown") == (1.0, 1.0)
    assert "T4" in (difficulty_rules().get("bands") or {})


def test_band_scaling_applies_in_session_when_enabled():
    from combat_session import CombatSession
    node_id = "enc_band_scaling_test"
    node = {
        "schema_version": 1, "node_id": node_id, "name": "带宽缩放测试",
        "map": {"rows": 5, "cols": 5, "tiles": "ground",
                "deploy": {"player": {"rect": [0, 0, 4, 0]},
                           "enemy": {"cells": [[2, 4]]}}},
        "waves": [{"enemies": [{"enemy": "整合运动士兵", "count": 1,
                                "positions": [[2, 4]]}]}],
        "difficulty": {"band": "T2", "apply_band_scaling": True, "threat_budget": 2.0},
    }
    path = ROOT / "data" / "combat" / "nodes" / f"{node_id}.json"
    try:
        path.write_text(json.dumps(node, ensure_ascii=False, indent=2), encoding="utf-8")
        state = CombatSession("band-test").start(node_id, character_names=["阿米娅"])
        enemy = next(u for u in state["units"] if u["team"] == "enemy")
        assert enemy["max_hp"] == 108        # 90 × 1.2
        assert enemy["patk"] == pytest.approx(24 * 1.15, abs=0.01)
    finally:
        path.unlink(missing_ok=True)


# ── 生成 → 校验 → 试跑 闭环 ──

def _tool_env() -> dict:
    """让子进程**确定性**地用 UTF-8 写 stdout/stderr。

    工具 CLI 会输出中文。若编码两边不一致——子进程按环境变量（PYTHONIOENCODING /
    PYTHONUTF8）写 UTF-8，父进程 `text=True` 却按 locale（Windows 上 GBK）解码——
    读线程会抛 `UnicodeDecodeError`，用例就以「工具坏了」的面目失败。这是夹具的
    问题，不是工具的问题，所以在这里把两端都钉死在 UTF-8。
    """
    return {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _run(tool: str, *args) -> subprocess.CompletedProcess:
    """跑工具 CLI（参数统一转字符串，允许直接传数字）。"""
    return subprocess.run([sys.executable, str(ROOT / "tools" / tool), *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=_tool_env(), cwd=ROOT)


def test_validate_cli_accepts_shipped_node():
    res = _run("validate_battle_spec.py", str(ROOT / "data/combat/nodes/enc_training.json"))
    assert res.returncode == 0, res.stderr
    assert "OK" in res.stdout


def test_validate_cli_rejects_broken_spec(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({
        "node_id": "bad", "name": "坏", "map": {"rows": 3, "cols": 3, "tiles": "ground"},
        "waves": [{"enemies": [{"enemy": "不存在", "count": 1, "positions": [[9, 9]]}]}],
    }, ensure_ascii=False), encoding="utf-8")
    res = _run("validate_battle_spec.py", str(broken), "--json")
    assert res.returncode == 1
    payload = json.loads(res.stdout)
    assert payload["failed"] == 1
    assert payload["results"][0]["errors"]


def test_generator_produces_valid_specs_for_each_band(tmp_path):
    for i, band in enumerate(("T0", "T1", "T2", "T3")):
        out = tmp_path / f"gen_{band}.json"
        res = _run("generate_battle_spec.py", "--node-id", f"enc_gen_{band}",
                   "--band", band, "--seed", str(41 + i), "--out", str(out))
        assert res.returncode == 0, res.stderr
        node = json.loads(out.read_text(encoding="utf-8"))
        assert node["difficulty"]["band"] == band
        assert node["difficulty"]["threat_budget"] > 0
        # 生成物必须自身通过校验（生成器内部已自校验，这里再走一遍 CLI）
        assert _run("validate_battle_spec.py", str(out)).returncode == 0


def test_simulate_cli_runs_candidate_and_enforces_thresholds(tmp_path):
    out = tmp_path / "cand.json"
    assert _run("generate_battle_spec.py", "--node-id", "enc_sim_candidate",
                "--band", "T1", "--seed", 7, "--out", str(out)).returncode == 0

    ok = _run("simulate_battle.py", "--spec", str(out), "--runs", 10,
              "--min-win-rate", "0.1", "--max-median-rounds", "20",
              "--json", str(tmp_path / "sim.json"))
    assert ok.returncode == 0, ok.stdout + ok.stderr
    payload = json.loads((tmp_path / "sim.json").read_text(encoding="utf-8"))
    assert payload["pass"] is True
    assert payload["summary"]["win_rate"] >= 0.1

    impossible = _run("simulate_battle.py", "--spec", str(out), "--runs", 10,
                      "--min-win-rate", "1.01")
    assert impossible.returncode == 1
    assert "未达阈值" in impossible.stdout


def test_simulate_cli_is_reproducible(tmp_path):
    out = tmp_path / "cand.json"
    _run("generate_battle_spec.py", "--node-id", "enc_sim_repro",
         "--band", "T2", "--seed", 3, "--out", str(out))
    a = _run("simulate_battle.py", "--spec", str(out), "--runs", 8)
    b = _run("simulate_battle.py", "--spec", str(out), "--runs", 8)
    assert a.stdout == b.stdout


def test_balance_audit_tool_runs(tmp_path):
    report = tmp_path / "balance_audit_report.md"
    res = _run("balance_audit.py", "--report", str(report))
    assert res.returncode == 0, res.stderr
    assert "敌人" in res.stdout and "节点" in res.stdout
    assert report.is_file()


def test_audit_report_written_with_tables():
    report = (ROOT / "perf_tests" / "balance_audit_report.md").read_text(encoding="utf-8")
    assert "敌人分层" in report and "节点威胁预算" in report


# ── 接口：校验返回威胁指标 ──

def test_validate_endpoint_returns_threat_metrics():
    client = create_app().test_client()
    node = json.loads((ROOT / "data/combat/nodes/enc_defense.json").read_text(encoding="utf-8"))
    res = client.post("/api/combat/nodes/validate", json={"node": node})
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["errors"] == []
    assert payload["metrics"]["threat"]["total"] > 0
    assert payload["metrics"]["threat"]["band_hint"] in ("T0", "T1", "T2", "T3", "T4")
