---
category: main
deviation_policy:
  allow: true
  base_difficulty: -3
  require_confirm: true
effects:
  character_available:
  - 瑕光
  - 临光
  - 砾
  - 焰尾
  - 托兰
  faction_change:
    卡西米尔监证会: 友好
    商业联合会: 敌对或警惕
  unlock_locations:
  - 大骑士领竞技场
  - 卡瓦莱利亚基商业区
  - 红松骑士团藏身处
  unlock_plots:
  - near_light_aftermath
id: near_light
imports:
- plots/_deviation-handbook
- plots/near-light/narrative
- plots/near-light/pacing
- plots/near-light/opening
- plots/near-light/quests
- plots/near-light/scenes
- plots/near-light/setting
name: 长夜临光
prerequisites:
  faction_known:
  - 罗德岛
  - 卡西米尔
priority: 9
repeatable: false
summary: 罗德岛抵大骑士领，耀骑士归来，资本、荣耀与感染者命运的风暴来临。
tension_clock:
  final: 商业联合会彻底掌控局势，临光被迫退赛，感染者骑士被全部清除，罗德岛被驱逐出卡西米尔。瑕光在混乱中受重伤。长夜无尽。
  stages:
  - - 1
    - 第一天：感染者骑士杰米在赛场上被公开虐杀。罗德岛内部出现紧急讨论
  - - 3
    - 第三天：玛莉娅（瑕光）遭遇第一次绑架未遂。商业联合会开始对罗德岛施压
  - - 5
    - 第五天：无胄盟暗杀名单扩大。大停电计划被利用——整座城市陷入混乱
trigger:
  character:
  - 瑕光
  - 临光
  keywords:
  - 特锦赛
  - 骑士竞技
  - 卡西米尔
  - 感染者骑士
  - 商业联合会
  location:
  - 大骑士领卡瓦莱利亚基
---

# 长夜临光

> 罗德岛抵达大骑士领卡瓦莱利亚基。耀骑士归来。资本、荣耀、与感染者命运的风暴即将来临。
> **主视角**：瑕光（玛莉娅·临光）——天才工匠、临光的妹妹。

## 文件索引

| 文件 | 内容 | 说明 |
|------|------|------|
| [opening.md](opening.md) | 开局设置 | 开场场景、角色选取、可到达地点、场景流程图、开局对话流程、推荐配置 |
| [setting.md](setting.md) | 常量设定 | 核心冲突、定时炸弹、关键人物、势力关系、偏离策略、后续影响、伏笔 |
| [narrative.md](narrative.md) | 剧情叙述 | 剧情概述、章节大纲、关键节拍、对话方向、玩家选项、关键对话参考 |
| [scenes.md](scenes.md) | 场景配置 | 节点顺序、地点/时间/氛围/五感、出场角色/敌人、场景转换、偏离点判定 |
| [quests.md](quests.md) | 任务记录 | 主线任务链、支线任务、触发/完成条件、奖励 |
| [pacing.md](pacing.md) | 节奏设计 | 每章时间预算、战斗次数、对话轮数、任务触发时机 |

## 章节速览

| 章节 | ID | 核心事件 |
|------|-----|------|
| 1. 开幕的鲜血 | `blood_opener` | 罗德岛抵达 + 感染者骑士杰米被公开虐杀 |
| 2. 光芒与暗影 | `radiance_and_shadow` | 临光 vs 烛骑士 + 瑕光绑架未遂被托兰/红松阻止 |
| 3. 大停电之夜 | `blackout` | 红松潜入、玛恩纳守街、焰尾抉择、银枪天马入城 |
| 4. 长夜将明 | `dawn_approaches` | 逐魇一战 → 血骑士理念对决 → 临光演讲 → 瑕光赠礼 |