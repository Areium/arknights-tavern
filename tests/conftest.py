"""pytest 全局钩子。

**测试残留战斗节点的自愈清理**

`tests/test_combat_nodes.py` 与 `tests/test_combat_growth_balance.py` 会在
`data/combat/nodes/` 下临时建节点文件，正常路径由 `finally` 删掉。但若用例在
进入 `try` 之前就失败（典型：上次残留让 `POST /api/combat/nodes` 返回 400
「已存在」，而那句 assert 在 `try` 之外），`finally` 永远不会执行，残留就此
留下；下一次运行时：

1. `test_combat_map.py::test_all_shipped_nodes_have_valid_maps` 是**收集期**
   按节点文件参数化的，多出一个幽灵参数用例；
2. `test_combat_nodes.py` 的 CRUD 用例继续在第一个 assert 失败，继续清不掉。

于是形成「一次污染 → 永久失败」的自锁（曾长期让 5 个用例假红，掩盖真实回归）。
conftest 在测试模块被收集**之前**导入，因此在这里清残留可以彻底断开该循环。
"""

from pathlib import Path

_NODE_DIR = Path(__file__).resolve().parent.parent / "data" / "combat" / "nodes"

#: 仅由测试临时创建、不应长期存在的节点 id
_STALE_TEST_NODES = (
    "enc_crud_test", "enc_empty_test", "enc_band_scaling_test", "enc_book_import",
)

for _node_id in _STALE_TEST_NODES:
    try:
        (_NODE_DIR / f"{_node_id}.json").unlink(missing_ok=True)
    except OSError:  # 权限/占用等：不该因为清理失败而阻断整个测试会话
        pass
