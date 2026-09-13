---
attributes:
  物理强度: 6
  战场机动: 9
  生理耐受: 6
  战斗技巧: 9
  源石技艺适应性: 4
  战术规划: 9
  情绪稳定性: 7
  魅力: 6
card_face: placeholder_skin.png
class: 狙击
default_avatar: enemy_1182_flasrt_3.png
default_skin: placeholder_skin.png
faction: 无胄盟
imports:
- classes/狙击
- factions/无胄盟
- factions/卡西米尔
- characters/白金
- characters/托兰
name: 青金莫妮克
race: 未公开
relationships:
  青金罗伊: 明确写在档案里的「讨厌」——两人的不和是博士可以撬动的情报缺口
  玄铁大位: 效忠的顶点——她记录、执行，不提问
  白金: 同僚——白金那句「我自己写报告」里，有一部分报告是写给她的
summary: 无胄盟青金大位，莫妮克。习惯是行动前详细记录自身状态，讨厌的东西是罗伊，以及所有打扰她工作的人。
tags:
- 卡西米尔
- 无胄盟
- 青金大位
- 杀手
- 狙击
theme_color: '#879ca8'
worldbook_id: arknights
---

# 角色背景

无胄盟青金大位，莫妮克。她的习惯是在行动前详细记录自身状态，讨厌的东西是罗伊，以及所有打扰她工作的人。

官方档案把「讨厌罗伊」直接写进了条目——这在大骑士领不是秘密，而是无胄盟内部裂痕的一个公开注脚。白金无意中的抱怨进一步印证了这一点：内部对商业联合会的不满正在增长，而两位青金彼此不和。

# 官方档案

> 无胄盟青金大位，莫妮克。习惯是在行动前详细记录自身状态，讨厌的东西是罗伊，以及所有打扰她工作的人。
>
> —— `enemy_handbook_table.json` · `enemy_1182_flasrt_3`

# 剧情定位（长夜临光）

- 支线 `sq_intel_from_platinum`（第二章）：她的名字被白金用来举例无胄盟的内部不和。
- 章节 3「大停电之夜」：作为无胄盟清洗行动的执行层存在（未单独出场，与罗伊并列）。

# 关键台词

- （本次剧情中未安排直接台词；她的存在主要通过白金的情报侧写呈现。）

# 备注

- 素材：官方**无半身立绘**，`avatar/` 取自敌人立绘 `enemy_1182_flasrt_3.png`（158×158），`skin/` 为占位图（待美术替换）。
- 战斗数值：未写死 `combat_stats`，由 `attributes` 按 `src/combat_balance.py` 同口径派生。
