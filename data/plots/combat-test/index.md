---
category: test
id: combat_test
imports:
- plots/combat-test/narrative
- plots/combat-test/opening
- plots/combat-test/quests
- plots/combat-test/scenes
- plots/combat-test/setting
- plots/combat-test/pacing
name: 战斗功能测试
priority: 1
repeatable: true
summary: 快速战斗测试剧情，用于验证战斗触发→结算→回到对话的完整流程。开场即进入战斗，后续连续触发多波敌人。
trigger:
  keywords:
  - 战斗测试
  - 测试
  - 快速测试
deviation_policy:
  allow: false
effects: {}
tension_clock:
  stages: []
  final: ""
---
# 战斗功能测试

> 这是一个**纯测试用剧情**，用于快速验证战斗系统的完整流程：对话→战斗触发→战斗结算→回到对话→再次战斗。
> 不适合正常游玩。

## 文件索引

| 文件 | 内容 | 说明 |
|------|------|------|
| [opening.md](opening.md) | 开局设置 | 开场即战场，立即触发战斗 |
| [setting.md](setting.md) | 常量设定 | 测试场景设定 |
| [narrative.md](narrative.md) | 剧情叙述 | 连续战斗的叙事引导 |
| [scenes.md](scenes.md) | 场景配置 | 战斗节点的场景信息 |
| [quests.md](quests.md) | 任务记录 | 测试用任务 |
| [pacing.md](pacing.md) | 节奏设计 | 每轮触发战斗 |

## 测试流程

| 轮次 | 操作 | 预期结果 |
|------|------|---------|
| 第 1 轮 | 选择"继续推进剧情" | LLM 输出 `[COMBAT:enc_quick_test_1]`，进入第一波战斗 |
| 战斗 1 | 消灭士兵 → 返回对话 | 自动叙述战斗结果，场景推进 |
| 第 2 轮 | 自动叙述或点击继续 | LLM 输出 `[COMBAT:enc_quick_test_2]`，进入第二波战斗 |
| 战斗 2 | 消灭士兵 → 返回对话 | 自动叙述，场景推进 |
| 第 3 轮 | 自动叙述或点击继续 | LLM 输出 `[COMBAT:enc_quick_test_3]`，进入第三波战斗 |
| 战斗 3 | 消灭混编敌人 → 返回对话 | 全部测试完成 |
