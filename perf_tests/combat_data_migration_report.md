# 战斗数据迁移报告（批次 1）

- 遭遇 → 节点 JSON：16 个（`data/combat/nodes/`）
- 其中已定位到剧情节拍绑定：8 个
- 敌人条目合并到 `data/enemies/`：19 个
- 未绑定节拍的节点：['enc_defense', 'enc_elite_hunt', 'enc_mixed_assault', 'enc_quick_test_1', 'enc_quick_test_2', 'enc_quick_test_3', 'enc_training', 'enc_first_reunion']

## 备注

- （无）

## 冲突（需人工确认，已按叙事侧取值）

- 整合运动士兵: race 两库不一致（叙事='卡特斯' / 战斗='未知'，取叙事）
- 整合运动士兵: summary 两库不一致（叙事='整合运动士兵是感染者组成的近战炮灰，装备简陋，依靠人海战术和绝望冲锋作战。' / 战斗='整合运动基础步兵，数量多且悍不畏死，需优先处理术师。'，取叙事）
- 整合运动术师: race 两库不一致（叙事='卡特斯' / 战斗='未知'，取叙事）
- 整合运动术师: summary 两库不一致（叙事='整合运动术师是远程法术输出单位，拥有源石能量弹等能力，依赖源石结晶作战。' / 战斗='整合运动术师是远程法术敌人，优先攻击高防单位，血低后撤，建议快速近战解决。'，取叙事）
- 乌萨斯盾卫: 仅叙事条目（无 combat_stats），引擎将按 attributes 派生战斗数值
- 整合运动突袭者: 仅叙事条目（无 combat_stats），引擎将按 attributes 派生战斗数值
- 整合运动队长: 仅叙事条目（无 combat_stats），引擎将按 attributes 派生战斗数值
- 无胄盟清洗小队: 仅叙事条目（无 combat_stats），引擎将按 attributes 派生战斗数值
- 武装佣兵: 仅叙事条目（无 combat_stats），引擎将按 attributes 派生战斗数值
- 源石虫: 仅叙事条目（无 combat_stats），引擎将按 attributes 派生战斗数值
- 灰狐: 仅叙事条目（无 combat_stats），引擎将按 attributes 派生战斗数值
- 锈铜骑士: 仅叙事条目（无 combat_stats），引擎将按 attributes 派生战斗数值
