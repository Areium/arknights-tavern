# 战斗规格（Battle Spec）

> 面向：人类设计者、以及**生成战斗内容的 LLM/代理**。
> 权威实现：`src/combat_map.py`（地图）、`src/combat_nodes.py`（校验）、
> `src/combat_balance.py`（威胁模型）；示例 `data/combat/nodes/TEMPLATE_node.json`。
> 配套工具：`tools/validate_battle_spec.py`（校验）、`tools/simulate_battle.py`（试跑）、
> `tools/balance_audit.py`（全局数值审计）；流程规范见 skill `combat-designer`。

一场战斗 = **一个 JSON 文件** `data/combat/nodes/<node_id>.json`。它自带地图、敌人与
数值覆盖，是**自包含**的：可以整份塞进世界书条目分发（见文末），也可以由程序生成。

---

## 1. 顶层字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `schema_version` | int | 否 | 目前恒为 1 |
| `node_id` | string | ✅ | 唯一 id；允许中英文/数字/`_`/`-`，≤64 字符；**与文件名一致**（`TEMPLATE_*` 除外） |
| `name` | string | ✅ | 显示名（前端下拉、战前卡片、结算播报用） |
| `summary` | string | 否 | 一句话处境，显示在战前卡片 |
| `description` | string | 否 | 更长的 markdown 背景（设计者/LLM 备注） |
| `bind` | object | 否 | 剧情节拍绑定：`{plot_id, chapter_id, beat_id}`；剧情文档里用 `[COMBAT:<node_id>]` 引用 |
| `rules` | object | 否 | `{range_metric: "manhattan"\|"chebyshev", allow_corner_cut: bool}`，默认曼哈顿 + 禁止切角 |
| `map` | object | ✅ | 战场（第 2 节） |
| `waves` | array | ✅ | 波次（第 3 节）；至少 1 个敌人，否则开战会被拒绝 |
| `enemies_def` | object | 否 | 内联敌人定义（`{名字: {combat_stats, ai_behavior, ai_skills, attributes...}}`），优先于全局敌人库；用于自包含分发 |
| `conditions` | object | 否 | `{max_rounds: int, escape_enabled: bool}` |
| `rewards` | object | 否 | `{xp: int, items: [string], unlock: [string]}` |
| `difficulty` | object | 否 | `{category, encounter_type, band, threat_budget, target_rounds, difficulty, apply_band_scaling}` |
| `background` | string | 否 | 背景 id（`data/combat/backgrounds/<id>/`）；缺省用 default |
| `balance_version` | int | 否 | 目前为 1 |

`difficulty.band` 取 `T0–T4`；`encounter_type` 取 `teaching | normal | elite | boss`；
`category` 取 `story | test | event`。**这些不是装饰**：审计工具会用它们的参考区间
判断你的编排是否与声称的难度一致。

---

## 2. 地图 `map`

```jsonc
"map": {
  "rows": 9, "cols": 12,                 // 1..40，且 rows*cols ≤ 1200
  "tiles": "ground",                     // 简写：整图同一格类型
  // 或二维数组（每格一个 tile_id）：
  // "tiles": [["ground","wall"],["cover","ground"]],
  "tile_defs": {                         // 内联格子定义（覆盖全局注册表）
    "wall":  { "blocks_movement": true, "blocks_los": true },
    "cover": { "name": "掩体", "glyph": "H", "color": "#a16207",
               "defense_bonus": 2, "evasion_bonus": 1 }
  },
  "deploy": {                            // 缺省按左右三分之一推导
    "player": { "rect": [3, 0, 5, 1] },  // 矩阵对角（含端点）[r0,c0,r1,c1]
    "enemy":  { "cells": [[3, 5], [5, 5]] },  // 或显式坐标
    "enemy_random_shift": false          // true = 敌人落点在部署区内随机
  }
}
```

**格子可用字段**（未知字段只警告、不报错，便于扩展）：

| 字段 | 默认 | 作用 |
|---|---|---|
| `blocks_movement` | false | 不可通行（墙） |
| `blocks_los` | false | 阻挡视线（远程攻击需视线；起点/终点所在格不参与判定） |
| `move_cost` | 1 | 通行代价（斜向步 = ×2） |
| `defense_bonus` / `evasion_bonus` | 0 | 站在此格受到的减伤 / 加闪避 |
| `damage_bonus` | 0 | 站在此格攻击的加伤（高台） |
| `on_enter` / `on_round_start` | `{}` | `{damage, heal, status, stacks}`；`status` 取 shield/slow/bind/weaken/strengthen/silence/burn/taunt/evade/blind |
| `glyph` / `color` / `name` | — | 前端渲染与悬停提示 |
| `deployable_player` / `deployable_enemy` | true | 是否允许部署（预留） |

内置格子：`ground`、`wall`、`cover`、`high_ground`、`hazard_fire`；项目可在
`data/combat/tiles/*.json` 追加（字段同上 + `tile_id`）。

**地形设计要点**：墙用来切分战场与挡视线；掩体给防守支点；火场逼走位；高台奖励抢点。
不要用墙把两个部署区完全隔开 —— 校验器会报 `玩家部署区与敌人部署区之间不存在通路`。

---

## 3. 波次 `waves`

```jsonc
"waves": [
  { "enemies": [
      { "enemy": "整合运动士兵", "count": 2, "positions": [[3,5],[5,5]] },
      { "enemy": "山雪鬼队长", "count": 1, "positions": [[4,6]],
        "stats": { "hp": 220 } }        // 逐单位数值覆盖（绝对值，覆盖文件数值）
  ] },
  { "enemies": [ { "enemy": "冰原术师", "count": 1 } ] }   // 第 2 波：清空第 1 波后入场
]
```

- `count` 1–12/波；波次 ≤6；敌人总数 ≤48。
- `positions` 个数与 `count` 不一致时只警告（缺的会落到敌方部署区空格）；
  站位必须在地图内且不在阻挡格，否则报错。
- `stats` 可覆盖 `hp/patk/matk/defense/resist/spd/hit/eva/max_ap`
  （外加 `ai_behavior`/`ai_skills`/`action_slots`/`threat_points`）。
- 第 2 波及以后的入场格若被占，引擎会自动顺延到最近空格（不会卡死，也不会覆盖已有单位）。

**敌人来源优先级**：`enemies_def` 内联 → 会话自定义敌人 → `data/enemies/*.md`。
全局敌人条目只有叙事 `attributes` 而没有 `combat_stats` 时，战斗数值按属性派生。

---

## 4. 威胁与阶段带（生成时的数值锚点）

五类模板（`src/combat_balance.py`）：

| 模板 | 相对生命 | 相对输出 | 威胁点 | 行动槽 |
|---|---:|---:|---:|---:|
| minion | 0.675 | 0.725 | 1.0 | 1 |
| standard | 1.000 | 1.000 | 1.6 | 1 |
| strong | 1.375 | 1.175 | 2.2 | 1 |
| elite | 1.800 | 1.250 | 3.2 | 2 |
| boss | 4.250 | 1.350 | 7.0 | 2 |

相对生命 = `hp / 100`；相对输出 = `(0.5×patk + 7.5) / 20`。分类取最近邻；
敌人条目声明了 `role`/`power_tier` 时以声明为准。

阶段带参考区间（`data/combat/rules/difficulty.json`）：

| 阶段带 | 威胁区间 | 敌人数值倍率（开启缩放时） |
|---|---|---|
| T0 | 1–3 | hp ×0.8 / atk ×0.8 |
| T1 | 3–6 | ×1.0 / ×1.0 |
| T2 | 6–10 | ×1.2 / ×1.15 |
| T3 | 10–16 | ×1.45 / ×1.3 |
| T4 | 16–30 | ×1.75 / ×1.5 |

校验器把"实际威胁 vs `threat_budget`"和"声明阶段带 vs 实际威胁"作为**警告**输出
（容差 25%）；`tools/balance_audit.py --strict` 可把它们升级为退出码。

---

## 5. 校验规则（会阻止入库/开战的硬错误）

1. `node_id`/`name` 缺失，或 `node_id` 含非法字符；
2. `map` 缺失、`rows/cols` 非正、超过 40×40 或 1200 格；
3. `tiles` 维度与 `rows/cols` 不符、引用了未定义的 `tile_id`；
4. `waves` 为空、波次 >6、`count` 越界（1–12）、总数 >48、完全没有敌人；
5. 敌人名称既不在 `enemies_def` 也不在全局敌人库；
6. 站位越界 / 落在 `blocks_movement` 格；
7. 节点没有任何可出场的敌人时开战被拒（`400 战斗节点「…」没有可出场的敌人`）。

**警告**（不阻断）：站位数与数量不符、同波次站位重复、未被声明部署区（按三分之一推导）、
软锁（部署区之间无通路）、威胁与预算/阶段带明显不符、未知格子字段/未知状态效果。

---

## 6. 生成 → 校验 → 试跑 → 入库

```bash
python3 tools/validate_battle_spec.py candidate.json          # 结构+数值自洽
python3 tools/simulate_battle.py --spec candidate.json --runs 30 \
    --min-win-rate 0.6 --max-median-rounds 8 --max-hp-loss 0.6  # 好不好玩
python3 tools/balance_audit.py                                 # 全局审计（含 XP 单调性）
```

`simulate_battle.py` 输出胜率 / 中位回合 / P90 / 首回合清场率 / 治疗溢出率 / 血损率 /
每轮出牌与移动 AP；相同种子结果可复现，因此可作为**生成循环的判据**：

```
LLM 产出候选 → validate（结构门禁）→ simulate（体验门禁）→ 人工/自动审阅 → 写入 nodes/
```

调优优先级：**先改编排**（地形、站位、波次、数量），再动 `stats` 覆盖，最后才动
全局敌人条目或带宽倍率。

---

## 7. 随世界书分发

节点可编码为一条酒馆兼容的世界书条目：

````markdown
```json combat-node
{"schema_version":1,"node_id":"enc_xxx", ...整份规格（可压成一行）... }
```
（可选说明文字）
````

并带 `raw.extensions.arknights_tavern = {"entry_type":"combat_node","node_id":"enc_xxx"}`。
导入世界书时程序**自动落地**为节点文件（校验失败会逐条返回错误、不写半成品）；
导出时从注册表回灌最新规格。因此第三方内容包可以自带战斗，肉鸽生成物也能直接入册。
