# -*- coding: utf-8 -*-
"""节点级世界书作用域的回档一致性回归（docs/node-scoped-worldbook-loading.md §5.4）。

不变量：∀ 轮次 r，eligible_uids_for(overlay) == 当前节点快照里的 lore_scope.allowed
∩ 会话范围。回档到旧节点后重走同一路径，候选集必须逐字节复现。

只写临时会话目录（monkeypatch _SESSIONS_DIR），不触碰真实 data/memory/。
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import node_lore_scope as nls  # noqa: E402
import session_overlay as so  # noqa: E402
from session_overlay import SessionOverlay  # noqa: E402
from world_book import WorldBook, WorldBookEntry  # noqa: E402

PLOT_ID = "fengxue_guojing"


def _make_book(first_beat: str, second_beat: str) -> WorldBook:
    """测试书：4 条普通条目 + 1 条 lore_bindings 绑定条目。"""
    binding_data = nls.encode_bindings_for_worldbook({
        "targets": {
            "tree:n_root": {"entry_uids": ["core"], "sticky": True},
            f"beat:{second_beat}": {"entry_uids": ["geo"], "sticky": True},
            "combat:enc_x": {"entry_uids": ["tactic"], "sticky": False,
                             "inject": "always"},
        },
        "dormant_uids": ["spoiler"],
    }, "arknights")
    entries = [
        WorldBookEntry(uid="core", content="核心设定", trigger_keys=["核心"]),
        WorldBookEntry(uid="geo", content="地理设定", trigger_keys=["地理"]),
        WorldBookEntry(uid="tactic", content="伏击战术", trigger_keys=[]),
        WorldBookEntry(uid="spoiler", content="剧透", trigger_keys=["剧透"]),
        WorldBookEntry(uid=binding_data["uid"], content=binding_data["content"],
                       trigger_keys=[], raw=binding_data["raw"]),
    ]
    return WorldBook("arknights", name="测试书", entries=entries)


def _bind_session_scope(ov, book):
    ov.set_worldbook_scope({
        "book_id": book.id,
        "policy_revision": 1,
        "resolved_entry_uids": [e.uid for e in book.entries
                                if e.enabled and e.content.strip()],
    })


def _resolver(book, ov):
    return nls.build_overlay_resolver(book, ov)


def _eligible(ov, book):
    return book.eligible_uids_for(ov)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """全新剧情会话 + 测试世界书（绑定覆盖 root / 第二节拍 / 战斗）。"""
    monkeypatch.setattr(so, "_SESSIONS_DIR", tmp_path / "sessions")
    ov = SessionOverlay("sess_test_lore_scope", "story")
    ov.load_quests_from_plot(PLOT_ID)
    ov.init_session_docs(PLOT_ID)
    first_beat = ov.get_current_beat_id()
    assert first_beat, "剧情应有节拍"
    ov.advance_beat()
    second_beat = ov.get_current_beat_id()
    assert second_beat and second_beat != first_beat
    # 回到第一节拍，让测试从已知状态起步
    ov.jump_to_beat(first_beat)
    book = _make_book(first_beat, second_beat)
    _bind_session_scope(ov, book)
    return ov, book, first_beat, second_beat


def _commit(ov, book, **kw):
    return ov.commit_tree_step(lore_resolver=_resolver(book, ov), **kw)


# ── 默认关闭：无绑定条目时行为不变 ──

def test_no_bindings_book_behavior_unchanged(env):
    ov, book, _, _ = env
    plain = WorldBook("arknights", name="无绑定书", entries=[
        WorldBookEntry(uid="core", content="核心设定", trigger_keys=["核心"]),
    ])
    _bind_session_scope(ov, plain)
    ov.commit_tree_step(narrative="n0", title="根", round_num=1,
                        lore_resolver=_resolver(plain, ov))
    assert ov.get_active_lore_scope() is None, "无绑定条目 → 功能整体关闭"
    assert _eligible(ov, plain) == {"core"}
    node = ov.get_current_tree_node()
    assert node["state"].get("lore_scope") is None


# ── 作用域随节点冻结与演化 ──

def test_scope_freezes_and_evolves(env):
    ov, book, first_beat, second_beat = env
    _commit(ov, book, narrative="n0", title="根",
            branches=[{"label": "甲"}], round_num=1)
    r1 = _eligible(ov, book)
    assert r1 == {"core"}, f"根节点只带 tree:n_root 绑定: {r1}"

    _commit(ov, book, narrative="n1", title="甲", branches=[{"label": "甲1"}],
            branch={"label": "甲"}, round_num=2)
    r2 = _eligible(ov, book)
    assert r2 == {"core"}, "同节拍子节点继承 root 的 sticky 条目"

    ov.advance_beat()  # → second_beat
    _commit(ov, book, narrative="n2", title="甲1", branches=[],
            branch={"label": "甲1"}, round_num=3)
    r3 = _eligible(ov, book)
    assert r3 == {"core", "geo"}, f"推进到第二节拍应叠加 geo: {r3}"

    # 每个节点的作用域都已冻结进快照
    tree = ov.get_story_tree()
    cur = tree["nodes"][tree["current_id"]]
    assert sorted(cur["state"]["lore_scope"]["allowed"]) == ["core", "geo"]


def test_combat_hint_activates_pinned_entry(env):
    ov, book, _, _ = env
    _commit(ov, book, narrative="n0", title="根",
            branches=[{"label": "甲"}], round_num=1)
    node = _commit(ov, book, narrative="遭遇伏击", title="伏击",
                   branches=[{"label": "乙"}], branch={"label": "甲"}, round_num=2,
                   combat_id_hint="enc_x")
    assert "tactic" in _eligible(ov, book)
    # inject="always"：无关键词也注入（forced_uids 随候选集传递）
    matched = book.collect_matches("", "", eligible_uids=_eligible(ov, book))
    assert [e.uid for e in matched] == ["tactic"]
    # sticky=False：落到【新节点】即卸载（同节点续走按 §5.2 复用冻结作用域）
    assert "tactic" not in node["state"]["lore_scope"]["sticky_uids"]
    _commit(ov, book, narrative="战后", title="战后", branches=[],
            branch={"label": "乙"}, round_num=3)
    assert "tactic" not in _eligible(ov, book)


# ── §5.4 回档不变量 ──

def test_rollback_restores_scope_byte_identical(env):
    ov, book, _, _ = env
    _commit(ov, book, narrative="n0", title="根",
            branches=[{"label": "甲"}], round_num=1)
    node_a = _commit(ov, book, narrative="n1", title="甲",
                     branches=[{"label": "甲1"}], branch={"label": "甲"},
                     round_num=2)
    r2 = set(_eligible(ov, book))
    ov.advance_beat()
    _commit(ov, book, narrative="n2", title="甲1", branches=[],
            branch={"label": "甲1"}, round_num=3)
    r3 = set(_eligible(ov, book))
    assert r2 != r3, "前置：两轮候选集应不同，否则回归无意义"

    # 回档到第 2 轮节点：ACT 必须从节点快照整体还原
    ov.rollback_to_tree_node(node_a["id"],
                             lore_resolver_factory=lambda: _resolver(book, ov))
    assert set(_eligible(ov, book)) == r2
    cur = ov.get_current_tree_node()
    assert ov.get_active_lore_scope() == cur["state"]["lore_scope"]

    # 重走同一分支（复访既有节点）→ 候选集逐字节复现
    ov.advance_beat()
    _commit(ov, book, narrative="n2-重走", title="甲1", branches=[],
            branch={"label": "甲1"}, round_num=3)
    assert set(_eligible(ov, book)) == r3


def test_rollback_to_old_node_lazy_recompute(env):
    """快照里没有 lore_scope 的老节点：回档时惰性补算并写回。"""
    ov, book, _, _ = env
    # 先不挂 resolver 走两轮 → 节点快照无 lore_scope（模拟改造前的老会话）
    ov.commit_tree_step(narrative="n0", title="根",
                        branches=[{"label": "甲"}], round_num=1)
    node_a = ov.commit_tree_step(narrative="n1", title="甲", branches=[],
                                 branch={"label": "甲"}, round_num=2)
    assert node_a["state"].get("lore_scope") is None
    assert ov.get_active_lore_scope() is None

    # 回档到根节点（tree:n_root 绑定 core）：惰性补算并写回
    ov.rollback_to_tree_node("n_root",
                             lore_resolver_factory=lambda: _resolver(book, ov))
    scope = ov.get_active_lore_scope()
    assert scope is not None and "core" in scope["allowed"]
    # 补算结果已写回节点，二次回档直接还原不再重算
    assert ov.get_current_tree_node()["state"]["lore_scope"]["allowed"] \
        == scope["allowed"]


def test_legacy_overlay_without_scope_api(env):
    """eligible_uids=None（不过滤）的旧语义保留：overlay 无 scope 方法时。"""
    ov, book, _, _ = env

    class _Bare:
        pass

    assert book.eligible_uids_for(_Bare()) is None
    # 全量会话范围（无节点作用域）返回 EligibleSet 但语义等于 set
    assert _eligible(ov, book) == {"core", "geo", "tactic", "spoiler",
                                   "lore_bindings_arknights"}
