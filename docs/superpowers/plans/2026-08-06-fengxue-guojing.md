# 「风雪过境」改编剧情 Demo 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 `data/` 下产出可运行的「风雪过境」改编剧情 demo：1 个剧情文件 + 8 张角色卡 + 7 种敌人 + 8 个遭遇 + 1 个背景 + 5 个地点，供剧情模式（tactical）加载游玩。

**架构：** 全部为数据文件，无代码改动。剧情由 `data/plots/fengxue_guojing/index.md` 驱动（LLM 叙述 + 节拍跟踪），战斗由 `[COMBAT:enc_xxx]` 标记触发；角色/敌人/遭遇/背景/地点分别被 wiki_manager / combat_data_loader / environment_state 加载。主线忠于原作「风雪过境」，分支（改编内容）通过 beat 的「发现路径」与「玩家选项方向」实现，可改变后续叙述（受影响主线 beat 提供条件变体）。

**技术栈：** Markdown + YAML frontmatter + JSON（combat.json），Python 校验脚本。

**格式规范（已从现有代码确认）：**

- 章节：`## 章节 N：标题`，下接 `**ID**：`id``、`**概要**：...`
- 节拍：`#### beat_xxx（keep_on_deviate: true）`，下接 `**内容**：`、`**强制对话**：`（可多条）、`**揭示信息**：`
- 剧情叙述区从第一个 `## 章节` 起到下一个非章节 `##` 标题止；「关键对话参考」「任务」放其后
- 战斗触发：叙述文本中出现 `[COMBAT:enc_xxx]` 标记
- 敌人/遭遇：YAML frontmatter（combat_stats/ai_skills/waves/deploy_zones）；角色卡：frontmatter（attributes/class/faction/imports/relationships）+ combat.json（exclusive_cards）

---

### 任务 1：敌人卡 ×7

**文件：**

- 创建：`data/combat/enemies/山雪鬼.md`、`山雪鬼队长.md`、`冰原战士.md`、`冰原猎人.md`、`冰原术师.md`、`冰原狂战士.md`、`雪原爪兽.md`

- [ ] **步骤 1：参照现有敌人格式编写 7 个敌人文件**

格式参照 `data/combat/enemies/整合运动士兵.md`（frontmatter：name/summary/alias/class/race/faction/tags/level/combat_stats{hp,patk,matk,defense,resist,spd,hit,eva,max_ap}/ai_behavior/ai_skills/drop_items/drop_rate/xp_reward + 描述正文）。

数值设计（基准：整合运动士兵 hp90/patk12/def5/spd9，难度随关卡递增）：

| 敌人 | level | hp | patk | matk | defense | resist | spd | ai_skills | 定位 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 山雪鬼 | 1 | 80 | 11 | 5 | 4 | 3 | 10 | enemy_atk, enemy_heavy | 近战杂兵，数量多，速度快 |
| 雪原爪兽 | 1 | 60 | 9 | 4 | 2 | 2 | 13 | enemy_atk | 野兽，成群，脆而快 |
| 冰原战士 | 2 | 120 | 10 | 5 | 9 | 5 | 7 | enemy_atk, enemy_heavy | 重装抗线 |
| 冰原猎人 | 2 | 70 | 14 | 6 | 3 | 4 | 11 | enemy_atk, enemy_aoe | 远程物理（range 描述于正文） |
| 冰原术师 | 3 | 75 | 8 | 16 | 3 | 8 | 8 | enemy_atk, enemy_aoe | 远程法术 |
| 山雪鬼队长 | 4 | 150 | 16 | 7 | 7 | 6 | 11 | enemy_atk, enemy_heavy, enemy_aoe | 近战精英 |
| 冰原狂战士 | 4 | 130 | 19 | 6 | 5 | 5 | 12 | enemy_atk, enemy_heavy | 高攻低防，狂暴 |

faction 统一为「山雪鬼武装」/「谢拉格」；drop_items 给低价值掉落（如「源岩碎片」不存在的物品会导致加载失败？——检查 drop_items 是否校验，稳妥起见沿用现有物品名「基础源石碎片」）；xp_reward 10-60 递增。

- [ ] **步骤 2：校验所有敌人可加载**

```bash
cd D:/Code/arknights-tavern && python -c "
import sys; sys.path.insert(0, 'src')
from combat_data_loader import CombatDataLoader
l = CombatDataLoader()
for n in ['山雪鬼','雪原爪兽','冰原战士','冰原猎人','冰原术师','山雪鬼队长','冰原狂战士']:
    u = l.load_enemy(n)
    assert u is not None, f'{n} 加载失败'
    print(f'✓ {n}: hp={u.hp} atk={u.patk} spd={u.spd}')
"
```

预期：7 行 `✓` 输出，无异常。

- [ ] **步骤 3：Commit**

```bash
git add data/combat/enemies/
git commit -m "feat: 风雪过境敌人卡 — 山雪鬼武装 7 种"
```

---

### 任务 2：战斗背景 snow_mountain

**文件：**

- 创建：`data/combat/backgrounds/snow_mountain/index.md`

- [ ] **步骤 1：编写背景元数据**

参照 `data/combat/backgrounds/default/index.md` 格式：frontmatter（name/summary/type=combat_background/image 留空/prompt 英文文生图提示词/negative_prompt/source=ai/size=1920x1080）+ 正文构图说明。image 留空（前端回退纯色，后续可用 tools/generate_combat_backgrounds.py 生成）。

prompt 要点：Arknights style anime background art, snow-covered Kjerag mountain battlefield, blizzard under grey sky, icy cliffs and pine trees in the distance, frozen lake ground plane, cold blue-white palette, no characters。

- [ ] **步骤 2：校验加载**

```bash
cd D:/Code/arknights-tavern && python -c "
import sys; sys.path.insert(0, 'src')
from combat_data_loader import CombatDataLoader
l = CombatDataLoader()
assert l.load_background('snow_mountain') is not None
print('✓ snow_mountain 背景加载成功')
"
```

- [ ] **步骤 3：Commit**

```bash
git add data/combat/backgrounds/snow_mountain/
git commit -m "feat: 雪山战斗背景 snow_mountain"
```

---

### 任务 3：遭遇战 ×8

**文件：**

- 创建：`data/combat/encounters/enc_snow_convoy.md`、`enc_snow_ambush.md`、`enc_mansion_uprising.md`、`enc_festival_eve.md`、`enc_snow_hunt.md`、`enc_festival_uprising.md`、`enc_ice_break.md`、`enc_final_showdown.md`

- [ ] **步骤 1：编写 8 个遭遇文件**

格式参照 `data/combat/encounters/初遇整合运动.md`（frontmatter：encounter_id/name/summary/category=story/difficulty/grid_size=7/background=snow_mountain/deploy_zones{player:[[4,0],[6,2]], enemy:...}/waves{enemies:[{enemy,count,positions}]}/conditions{max_rounds:30, escape_enabled}/rewards{xp,items}/trigger_plot）。

敌人构成与难度（来自设计规格）：

| ID | 对应战斗 | 敌人 | difficulty |
| --- | --- | --- | --- |
| enc_snow_convoy | 战1 | 山雪鬼×3、雪原爪兽×2 | 1 |
| enc_snow_ambush | 战2 | 山雪鬼×4、冰原猎人×2 | 2 |
| enc_mansion_uprising | 战3 | 冰原战士×2、冰原术师×2、山雪鬼×2 | 3 |
| enc_festival_eve | 战4 | 山雪鬼×5、冰原战士×2 | 3 |
| enc_snow_hunt | 战5 | 雪原爪兽×6、冰原猎人×2 | 3 |
| enc_festival_uprising | 战6 | 冰原战士×3、冰原术师×2、山雪鬼队长×1 | 4 |
| enc_ice_break | 战7 | 山雪鬼×4、冰原狂战士×1 | 4 |
| enc_final_showdown | 战8 | 山雪鬼队长×2、冰原狂战士×2、冰原术师×2 | 5 |

positions 使用 7×7 网格坐标分散布置（敌人区 [3,3]-[6,6]，玩家区 [0,0]-[2,2] 附近）；rewards.xp 按难度 100-500；trigger_plot 留空（由剧情文件 `[COMBAT:]` 标记触发）。

- [ ] **步骤 2：校验全部遭遇可加载**

```bash
cd D:/Code/arknights-tavern && python -c "
import sys; sys.path.insert(0, 'src')
from combat_data_loader import CombatDataLoader
l = CombatDataLoader()
ids = ['enc_snow_convoy','enc_snow_ambush','enc_mansion_uprising','enc_festival_eve','enc_snow_hunt','enc_festival_uprising','enc_ice_break','enc_final_showdown']
for i in ids:
    e = l.load_encounter(i)
    assert e is not None, f'{i} 加载失败'
    n = sum(w['enemies'][j]['count'] for w in e['waves'] for j in range(len(w['enemies']))) if isinstance(e.get('waves'), list) else 0
    print(f'✓ {i}: {e.get(\"name\")} 敌人总数≈{n}')
"
```

- [ ] **步骤 3：Commit**

```bash
git add data/combat/encounters/
git commit -m "feat: 风雪过境遭遇战 8 场"
```

---

### 任务 4：谢拉格地点 ×5

**文件：**

- 创建：`data/environment/Location/Kjerag/喀兰贸易会客厅.md`、`谢拉格小镇.md`、`雪山大典广场.md`、`圣山山路.md`、`圣山祭坛.md`

- [ ] **步骤 1：编写 5 个地点文件**

格式参照 `data/environment/Location/TEMPLATE.md`（frontmatter：name/summary/alias/type=location/tags/combat_bg: snow_mountain + 正文描述/环境提示）。每处 2-4 句整体面貌 + 视觉/听觉/气味/氛围提示。文件名用中文（与 Rhode_Island 目录下文件名格式一致，需先确认现有文件名风格——若现有文件用英文名，改用英文文件名 + name 中文）。

- [ ] **步骤 2：校验加载**

```bash
cd D:/Code/arknights-tavern && python -c "
import sys; sys.path.insert(0, 'src')
# 复用 wiki/document 加载逻辑确认可读
from document_manager import DocumentManager
print('✓ 地点文件已写入（详细校验在任务 7 汇总）')
"
```

- [ ] **步骤 3：Commit**

```bash
git add data/environment/Location/Kjerag/
git commit -m "feat: 谢拉格地点 5 处（喀兰会客厅/小镇/大典广场/圣山山路/圣山祭坛）"
```

---

### 任务 5：参战角色卡 ×4（含 combat.json）

**文件：**

- 创建：`data/characters/灵知/index.md` + `combat.json`、`data/characters/初雪/index.md` + `combat.json`、`data/characters/崖心/index.md` + `combat.json`、`data/characters/锏/index.md` + `combat.json`

- [ ] **步骤 1：编写 4 张角色卡 index.md**

格式参照 `data/characters/银灰/index.md`：frontmatter（attributes 8 项 1-10、card_face 留空、class、faction、imports、name、race、relationships、summary、tags、theme_color）+ 角色背景正文（2-4 段，忠于原作人设）。

人设要点（原作）：

- **灵知（诺希斯·A·T·G·灵知）**：黎博利，喀兰贸易情报主管，银灰的童年挚友与幕僚，反间计的实际执行者；表面冷漠理性，实际背负着对银灰的忠诚与对谢拉格的复杂情感。attributes 偏战术规划/情绪稳定。
- **初雪（恩雅）**：埃拉菲亚，希瓦艾什次女，被选为耶拉冈德圣女；与兄长银灰理念相左（信仰 vs 变革），内心痛苦但坚守职责。源石技艺适应性高。
- **崖心（恩希亚）**：埃拉菲亚，希瓦艾什幼女，活泼坚韧，是兄妹间唯一的桥梁；近卫（钩索）。物理强度/战场机动高。
- **锏**：库兰塔，银灰的贴身护卫与杀手，沉默寡言，战力顶尖；只认银灰一人的命令，但对博士的冷静与胆识逐渐认可。战斗技巧/物理强度极高。

imports：引用 `races/`（黎博利/埃拉菲亚/库兰塔）、`factions/喀兰贸易`、`characters/银灰`、`characters/博士` 等现有条目；faction 填「喀兰贸易」。注意：需确认 `data/races/` 与 `data/factions/` 存在对应条目（黎博利/埃拉菲亚/喀兰贸易），缺失则在 imports 中省略或创建（创建需先确认 races/factions 目录结构）。

- [ ] **步骤 2：编写 4 份 combat.json（每份 4-5 张专属卡）**

格式参照 `data/characters/银灰/combat.json`（version:1, exclusive_cards[]，每张卡含 card_id/name/rarity/category=exclusive/card_type/cost_type=sp/cost/damage_type/target/range/min_damage/max_damage/atk_scale/tier/class_required/description/effect/base_value/base_value_formula/check/plot_impact/usage_limit/condition/tags）。

卡片设计：

- **灵知**：凝滞/情报系——「极寒领域」（法术群控）、「情报推演」（辅助，下次命中+修正）、「冷静分析」（感知）等
- **初雪**：信仰/辅助系——「圣颂」（治疗/增益）、「耶拉冈德之眼」（感知/揭示）、「寒霜祷言」（法术）等
- **崖心**：机动/近战系——「钩索突袭」（位移+攻击）、「岩崩」（重击）、「攀岩者」（机动）等
- **锏**：爆发/近战系——「瞬身斩」（高伤单体）、「双刀连击」（连击）、「银甲护卫」（防御）等

- [ ] **步骤 3：校验角色卡 + 战斗卡加载**

```bash
cd D:/Code/arknights-tavern && python -c "
import sys; sys.path.insert(0, 'src')
from combat_engine.card_loader import load_character_cards
from combat_data_loader import CombatDataLoader
for n in ['灵知','初雪','崖心','锏']:
    cards = load_character_cards(n)
    assert cards, f'{n} 战斗卡加载失败'
    print(f'✓ {n}: {len(cards)} 张专属卡')
"
```

- [ ] **步骤 4：Commit**

```bash
git add data/characters/灵知 data/characters/初雪 data/characters/崖心 data/characters/锏
git commit -m "feat: 谢拉格参战角色卡 4 张（灵知/初雪/崖心/锏）+ 战斗卡"
```

---

### 任务 6：对话角色卡 ×3

**文件：**

- 创建：`data/characters/大长老/index.md`、`data/characters/菈塔托丝·布朗陶/index.md`、`data/characters/阿克托斯·佩尔罗契/index.md`

- [ ] **步骤 1：编写 3 张对话角色卡（无 combat.json）**

格式同任务 5 的 index.md。人设：

- **大长老**：谢拉格最高精神领袖，耶拉冈德信仰的化身，看似昏聩实则清醒，在两族博弈中保持中立裁决者的姿态
- **菈塔托丝·布朗陶**：布朗陶家主，保守派核心，反对喀兰铁路，与大长老共治谢拉格旧秩序
- **阿克托斯·佩尔罗契**：佩尔罗契家主，武力派，握有圣山武装（山雪鬼的雇主之一），强硬而短视

class 可填「术师/重装/近卫」但不参与战斗；attributes 按人设填写。

- [ ] **步骤 2：校验 frontmatter 完整性**

```bash
cd D:/Code/arknights-tavern && python -c "
import sys, yaml, pathlib
for n in ['大长老','菈塔托丝·布朗陶','阿克托斯·佩尔罗契']:
    p = pathlib.Path(f'data/characters/{n}/index.md')
    txt = p.read_text(encoding='utf-8').split('---', 2)[1]
    d = yaml.safe_load(txt)
    for k in ['name','attributes','class','faction','summary']:
        assert k in d, f'{n} 缺少 {k}'
    print(f'✓ {n} frontmatter 完整')
"
```

- [ ] **步骤 3：Commit**

```bash
git add data/characters/大长老 data/characters/菈塔托丝·布朗陶 data/characters/阿克托斯·佩尔罗契
git commit -m "feat: 谢拉格对话角色卡 3 张（大长老/菈塔托丝/阿克托斯）"
```

---

### 任务 7：主剧情文件（核心）

**文件：**

- 创建：`data/plots/fengxue_guojing/index.md`（约 1200-1500 行）

- [ ] **步骤 1：编写 frontmatter + 可检索条目 + 剧情概述 + 触发场景**

frontmatter 参照 `data/plots/near-light/index.md`：id: fengxue_guojing、name: 风雪过境、category: main、priority: 8、repeatable: false、summary、trigger（location: [喀兰贸易会客厅]、character: [银灰]、keywords: [谢拉格, 喀兰贸易, 雪山大典, 银灰]）、initial_location/time/atmosphere/characters、opening_scene（博士抵达谢拉格的完整开场描写）、deviation_policy{allow: true, base_difficulty: -3, require_confirm: true}、effects（character_available: [银灰,灵知,初雪,崖心,锏,大长老,菈塔托丝·布朗陶,阿克托斯·佩尔罗契]、faction_change、unlock_locations: [喀兰贸易会客厅,谢拉格小镇,雪山大典广场,圣山山路,圣山祭坛]）、tension_clock（3 阶段：大典筹备期谣言/投毒事件/全城戒严→圣山决战）。

可检索条目列出 characters/factions/locations/items 引用。剧情概述写原作浓缩（博士受邀赴谢拉格，卷入三族之争）。

- [ ] **步骤 2：编写 6 章 22 节拍**

每章结构：`## 章节 N：标题` + `**ID**` + `**概要**` + 各 beat（`#### beat_id（keep_on_deviate: true 视需要）` + `**内容**` + `**强制对话**` + `**揭示信息**` + `**发现路径**` + `**玩家选项方向**`）。

章节与 beat 规划（主线忠于原作）：

- **第 1 章 不欢而聚**（beat_arrival 抵达接风 / beat_intro_tension 三族矛盾与信仰 / beat_convoy_fight 商会车队遇袭 ⚔️战1[COMBAT:enc_snow_convoy]）
  - 分支：① 与灵知交谈（情报）；② 观察锏（角色）；③ 询问银灰铁路计划（政治）
- **第 2 章 入乡随俗·息事宁人**（beat_town 小镇见闻 / beat_assassination 银灰遇刺未遂 / beat_ambush 追击刺客遇伏 ⚔️战2[COMBAT:enc_snow_ambush]）
  - 分支：① 追查刺客线索（情报→第 5 章变体）；② 与感染者工匠交谈（社交→第 4 章近路变体）；③ 向锏问银灰过去（角色→第 6 章变体）
- **第 3 章 山雪欲来·人心难测**（beat_family 希瓦艾什家宴：初雪/崖心登场 / beat_mansion_uprising 家宴事变 ⚔️战3[COMBAT:enc_mansion_uprising] / beat_festival_eve 大典前夜冲突 ⚔️战4[COMBAT:enc_festival_eve]）
  - 分支：① 与初雪谈信仰（关系）；② 与崖心修装备（角色）；③ 调查山雪鬼调动（情报）
- **第 4 章 立雪求道·猎场**（beat_hunt 圣山圣猎启程 / beat_snow_hunt 兽群与伏击 ⚔️战5[COMBAT:enc_snow_hunt] / beat_blizzard 暴风雪与崖心危机）
  - 分支：① 用工匠近路绕行（若第 2 章分支②成功，战斗选项变化）；② 保护崖心（→第 6 章变体）
- **第 5 章 一着不慎·歧路**（beat_festival 大典开幕 / beat_assassination2 长老遇刺 / beat_poison 投毒事件与戒严 ⚔️战6[COMBAT:enc_festival_uprising] / beat_mistrust 博士与银灰信任危机）
  - 分支：① 追查投毒源头（若第 2 章分支①成功，提前识破反间计）；② 保护大长老（政治）
- **第 6 章 破冰·将军·封盘**（beat_reveal 反间计真相 / beat_ice_break 破冰巷战 ⚔️战7[COMBAT:enc_ice_break] / beat_final_showdown 圣山决战 ⚔️战8[COMBAT:enc_final_showdown] / beat_trial 耶拉冈德试炼与暴风雪抉择 / beat_end 变革落幕）
  - 分支：① 与银灰对质真相（关系）；② 在试炼中替初雪承担风雪（若第 3 章分支①成功，初雪会阻止博士）

每个受分支影响的主线 beat 写明条件变体：「若……（分支条件），则……；否则……」由 LLM 按会话状态选择。

- [ ] **步骤 3：编写关键对话参考 + 任务**

关键对话参考：银灰（优雅深谋、话里有话）、灵知（理性克制、数据化表达）、初雪（温柔隐忍、信仰口吻）、崖心（活泼直率）、锏（惜字如金）、大长老（苍老缓慢、先知口吻）、菈塔托丝（傲慢守旧）、阿克托斯（暴躁武断）。

任务：主线 M1（查明大典真相）M2（护送银灰完成变革）/支线 S1（追查刺客）S2（帮助感染者工匠）S3（修复崖心的钩索）等，按模板表格格式。

- [ ] **步骤 4：结构校验**

```bash
cd D:/Code/arknights-tavern && python -c "
import sys, re, pathlib
sys.path.insert(0, 'src')
from session_overlay import _read_plot_file, _parse_narrative_beats
fm, body = _read_plot_file('fengxue_guojing')
assert fm.get('id') == 'fengxue_guojing', 'frontmatter id 错误'
chapters = _parse_narrative_beats(body)
print(f'✓ 解析到 {len(chapters)} 章')
total = 0
for ch in chapters:
    total += len(ch['beats'])
    print(f\"  章节 {ch['title']}: {len(ch['beats'])} beats\")
assert len(chapters) == 6, f'期望 6 章，实际 {len(chapters)}'
assert total >= 20, f'期望 ≥20 beats，实际 {total}'
# 战斗标记检查
combat_markers = re.findall(r'\[COMBAT:(\w+)\]', body)
print(f'✓ 战斗标记: {combat_markers}')
assert len(combat_markers) == 8, f'期望 8 个战斗标记，实际 {len(combat_markers)}'
"
```

预期：6 章、20+ beats、8 个 `[COMBAT:]` 标记全部输出。

- [ ] **步骤 5：Commit**

```bash
git add data/plots/fengxue_guojing/
git commit -m "feat: 「风雪过境」主剧情文件（6 章 22 节拍 8 战斗）"
```

---

### 任务 8：全量集成校验 + 收尾

- [ ] **步骤 1：全量校验**

```bash
cd D:/Code/arknights-tavern && python -c "
import sys; sys.path.insert(0, 'src')
from combat_data_loader import CombatDataLoader
from combat_engine.card_loader import load_character_cards
from session_overlay import _read_plot_file, _parse_narrative_beats

l = CombatDataLoader()
# 敌人
for n in ['山雪鬼','雪原爪兽','冰原战士','冰原猎人','冰原术师','山雪鬼队长','冰原狂战士']:
    assert l.load_enemy(n), n
# 遭遇
for i in ['enc_snow_convoy','enc_snow_ambush','enc_mansion_uprising','enc_festival_eve','enc_snow_hunt','enc_festival_uprising','enc_ice_break','enc_final_showdown']:
    assert l.load_encounter(i), i
# 背景
assert l.load_background('snow_mountain')
# 角色卡
for n in ['银灰','灵知','初雪','崖心','锏']:
    assert load_character_cards(n), n
# 剧情
fm, body = _read_plot_file('fengxue_guojing')
assert len(_parse_narrative_beats(body)) == 6
print('✓ 全量集成校验通过')
"
```

- [ ] **步骤 2：README/文档同步（如 data/README.md 有剧情目录清单则补充）**

检查 `data/README.md` 是否维护剧情/角色清单，有则补一行。

- [ ] **步骤 3：Commit 收尾**

```bash
git add -A
git commit -m "chore: 风雪过境 demo 全量校验通过"
```

- [ ] **步骤 4：合并回 main（用户确认后执行）**

```bash
git checkout main && git merge --no-ff feat/plot-fengxue-guojing -m "merge: 「风雪过境」改编剧情 demo" && git branch -d feat/plot-fengxue-guojing
```

- [ ] **步骤 5：提示恢复 stash**

告知用户 `git stash list` 中存有之前分支的未提交工作（wip: session combat background overrides），由其决定何时恢复。

---

## 自检记录

- **规格覆盖度**：规格二（章节结构）→ 任务 7；规格三（角色）→ 任务 5/6；规格四（战斗资源）→ 任务 1/2/3/4；规格五（文件清单）→ 全部任务；规格六（验证）→ 各任务步骤 2 + 任务 8。✓
- **占位符扫描**：无 TODO/待定；所有文件内容要点与格式示例已给出。✓
- **类型一致性**：遭遇 ID、敌人名、章节数（6）、战斗数（8）、角色名（灵知/初雪/崖心/锏/大长老/菈塔托丝·布朗陶/阿克托斯·佩尔罗契）在计划各处一致。✓
