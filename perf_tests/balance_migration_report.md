# 敌人分层与遭遇预算迁移报告（balance_version 1）

## 敌人

| 敌人 | 角色 | 阶段 | 行动槽 | 威胁点 | 相对生命 | 相对输出 | XP |
|---|---|---|---:|---:|---:|---:|---:|
| 山雪鬼队长 | elite | T3 | 2 | 3.2 | 1.5 | 1.18 | 38 |
| 冰原狂战士 | strong | T2 | 1 | 2.2 | 1.3 | 1.32 | 22 |
| 整合运动盾卫 | strong | T1 | 1 | 2.2 | 1.4 | 0.72 | 22 |
| 冰原战士 | standard | T1 | 1 | 1.6 | 1.2 | 0.88 | 16 |
| 冰原猎人 | standard | T1 | 1 | 1.6 | 0.7 | 1.07 | 16 |
| 山雪鬼 | standard | T0 | 1 | 1.6 | 0.8 | 0.93 | 16 |
| 整合运动士兵 | standard | T0 | 1 | 1.6 | 0.9 | 0.97 | 16 |
| 冰原术师 | minion | T1 | 1 | 1.0 | 0.75 | 0.78 | 10 |
| 整合运动术师 | minion | T1 | 1 | 1.0 | 0.7 | 0.68 | 10 |
| 整合运动狙击手 | minion | T1 | 1 | 1.0 | 0.75 | 0.88 | 10 |
| 雪原爪兽 | minion | T0 | 1 | 1.0 | 0.6 | 0.82 | 10 |

## 遭遇

| 遭遇 | 类型 | 阶段 | 单位 | 威胁预算 | 旧 XP | 新基础 XP | 最终 XP | 奖励带 | 回合目标 | max_rounds |
|---|---|---|---:|---:|---:|---:|---:|---|---:|---:|
| enc_defense | normal | T2 | 7 | 10.6 | 400 | 45 | 82 | 70–95 | 5 | 8 |
| enc_elite_hunt | elite | T3 | 10 | 14.8 | 500 | 141 | 193 | 165–220 | 6 | 10 |
| enc_festival_eve | normal | T1 | 7 | 11.2 | 200 | 21 | 60 | 50–70 | 5 | 8 |
| enc_festival_uprising | normal | T2 | 6 | 10.0 | 300 | 45 | 82 | 70–95 | 5 | 8 |
| enc_final_showdown | boss | T3 | 6 | 12.8 | 500 | 301 | 350 | 300–400 | 8 | 12 |
| enc_ice_break | normal | T2 | 5 | 8.6 | 300 | 52 | 82 | 70–95 | 5 | 8 |
| enc_mansion_uprising | normal | T1 | 6 | 8.4 | 200 | 31 | 60 | 50–70 | 5 | 8 |
| enc_mixed_assault | normal | T1 | 6 | 7.8 | 300 | 33 | 60 | 50–70 | 5 | 8 |
| enc_quick_test_1 | teaching | T0 | 1 | 1.6 | 50 | 20 | 26 | 21–30 | 3 | 6 |
| enc_quick_test_2 | teaching | T0 | 2 | 3.2 | 80 | 14 | 25 | 21–30 | 3 | 6 |
| enc_quick_test_3 | teaching | T1 | 2 | 2.6 | 120 | 27 | 36 | 30–42 | 3 | 6 |
| enc_snow_ambush | normal | T1 | 6 | 9.6 | 150 | 26 | 60 | 50–70 | 5 | 8 |
| enc_snow_convoy | teaching | T0 | 5 | 6.8 | 100 | 2 | 26 | 21–30 | 3 | 6 |
| enc_snow_hunt | elite | T1 | 8 | 9.2 | 200 | 73 | 105 | 90–120 | 6 | 10 |
| enc_training | teaching | T0 | 2 | 3.2 | 100 | 14 | 25 | 21–30 | 3 | 6 |
| enc_first_reunion | normal | T1 | 4 | 5.2 | 200 | 42 | 60 | 50–70 | 5 | 8 |
