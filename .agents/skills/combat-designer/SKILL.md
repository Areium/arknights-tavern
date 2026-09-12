---
name: combat-designer
description: 设计/生成一场战斗（战斗节点 JSON）时使用——按威胁预算编排敌人与地形，先校验再试跑，达标后才入库；也用于把 LLM 生成的战斗规格变成可玩内容。禁止改引擎代码。
---

# 战斗设计（节点规格 → 校验 → 试跑 → 入库）

本 skill 规定"一场战斗"从构思到入库的完整流程与硬性约束。适用对象：人类设计者、
以及**代表设计者产出候选规格的 LLM/代理**。

## 0. 铁律

1. **只产出数据，不改引擎**：你的产物是 `data/combat/nodes/<node_id>.json`（或候选文件）。
   不要修改 `src/combat_engine/**`、`src/combat_session.py` 等运行时代码。
2. **先校验，后试跑，再入库**：`validate → simulate → 人工审阅 → 写入注册表`。
   未通过校验的规格不得入库；未试跑过的规格不得作为正式剧情战斗。
3. **不改别人负责的字段**：`bind.*`（剧情节拍绑定）由剧情侧决定，除非任务明确要求。
4. **数值要有依据**：宣称的 `difficulty.band` / `threat_budget` 必须与实际编排一致
   （用 `tools/balance_audit.py` 与校验器的威胁对照自查）。

## 1. 规格在哪儿、长什么样

- 完整字段说明与示例：`docs/battle-spec.md`（**先读它**）
- 模板：`data/combat/nodes/TEMPLATE_node.json`
- 参考实例：`data/combat/nodes/enc_training.json`（教学战）、`enc_snow_convoy.json`（剧情战）

最小可用规格的骨架（键名必须一致）：

```json
{
  "schema_version": 1,
  "node_id": "enc_xxx", "name": "显示名", "summary": "一句话处境",
  "bind": { "plot_id": "", "chapter_id": "", "beat_id": "" },
  "rules": { "range_metric": "manhattan", "allow_corner_cut": false },
  "map": { "rows": 7, "cols": 7, "tiles": "ground",
           "deploy": { "player": { "rect": [3,0,5,1] }, "enemy": { "rect": [3,5,5,6] } } },
  "waves": [ { "enemies": [ { "enemy": "整合运动士兵", "count": 2, "positions": [[3,5],[5,5]] } ] } ],
  "conditions": { "max_rounds": 8, "escape_enabled": true },
  "rewards": { "xp": 60, "items": [] },
  "difficulty": { "category": "test", "encounter_type": "normal",
                  "band": "T1", "threat_budget": 3.2, "target_rounds": 4 }
}
```

## 2. 流程

```bash
# ① 写候选（可先写到 /tmp 或工作区临时路径，不必入库）
$EDITOR candidate.json

# ② 校验：结构/地图/敌人/站位/威胁预算（退出码 1 = 有错）
python3 tools/validate_battle_spec.py candidate.json

# ③ 试跑：固定种子批量模拟，按阈值判断"好不好玩"
python3 tools/simulate_battle.py --spec candidate.json --runs 30 \
    --min-win-rate 0.6 --max-median-rounds 8 --max-hp-loss 0.6

# ④ 达标后入库（或交给编辑器 / 注册表接口）
cp candidate.json data/combat/nodes/enc_xxx.json
python3 tools/balance_audit.py            # 全局数值自洽性（含 XP 单调性）
```

也可以用 HTTP（应用运行时）：`POST /api/combat/nodes/validate`、
`POST /api/combat/nodes`、`PUT /api/combat/nodes/<id>`，或在
**内容中心 → 战斗节点** Tab 里可视化编辑（地图绘制/敌人编成/血量覆盖）。

## 3. 设计准则（v1 数值）

- **威胁预算**：`标准敌人 = 1.6 威胁`、`弱兵 1.0`、`强兵 2.2`、`精英 3.2`、`Boss 7.0`
  （见 `src/combat_balance.py`）。节点威胁 = Σ 威胁点 × 数量；阶段带参考区间
  `T0 1–3 / T1 3–6 / T2 6–10 / T3 10–16 / T4 16–30`。
- **难度节奏**：教学战 2–3 回合、普通 4–6、精英 6–10、Boss 8–12。
  中位回合明显偏快/偏慢时，先调 `max_rounds` 与敌人数量，再动单卡数值。
- **地形**：`wall`（阻挡 + 挡视线）用来切分战场、制造绕行；`cover`（加防/加闪避）
  给防守方支点；`hazard_fire` 逼走位；`high_ground`（加伤）奖励抢高地。
  地形不要切断两片部署区（校验器会报"不存在通路"软锁）。
- **数值覆盖**：`waves[].enemies[].stats = {"hp": 150}` 可逐单位调血量
  （Boss/精英常用），不需要改全局敌人条目。
- **阶段带缩放**（可选）：节点写 `difficulty.apply_band_scaling: true` 时，
  敌人数值按 `data/combat/rules/difficulty.json` 的带宽倍率缩放 ——
  一套敌人即可覆盖多个难度档。

## 4. 判定标准（"好不好玩"的可量化代理）

| 指标 | 期望 | 说明 |
|---|---|---|
| 胜率 | 60–90%（教学 90%+，精英/Boss 可 40–70%） | 100% 或 <30% 都要复核 |
| 中位回合 | 落在该类型的节奏区间 | 用 `target_rounds` 声明并接受审计 |
| 首回合清场率 | < 5%（Boss/精英 < 2%） | 过高说明玩家过强或敌人太散 |
| 血损率 | 教学 < 20%；普通 20–50%；精英/Boss 40–70% | 太低没张力 |
| 治疗溢出率 | < 30% | 过高说明伤害不足 |
| 每轮移动 AP | 明显高于 0 说明地形/站位在起作用 | 装备/走位权重 |

阈值未达标时**优先改编排**（地形、站位、波次、数量），最后才动数值缩放。

## 5. 交付格式（给上游的回报）

产出候选后回报：`node_id`、一句话设计意图、`validate` 结果、`simulate` 的关键指标
（胜率/中位回合/血损）、与声明预算的偏差、以及入库路径。若未入库，说明原因
（等审阅 / 数值待定 / 缺剧情绑定）。
