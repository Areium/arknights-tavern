# -*- coding: utf-8 -*-
"""节点级世界书绑定 API（GET/PUT /api/worldbook/<book_id>/lore-bindings）。

隔离 WorldBookManager(tmp_path)，不触碰真实 data/worldbooks/。
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import node_lore_scope as nls  # noqa: E402
from world_book import WorldBook, WorldBookEntry, WorldBookManager  # noqa: E402


@pytest.fixture()
def api(tmp_path):
    from blueprints.worldbook import register
    manager = WorldBookManager(tmp_path)
    manager.save(WorldBook("book", "测试书", [
        WorldBookEntry("a", content="角色A", trigger_keys=["A"]),
        WorldBookEntry("b", content="常驻条目", always_active=True),
    ]))
    app = Flask(__name__)
    app.config["TESTING"] = True
    register(app, {"worldbook": manager, "llm_backend": None})
    return app.test_client(), manager


def test_get_empty(api):
    client, _ = api
    body = client.get("/api/worldbook/book/lore-bindings").get_json()
    assert body["bindings"] is None
    assert body["fingerprint"] == ""


def test_put_then_get_roundtrip(api):
    client, manager = api
    payload = {"targets": {"beat:beat_x": {"entry_uids": ["a"], "sticky": True,
                                           "inject": "always"}},
               "dormant_uids": []}
    res = client.put("/api/worldbook/book/lore-bindings", json=payload)
    assert res.status_code == 200, res.get_json()

    body = client.get("/api/worldbook/book/lore-bindings").get_json()
    assert body["bindings"]["targets"]["beat:beat_x"]["entry_uids"] == ["a"]
    assert body["fingerprint"]

    # 落盘的绑定条目自身永不注入：空触发键且非常驻
    book = manager.load("book")
    binding = next(e for e in book.entries if nls.is_lore_bindings_entry(e))
    assert binding.trigger_keys == []
    assert not binding.always_active


def test_put_replaces_single_entry(api):
    client, manager = api
    for i in range(2):
        res = client.put("/api/worldbook/book/lore-bindings",
                         json={"targets": {"beat:b": {"entry_uids": ["a"]}}})
        assert res.status_code == 200, res.get_json()
    book = manager.load("book")
    assert sum(1 for e in book.entries if nls.is_lore_bindings_entry(e)) == 1


def test_put_rejects_bad_refs(api):
    client, _ = api
    res = client.put("/api/worldbook/book/lore-bindings", json={
        "targets": {"beat:x": {"entry_uids": ["ghost"]}}})
    assert res.status_code == 400
    assert "ghost" in res.get_json()["error"]

    # 常驻条目禁止绑定（会打碎前缀缓存）
    res = client.put("/api/worldbook/book/lore-bindings", json={
        "targets": {"beat:x": {"entry_uids": ["b"]}}})
    assert res.status_code == 400
    assert "always_active" in res.get_json()["error"]


def test_put_empty_targets_disables(api):
    client, _ = api
    client.put("/api/worldbook/book/lore-bindings",
               json={"targets": {"beat:x": {"entry_uids": ["a"]}}})
    res = client.put("/api/worldbook/book/lore-bindings", json={"targets": {}})
    assert res.status_code == 200
    # 空 targets = 关闭：find_bindings 视为无绑定
    assert client.get("/api/worldbook/book/lore-bindings").get_json()["bindings"] is None
