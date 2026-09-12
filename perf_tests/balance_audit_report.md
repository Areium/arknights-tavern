# 战斗数值审计报告（威胁模型 v1）

- 敌人条目：19（其中按 attributes 派生数值：8）
- 战斗节点：16
- XP 单调性问题：0

## 敌人分层

| 敌人 | role | 自动分类 | 阶段带 | 威胁点 | 行动槽 | XP | 偏差 |
|---|---|---|---|---:|---:|---:|---|
| 乌萨斯盾卫 | strong | strong | T0 | 2.2 | 1 | 0 | - |
| 冰原战士 | standard | standard | T1 | 1.6 | 1 | 16 | - |
| 冰原术师 | minion | minion | T1 | 1.0 | 1 | 10 | - |
| 冰原狂战士 | strong | strong | T2 | 2.2 | 1 | 22 | - |
| 冰原猎人 | standard | standard | T1 | 1.6 | 1 | 16 | - |
| 山雪鬼 | standard | standard | T0 | 1.6 | 1 | 16 | - |
| 山雪鬼队长 | elite | elite | T3 | 3.2 | 2 | 38 | - |
| 整合运动士兵 | standard | standard | T0 | 1.6 | 1 | 16 | - |
| 整合运动术师 | minion | minion | T1 | 1.0 | 1 | 10 | - |
| 整合运动狙击手 | minion | minion | T1 | 1.0 | 1 | 10 | - |
| 整合运动盾卫 | strong | strong | T1 | 2.2 | 1 | 22 | - |
| 整合运动突袭者 | standard | standard | T0 | 1.6 | 1 | 0 | - |
| 整合运动队长 | strong | strong | T0 | 2.2 | 1 | 0 | - |
| 无胄盟清洗小队 | standard | standard | T0 | 1.6 | 1 | 0 | - |
| 武装佣兵 | standard | standard | T0 | 1.6 | 1 | 0 | - |
| 源石虫 | minion | minion | T0 | 1.0 | 1 | 0 | - |
| 灰狐 | standard | standard | T0 | 1.6 | 1 | 0 | - |
| 锈铜骑士 | standard | standard | T0 | 1.6 | 1 | 0 | - |
| 雪原爪兽 | minion | minion | T0 | 1.0 | 1 | 10 | - |

## 节点威胁预算

| 节点 | 单位 | 威胁 | 声明预算 | 预算偏差 | 阶段带 | 推荐 | 备注 |
|---|---:|---:|---:|---:|---|---|---|
| enc_defense | 4 | 5.8 | 5.8 | 0% | T2 | T1 | - |
| enc_elite_hunt | 8 | 11.0 | 7.0 | 57% | T3 | T3 | 实际威胁 11.0 超出声明预算 7（偏差 57% > 容差 25%） |
| enc_festival_eve | 4 | 6.4 | 6.4 | 0% | T1 | T2 | - |
| enc_festival_uprising | 6 | 10.0 | 10.0 | 0% | T2 | T2 | - |
| enc_final_showdown | 6 | 12.8 | 12.8 | 0% | T3 | T3 | - |
| enc_first_reunion | 4 | 5.2 | 5.2 | 0% | T1 | T1 | - |
| enc_ice_break | 3 | 5.4 | 5.4 | 0% | T2 | T1 | - |
| enc_mansion_uprising | 4 | 5.8 | 5.8 | 0% | T1 | T1 | - |
| enc_mixed_assault | 4 | 5.2 | 5.2 | 0% | T1 | T1 | - |
| enc_quick_test_1 | 1 | 1.6 | 1.6 | 0% | T0 | T0 | - |
| enc_quick_test_2 | 2 | 3.2 | 3.2 | 0% | T0 | T1 | - |
| enc_quick_test_3 | 2 | 2.6 | 2.6 | 0% | T1 | T0 | - |
| enc_snow_ambush | 4 | 6.4 | 6.4 | 0% | T1 | T2 | - |
| enc_snow_convoy | 2 | 2.6 | 2.6 | 0% | T0 | T0 | - |
| enc_snow_hunt | 5 | 6.2 | 6.2 | 0% | T1 | T2 | - |
| enc_training | 2 | 3.2 | 3.2 | 0% | T0 | T1 | - |
