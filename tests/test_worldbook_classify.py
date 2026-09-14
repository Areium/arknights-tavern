"""世界书条目自动分类：只认显式线索，识别不出就不分类。

覆盖三层：
  1. 纯分类器（信号优先级、白名单、冲突、角色关联）
  2. `WorldBook.from_dict` 的迁移守卫（空分类才补，已保存的分类不覆盖，不改载入模式）
  3. `POST /api/worldbook/<id>/auto-classify`（预览只读、应用落盘、revision 冲突）
"""
import copy
import json
from pathlib import Path
import sys

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from world_book import WorldBook, WorldBookEntry, WorldBookManager  # noqa: E402
from worldbook_classify import (  # noqa: E402
    PRESET_CATEGORIES, UNLINKED_CHARACTERS_ID, character_id_from_uid, classify_entries,
    classify_entry, has_reliable_metadata, needs_classification,
)
from worldbook_scope import UNCLASSIFIED, validate_categories  # noqa: E402


def entry(uid, name="", group="", character_id=""):
    return WorldBookEntry(uid=uid, content=f"content-{uid}", name=name, group=group,
                          character_id=character_id)


def pack_entries():
    """内置生成器写出的条目形态：uid 前缀、group、名称后缀三者一致。"""
    return [
        entry("world_01-basic-setting_index", name="泰拉世界基础设定（世界观设定）", group="世界观"),
        entry("rules_buff-pool_index", name="buff-pool（规则设定）", group="规则"),
        entry("races_乌萨斯_index", name="乌萨斯（种族设定）", group="种族"),
        entry("Location_01-罗德岛_index", name="罗德岛（地点设定）", group="地点"),
        entry("items_01-源石_index", name="源石（物品设定）", group="物品"),
        entry("enemies_01-整合运动_index", name="整合运动（敌人设定）", group="敌人"),
        entry("plots_01-序章_index", name="序章（剧情设定）", group="剧情"),
        entry("plot_graph_near-light", name="节点图：长夜临光"),
        entry("characters_阿米娅_index", name="阿米娅（角色设定）", group="角色"),
        entry("100", name="someone"),
    ]


@pytest.mark.parametrize("uid,category_id", [
    ("world_01-basic-setting_index", "worldview"),
    ("rules_buff-pool_index", "rules"),
    ("attributes_情绪稳定性_index", "attributes"),
    ("races_乌萨斯_index", "races"),
    ("classes_先锋_index", "classes"),
    ("weather_雷暴_index", "weather"),
    ("Location_01-罗德岛_index", "locations"),
    ("items_01-源石_index", "items"),
    ("enemies_01-整合运动_index", "enemies"),
    ("plots_01-序章_index", "plots"),
    ("plot_graph_near-light", "plot_graph"),
    ("characters_阿米娅_index", "characters"),
])
def test_uid_prefix_rules(uid, category_id):
    assert classify_entry(uid)[0] == category_id


def test_plot_graph_prefix_is_not_swallowed_by_plots():
    assert classify_entry("plot_graph_x")[0] == "plot_graph"
    assert classify_entry("plots_01-序章_index")[0] == "plots"


def test_group_and_name_suffix_are_fallbacks():
    assert classify_entry("100", group="敌人")[0] == "enemies"
    assert classify_entry("101", name="某种族（种族设定）")[0] == "races"
    assert classify_entry("102", name="Some Race", group="Races")[0] == "races"


def test_unknown_shapes_are_left_unclassified_instead_of_guessed():
    # 外部酒的 group（包含组/权重语义）与英文名字都不构成分类依据
    assert classify_entry("0", name="abductor virgins", group="group1")[0] is None
    assert classify_entry("1", name="alecto, black knife ringleader")[0] is None
    assert classify_entry("2", name="普通条目（近卫）")[0] is None
    assert has_reliable_metadata([entry("0", name="boss"), entry("1", name="mob")]) is False


def test_uid_prefix_wins_and_conflicts_are_reported():
    category_id, signals, votes = classify_entry("items_01-源石_index", group="敌人", name="源石（敌人设定）")
    assert category_id == "items" and signals[0] == "uid-prefix"
    assert votes == {"uid-prefix": "items", "group": "enemies", "name-suffix": "enemies"}
    result = classify_entries([entry("items_01-源石_index", group="敌人")])
    assert result.conflicts == {"items_01-源石_index": {"uid-prefix": "items", "group": "enemies"}}


def test_character_entries_need_a_catalog_id_to_stay_in_character_scope():
    assert character_id_from_uid("characters_阿米娅_index") == "阿米娅"
    assert character_id_from_uid("characters_index") is None
    assert character_id_from_uid("characters_阿米娅") is None
    assert classify_entry("characters_阿米娅_index")[0] == "characters"
    # 没有目录名就不能留在 character 分类：_validate_entry_scope 会拒绝保存
    assert classify_entry("characters_阿米娅")[0] == UNLINKED_CHARACTERS_ID
    assert classify_entry("characters_阿米娅", character_id="阿米娅")[0] == "characters"


def test_needs_classification_covers_missing_empty_and_only_unclassified():
    assert needs_classification(None) is True
    assert needs_classification([]) is True
    assert needs_classification([dict(UNCLASSIFIED)]) is True
    assert needs_classification([dict(UNCLASSIFIED), {"id": "worldview", "name": "世界观设定",
                                                      "scope_type": "worldview", "parent_id": None,
                                                      "sort_order": 10}]) is False


def test_proposal_keeps_parent_and_unclassified_and_passes_validation():
    result = classify_entries([entry("rules_buff-pool_index")])
    categories = validate_categories(result.categories())
    ids = [c["id"] for c in categories]
    assert ids == ["worldview", "rules", "unclassified"]
    parent = next(c for c in categories if c["id"] == "worldview")
    child = next(c for c in categories if c["id"] == "rules")
    assert child["parent_id"] == parent["id"] and child["scope_type"] == parent["scope_type"] == "worldview"


def test_proposal_reuses_user_renamed_categories():
    renamed = [{"id": "rules", "name": "我的规则", "scope_type": "worldview", "parent_id": None, "sort_order": 1}]
    result = classify_entries([entry("rules_buff-pool_index")])
    saved = {c["id"]: c for c in result.categories(existing=renamed)}
    assert saved["rules"]["name"] == "我的规则"


def test_preset_categories_are_valid_and_unique():
    categories = validate_categories([dict(c) for c in PRESET_CATEGORIES])
    assert len({c["id"] for c in categories}) == len(categories)
    by_id = {c["id"]: c for c in categories}
    for category in categories:
        if category["parent_id"]:
            assert by_id[category["parent_id"]]["scope_type"] == category["scope_type"]


# ── from_dict 迁移守卫 ────────────────────────────────────────────────

def raw_pack(entries=None, categories=None):
    data = {"id": "arknights", "name": "氪金整合包", "source": "preinstalled", "schema_version": 1,
            "entries": [e.to_dict() for e in (entries or pack_entries())]}
    if categories is not None:
        data["categories"] = categories
    return data


def test_empty_categories_are_treated_as_unclassified_and_classified(tmp_path):
    """磁盘上是 `categories: []`（被保存过的旧副本）也要补分类，但不切换载入模式。"""
    book = WorldBook.from_dict(raw_pack(categories=[]))
    assert book.scope_mode == "legacy", "旧书仅补分类，不隐式进入按需载入"
    assert [e.category_id for e in book.entries][:3] == ["worldview", "rules", "races"]
    assert book.entries[8].character_id == "阿米娅"
    names = {c["name"] for c in book.categories}
    assert {"世界观设定", "规则设定", "种族设定", "角色设定", "物品设定", "节点图", "未分类"} <= names
    assert book.entries[9].category_id == "unclassified"
    assert book.category_scope_type("rules") == "worldview"


def test_first_install_without_categories_key_keeps_entering_selective():
    """分发源没有 categories 字段：预装包首次安装沿用「直接进入按需载入」的既有语义。"""
    book = WorldBook.from_dict(raw_pack())
    assert book.scope_mode == "selective"
    assert book.entries[0].category_id == "worldview"


def test_saved_taxonomy_is_never_overwritten():
    saved = [{"id": "mine", "name": "我的分类", "scope_type": "other", "parent_id": None, "sort_order": 1},
             dict(UNCLASSIFIED)]
    book = WorldBook.from_dict(raw_pack(categories=copy.deepcopy(saved)))
    assert [c["id"] for c in book.categories] == ["mine", "unclassified"]
    assert all(e.category_id == "unclassified" for e in book.entries)


def test_external_books_without_signals_are_left_alone():
    data = {"id": "er", "name": "外部书", "source": "imported", "entries": [
        entry("0", name="abductor virgins").to_dict(),
        entry("1", name="alecto").to_dict()]}
    book = WorldBook.from_dict(data)
    assert [c["id"] for c in book.categories] == ["unclassified"]
    assert all(e.category_id == "unclassified" for e in book.entries)
    assert book.scope_mode == "legacy"


def test_imported_book_with_generator_metadata_is_not_auto_classified_on_load():
    """自动迁移只服务预装包；导入书要走用户显式的「自动分类」。"""
    data = raw_pack(categories=[])
    data["source"] = "imported"
    book = WorldBook.from_dict(data)
    assert [c["id"] for c in book.categories] == ["unclassified"]
    assert all(e.category_id == "unclassified" for e in book.entries)


def test_missing_parent_is_never_left_behind():
    """只识别出子分类时也要补上父分类，否则 validate_categories 会拒绝整份分类。"""
    book = WorldBook.from_dict(raw_pack(entries=[entry("rules_buff-pool_index")], categories=[]))
    assert {c["id"] for c in book.categories} == {"worldview", "rules", "unclassified"}


# ── API ──────────────────────────────────────────────────────────────

@pytest.fixture
def api(tmp_path):
    from blueprints.worldbook import register
    manager = WorldBookManager(tmp_path)
    book = WorldBook.from_dict(raw_pack(categories=[]))
    manager.save(book)
    app = Flask(__name__)
    app.config["TESTING"] = True
    register(app, {"worldbook": manager})
    return app.test_client(), manager, book


def test_api_auto_classify_preview_is_read_only(api):
    client, manager, book = api
    path = manager._path(book.id)
    original = path.read_bytes()
    response = client.post("/api/worldbook/arknights/auto-classify", json={})
    assert response.status_code == 200
    payload = response.json
    assert payload["apply"] is False and payload["matched"] == 9 and payload["unmatched_count"] == 1
    assert payload["character_links"] == 1
    counts = {c["id"]: c["count"] for c in payload["categories"]}
    assert counts["worldview"] == 1 and counts["items"] == 1 and counts["plot_graph"] == 1
    assert payload["unmatched"] == ["100"]
    assert any(c["id"] == "rules" for c in payload["proposal"])
    assert path.read_bytes() == original, "预览不得写盘"


def test_api_auto_classify_apply_persists_without_switching_scope_mode(api):
    client, manager, book = api
    revision = manager.load(book.id).import_config["revision"]
    response = client.post("/api/worldbook/arknights/auto-classify",
                           json={"apply": True, "expected_revision": revision})
    assert response.status_code == 200
    detail = response.json["book"]
    assert detail["scope_mode"] == "legacy", "编辑分类不隐式退出旧书兼容模式"
    assert detail["import_config"]["revision"] == revision + 1
    by_uid = {e["uid"]: e for e in detail["entries"]}
    assert by_uid["races_乌萨斯_index"]["category_id"] == "races"
    assert by_uid["characters_阿米娅_index"]["category_id"] == "characters"
    assert by_uid["characters_阿米娅_index"]["character_id"] == "阿米娅"
    assert by_uid["100"]["category_id"] == "unclassified"
    on_disk = json.loads(manager._path(book.id).read_text(encoding="utf-8"))
    assert {c["id"] for c in on_disk["categories"]} >= {"worldview", "rules", "characters", "items"}
    assert manager.load(book.id).entries[1].category_id == "rules"


def test_api_auto_classify_revision_conflict_and_no_signal_book(tmp_path):
    from blueprints.worldbook import register
    manager = WorldBookManager(tmp_path)
    book = WorldBook.from_dict(raw_pack(categories=[]))
    manager.save(book)
    plain = WorldBook("plain", "外部书", [entry("0", name="abductor virgins")], source="imported")
    manager.save(plain)
    app = Flask(__name__)
    app.config["TESTING"] = True
    register(app, {"worldbook": manager})
    client = app.test_client()

    assert client.post("/api/worldbook/arknights/auto-classify",
                       json={"apply": True, "expected_revision": 99}).status_code == 409
    before = manager.load("plain").entries[0].category_id
    response = client.post("/api/worldbook/plain/auto-classify", json={"apply": True})
    assert response.status_code == 200
    assert response.json["matched"] == 0 and "没有可用的分类线索" in response.json["reason"]
    assert manager.load("plain").entries[0].category_id == before
