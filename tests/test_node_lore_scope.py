# -*- coding: utf-8 -*-
"""节点级世界书绑定求解器（src/node_lore_scope.py）的纯函数单测。

不触文件系统：绑定条目 / 世界书全部在内存里构造。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import node_lore_scope as nls  # noqa: E402
from world_book import WorldBookEntry  # noqa: E402


def _entry(uid, content="正文", **kw):
    return WorldBookEntry(uid=uid, content=content, **kw)


def _book(entries, book_id="arknights", related_edges=None):
    return SimpleNamespace(id=book_id, entries=list(entries),
                           related_edges=list(related_edges or []))


def _bindings_entry(book_id="arknights", targets=None, dormant=None):
    payload = {"targets": targets or {}, "dormant_uids": dormant or []}
    data = nls.encode_bindings_for_worldbook(payload, book_id)
    return WorldBookEntry(uid=data["uid"], content=data["content"],
                          trigger_keys=[], raw=data["raw"])


KNOWN = {"a", "b", "c", "d", "e"}


# ── 编码 / 解码 / 定位 ──

def test_encode_decode_roundtrip():
    payload = {"targets": {"beat:b1": {"entry_uids": ["a"]}}, "dormant_uids": ["z"]}
    data = nls.encode_bindings_for_worldbook(payload, "arknights")
    entry = WorldBookEntry(uid=data["uid"], content=data["content"], raw=data["raw"])
    assert nls.is_lore_bindings_entry(entry)
    out = nls.decode_bindings(entry)
    assert out["book_id"] == "arknights"
    assert out["schema_version"] == nls.SCHEMA_VERSION
    assert out["targets"]["beat:b1"]["entry_uids"] == ["a"]


def test_is_bindings_entry_by_fence_only():
    entry = _entry("x", content='前 ```json arknights_tavern_lore_bindings\n{}\n``` 后')
    assert nls.is_lore_bindings_entry(entry)
    assert nls.decode_bindings(entry) == {}


def test_decode_non_bindings_returns_none():
    assert nls.decode_bindings(_entry("x", content="普通条目")) is None
    assert nls.decode_bindings(_entry("x", content="```json arknights_tavern_lore_bindings\n坏{\n```")) is None


def test_find_bindings_none_when_absent():
    book = _book([_entry("a")])
    assert nls.find_bindings(book) == (None, "")


def test_find_bindings_first_and_fingerprint():
    b1 = _bindings_entry(targets={"beat:x": {"entry_uids": ["a"]}})
    b2 = nls.encode_bindings_for_worldbook({"targets": {}}, "arknights")
    b2 = WorldBookEntry(uid="lore_bindings_2", content=b2["content"], raw=b2["raw"])
    book = _book([_entry("a"), b1, b2])
    payload, fp = nls.find_bindings(book)
    assert payload["targets"]["beat:x"]["entry_uids"] == ["a"]
    assert fp and isinstance(fp, str)


# ── resolve_scope 基本语义 ──

def _resolve(targets, *, path_scopes=None, known=KNOWN, dormant=None, **kw):
    bindings = {"book_id": "arknights", "targets": targets,
                "dormant_uids": dormant or []}
    return nls.resolve_scope(node_id="n_x", path_scopes=path_scopes or [],
                             bindings=bindings, known_uids=known,
                             bindings_fingerprint="fp1", **kw)


def test_explicit_filtered_by_known():
    sc = _resolve({"beat:b1": {"entry_uids": ["a", "ghost"]}}, beat_id="b1")
    assert sc["explicit"] == ["a"]
    assert sc["allowed"] == ["a"]
    assert sc["sticky_uids"] == ["a"]      # sticky 默认 true
    assert sc["keys"] == ["tree:n_x", "beat:b1"]


def test_sticky_false_not_passed_down():
    parent = _resolve({"combat:enc": {"entry_uids": ["a"], "sticky": False}},
                      combat_id_hint="enc")
    assert parent["allowed"] == ["a"]
    assert parent["sticky_uids"] == []     # 非 sticky 不进继承集
    child = _resolve({}, path_scopes=[parent])
    assert child["allowed"] == []          # 后代不继承


def test_inheritance_chain():
    root = _resolve({"tree:n_root": {"entry_uids": ["a"]}})
    # tree:n_root 的 key 只有 node_id 匹配才命中；这里直接构造祖先作用域
    root = dict(root, sticky_uids=["a"], allowed=["a"])
    child = _resolve({"beat:b2": {"entry_uids": ["b"]}}, beat_id="b2",
                     path_scopes=[root])
    assert child["inherited"] == ["a"]
    assert child["allowed"] == ["a", "b"]


def test_dormant_and_explicit_reintroduce():
    sc = _resolve({"beat:b1": {"entry_uids": ["a", "e"]}}, beat_id="b1",
                  dormant=["e"])
    assert sc["allowed"] == ["a", "e"]     # 显式写名 = 当场解禁
    # 继承来的 e 仍被休眠拦住
    parent = dict(sc, sticky_uids=["e"], allowed=["e"], pinned=[], overrides={})
    child = _resolve({}, path_scopes=[parent], dormant=["e"])
    assert child["allowed"] == []


def test_pinned_respects_dormant():
    sc = _resolve({"beat:b1": {"entry_uids": ["e"], "inject": "always"}},
                  beat_id="b1", dormant=["e"])
    # 显式解禁后 allowed 含 e，pinned 与 allowed 求交后保留
    assert sc["allowed"] == ["e"]
    assert sc["pinned"] == ["e"]


def test_pinned_inheritance_boundary():
    parent = _resolve({"beat:b1": {"entry_uids": ["a"], "inject": "always",
                                   "sticky": False}},
                      beat_id="b1")
    assert parent["pinned"] == ["a"]
    child = _resolve({}, path_scopes=[parent])
    assert child["pinned"] == []           # 非 sticky 的钉入不下传


def test_overrides_nearest_wins():
    parent = _resolve({"beat:b1": {"entry_uids": ["a"],
                                   "inject_position": {"position": 1}}},
                      beat_id="b1")
    child = _resolve({"beat:b2": {"entry_uids": ["a"],
                                  "inject_position": {"group_weight": 5}}},
                     beat_id="b2", path_scopes=[parent])
    assert child["overrides"]["a"] == {"group_weight": 5}
    # 孙代无覆盖时继承最近祖先的
    grand = _resolve({}, path_scopes=[parent, child])
    assert grand["overrides"]["a"] == {"group_weight": 5}


# ── 关系图展开 ──

def test_freeze_neighbours_depth_and_known():
    edges = [{"from_uid": "a", "to_uid": "b"},
             {"from_uid": "b", "to_uid": "c"},
             {"from_uid": "c", "to_uid": "a"}]          # 环：不应死循环
    assert nls.freeze_neighbours({"a"}, edges, depth=1, known_uids=KNOWN) == {"b"}
    assert nls.freeze_neighbours({"a"}, edges, depth=2, known_uids=KNOWN) == {"b", "c"}
    assert nls.freeze_neighbours({"a"}, edges, depth=2, known_uids={"b"}) == {"b"}


def test_expand_frozen_into_scope():
    edges = [{"from_uid": "a", "to_uid": "b"}]
    sc = _resolve({"beat:b1": {"entry_uids": ["a"],
                               "expand": {"depth": 1, "relation": "related"}}},
                  beat_id="b1", related_edges=edges)
    assert sc["expanded"] == ["b"]
    assert sc["allowed"] == ["a", "b"]
    assert sc["sticky_uids"] == ["a", "b"]


# ── build_resolver：复用与补算 ──

def test_build_resolver_none_without_bindings():
    book = _book([_entry("a")])
    assert nls.build_resolver(book, known_uids=KNOWN) is None


def test_resolver_reuses_prev_on_same_fingerprint():
    binding = _bindings_entry(targets={"beat:b1": {"entry_uids": ["a"]}})
    book = _book([_entry("a"), binding])
    resolver = nls.build_resolver(book, known_uids=KNOWN, beat_id="b1")
    assert resolver is not None
    node = {"id": "n_1", "parent_id": None}
    first = resolver(node, None, {"n_1": node}, "")
    assert first["allowed"] == ["a"]
    # 同指纹 → 原样复用（即使换个节点 id，幂等键命中就不重算）
    sentinel = dict(first, node_id="n_1")
    again = resolver(node, sentinel, {"n_1": node}, "")
    assert again is sentinel


def test_resolver_walks_parents_for_inheritance():
    binding = _bindings_entry(targets={"beat:b1": {"entry_uids": ["a"]}})
    book = _book([_entry("a"), binding])
    resolver = nls.build_resolver(book, known_uids=KNOWN, beat_id="b1")
    root = {"id": "n_root", "parent_id": None, "state": {
        "lore_scope": {"sticky_uids": ["a"], "allowed": ["a"],
                       "pinned": [], "overrides": {}}}}
    child = {"id": "n_c", "parent_id": "n_root"}
    nodes = {"n_root": root, "n_c": child}
    sc = resolver(child, None, nodes, "")
    assert sc["inherited"] == ["a"]
    assert sc["allowed"] == ["a"]


# ── validate_bindings ──

def test_validate_ok():
    binding = _bindings_entry(targets={"beat:b1": {"entry_uids": ["a"]}})
    book = _book([_entry("a"), binding])
    payload, _ = nls.find_bindings(book)
    assert nls.validate_bindings(book, payload) == []


def test_validate_reports_all_bad_refs():
    binding = _bindings_entry()
    book = _book([_entry("a"), _entry("c", always_active=True),
                  _entry("d", enabled=False), binding])
    payload = {
        "targets": {
            "beat:b1": {"entry_uids": ["ghost", "c", "d", binding.uid]},
            "beat:b2": {"entry_uids": ["a"], "inject": "sometimes"},
            "beat:b3": {"entry_uids": ["a"], "inject_position": {"priority": 1}},
        },
        "dormant_uids": "not-a-list",
    }
    errors = nls.validate_bindings(book, payload)
    text = "\n".join(errors)
    assert "不存在的条目: ghost" in text
    assert "always_active" in text
    assert "已停用" in text
    assert "绑定条目自身" in text
    assert "match / always" in text
    assert "未知键: priority" in text
    assert "dormant_uids 必须是数组" in text
