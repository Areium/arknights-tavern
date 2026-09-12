# 战术卡 CV 审计报告（balance_version 1）

- 卡牌总数：72
- 落在预算 ±20%：63
- 有明确例外说明：9
- 仍偏离预算且无说明：0

| 卡 | 职业 | AP | 阶 | 调整前 | 调整后 | CV | 预算 | 偏差 | 状态 | 例外 |
|---|---|---:|---|---|---|---:|---:|---:|---|---|
| defender_breach | 重装 | 2 | elite | 0–0 / 0.0 | 0–0 / 0.0 | 7.65 | 48.0 | -84% | under | effect_only（纯效果卡无法用数值缩放调整，建议按方案 §5.2 增加机制补足剩余预算——P2 内容） |
| defender_wall | 重装 | 2 | basic | 0–0 / 0.0 | 0–0 / 0.0 | 21.6 | 48.0 | -55% | under | effect_only（纯效果卡无法用数值缩放调整，建议按方案 §5.2 增加机制补足剩余预算——P2 内容） |
| cmd_scan | 战术指挥 | 1 | basic | 2–5 / 0.2 | 2–5 / 0.2 | 33.29 | 24.0 | +39% | over | effect_dominated（价值主要来自状态效果，数值缩放无效；方案 §3.4 的 SELF 目标系数低估自保型技能，建议 P2 以机制补足而非堆数值） |
| medic_sanctuary | 医疗 | 3 | elite | 8–14 / 0.7 | 8–14 / 0.7 | 48.21 | 72.0 | -33% | under | support_discount（纯治疗卡按稳定性溢价允许低于预算 ≤35%） |
| medic_miracle | 医疗 | 2 | elite | 12–22 / 1.0 | 12–22 / 1.0 | 32.58 | 48.0 | -32% | under | support_discount（纯治疗卡按稳定性溢价允许低于预算 ≤35%） |
| supp_overload | 辅助 | 2 | elite | 0–0 / 0.0 | 0–0 / 0.0 | 33.66 | 48.0 | -30% | under | effect_only（纯效果卡无法用数值缩放调整，建议按方案 §5.2 增加机制补足剩余预算——P2 内容） |
| cmd_banner | 战术指挥 | 2 | elite | 6–12 / 0.5 | 6–12 / 0.5 | 36.41 | 48.0 | -24% | under | support_discount（纯治疗卡按稳定性溢价允许低于预算 ≤35%） |
| medic_heal | 医疗 | 1 | basic | 6–12 / 0.5 | 6–12 / 0.5 | 18.74 | 24.0 | -22% | under | support_discount（方案 §5.2 明确保留治疗术数值） |
| medic_group | 医疗 | 2 | basic | 4–8 / 0.3 | 9–18 / 0.66 | 37.97 | 48.0 | -21% | under | support_discount（纯治疗卡按稳定性溢价允许低于预算 ≤35%） |
| spec_backstab | 特种 | 1 | basic | 5–9 / 0.5 | 11–19 / 1.05 | 28.73 | 24.0 | +20% | over | - |
| medic_cleanse | 医疗 | 1 | basic | 3–7 / 0.3 | 3–7 / 0.3 | 19.29 | 24.0 | -20% | under | - |
| caster_shock | 术师 | 2 | basic | 7–12 / 0.6 | 15–26 / 1.32 | 38.79 | 48.0 | -19% | under | - |
| guard_iaido | 近卫 | 3 | elite | 8–12 / 0.8 | 18–26 / 1.5 | 58.34 | 72.0 | -19% | under | - |
| medic_arts_atk | 医疗 | 2 | elite | 8–14 / 0.8 | 18–31 / 1.5 | 38.91 | 48.0 | -19% | under | - |
| defender_taunt | 重装 | 1 | basic | 1–4 / 0.2 | 1–6 / 0.29 | 19.53 | 24.0 | -19% | under | - |
| supp_disrupt | 辅助 | 1 | basic | 4–7 / 0.4 | 4–7 / 0.4 | 28.43 | 24.0 | +18% | over | - |
| sniper_aim | 狙击 | 1 | basic | 5–9 / 0.5 | 10–18 / 1.01 | 28.37 | 24.0 | +18% | over | - |
| defender_fortress | 重装 | 1 | elite | 15–25 / 0.8 | 15–25 / 0.8 | 28.32 | 24.0 | +18% | over | - |
| supp_debuff | 辅助 | 1 | basic | 1–4 / 0.2 | 1–5 / 0.25 | 19.84 | 24.0 | -17% | under | - |
| supp_zone | 辅助 | 2 | basic | 3–6 / 0.3 | 3–6 / 0.3 | 39.8 | 48.0 | -17% | under | - |
| sniper_lethal | 狙击 | 3 | elite | 12–22 / 1.5 | 36–65 / 1.5 | 60.21 | 72.0 | -16% | under | - |
| caster_storm | 术师 | 2 | basic | 5–10 / 0.5 | 11–22 / 1.1 | 55.79 | 48.0 | +16% | over | - |
| defender_quake_elite | 重装 | 3 | elite | 6–12 / 0.7 | 13–26 / 1.5 | 60.59 | 72.0 | -16% | under | - |
| supp_control | 辅助 | 3 | elite | 8–12 / 0.7 | 18–26 / 1.5 | 61.26 | 72.0 | -15% | under | - |
| guard_true_silver | 近卫 | 3 | elite | 12–20 / 1.2 | 14–20 / 1.25 | 61.34 | 72.0 | -15% | under | - |
| spec_evade | 特种 | 1 | basic | 2–5 / 0.3 | 3–6 / 0.39 | 20.46 | 24.0 | -15% | in_band | - |
| vang_dash | 先锋 | 1 | basic | 3–6 / 0.3 | 7–13 / 0.66 | 27.5 | 24.0 | +15% | over | - |
| guard_will | 近卫 | 1 | elite | 10–18 / 0.6 | 10–18 / 0.6 | 20.52 | 24.0 | -14% | in_band | - |
| vang_blitz | 先锋 | 2 | elite | 8–12 / 0.8 | 23–33 / 1.5 | 41.41 | 48.0 | -14% | under | - |
| supp_nullify | 辅助 | 3 | elite | 6–10 / 0.6 | 8–13 / 0.81 | 62.58 | 72.0 | -13% | under | - |
| vang_decimate | 先锋 | 3 | elite | 6–10 / 0.7 | 25–42 / 1.5 | 62.61 | 72.0 | -13% | under | - |
| spec_execute | 特种 | 2 | elite | 10–18 / 1.0 | 21–37 / 1.5 | 42.13 | 48.0 | -12% | in_band | - |
| defender_shield | 重装 | 1 | basic | 3–6 / 0.4 | 7–13 / 0.88 | 21.1 | 24.0 | -12% | in_band | - |
| medic_regen | 医疗 | 2 | basic | 3–6 / 0.2 | 15–29 / 0.97 | 42.34 | 48.0 | -12% | in_band | - |
| supp_slow | 辅助 | 1 | basic | 2–5 / 0.2 | 4–9 / 0.35 | 21.34 | 24.0 | -11% | in_band | - |
| spec_ambush | 特种 | 3 | elite | 8–14 / 0.9 | 44–76 / 1.5 | 64.26 | 72.0 | -11% | in_band | - |
| caster_missile | 术师 | 2 | elite | 10–18 / 1.0 | 20–35 / 1.5 | 43.01 | 48.0 | -10% | in_band | - |
| medic_shield | 医疗 | 1 | basic | 5–10 / 0.4 | 5–10 / 0.4 | 21.56 | 24.0 | -10% | in_band | - |
| guard_cleave | 近卫 | 2 | basic | 3–6 / 0.3 | 12–21 / 1.09 | 52.79 | 48.0 | +10% | over | - |
| defender_quake | 重装 | 2 | basic | 3–6 / 0.3 | 12–21 / 1.09 | 52.79 | 48.0 | +10% | over | - |
| guard_pierce | 近卫 | 1 | basic | 6–10 / 0.6 | 10–14 / 0.7 | 21.67 | 24.0 | -10% | in_band | - |
| spec_smoke | 特种 | 2 | elite | 5–9 / 0.5 | 6–11 / 0.62 | 43.54 | 48.0 | -9% | in_band | - |
| guard_slash | 近卫 | 1 | basic | 5–9 / 0.5 | 12–16 / 0.75 | 21.84 | 24.0 | -9% | in_band | - |
| sniper_explosive | 狙击 | 2 | elite | 8–12 / 0.8 | 15–22 / 1.49 | 52.34 | 48.0 | +9% | over | - |
| sniper_ap_round | 狙击 | 2 | basic | 4–7 / 0.4 | 9–15 / 0.88 | 43.73 | 48.0 | -9% | in_band | - |
| cmd_trap | 战术指挥 | 3 | elite | 10–16 / 0.9 | 45–71 / 1.5 | 65.82 | 72.0 | -9% | in_band | - |
| vang_quick | 先锋 | 1 | basic | 5–8 / 0.5 | 9–14 / 0.86 | 21.96 | 24.0 | -8% | in_band | - |
| vang_recon | 先锋 | 1 | basic | 2–4 / 0.2 | 2–4 / 0.2 | 26.01 | 24.0 | +8% | over | - |
| supp_bind | 辅助 | 1 | basic | 3–6 / 0.3 | 3–6 / 0.3 | 22.11 | 24.0 | -8% | in_band | - |
| cmd_orbital | 战术指挥 | 3 | elite | 8–14 / 0.8 | 18–31 / 1.5 | 66.71 | 72.0 | -7% | in_band | - |
| sniper_rain | 狙击 | 2 | basic | 3–6 / 0.3 | 10–19 / 0.99 | 51.1 | 48.0 | +6% | in_band | - |
| defender_bash | 重装 | 2 | basic | 5–9 / 0.5 | 17–31 / 1.5 | 45.36 | 48.0 | -6% | in_band | - |
| vang_stab | 先锋 | 1 | basic | 4–7 / 0.4 | 9–15 / 0.88 | 22.78 | 24.0 | -5% | in_band | - |
| vang_flurry | 先锋 | 1 | basic | 3–5 / 0.3 | 10–16 / 0.96 | 25.23 | 24.0 | +5% | in_band | - |
| spec_shadow | 特种 | 1 | basic | 3–5 / 0.3 | 10–16 / 0.96 | 25.23 | 24.0 | +5% | in_band | - |
| cmd_strike | 战术指挥 | 1 | basic | 4–8 / 0.4 | 9–18 / 0.88 | 25.19 | 24.0 | +5% | in_band | - |
| guard_heavy | 近卫 | 2 | basic | 8–14 / 0.8 | 18–31 / 1.5 | 45.78 | 48.0 | -5% | in_band | - |
| spec_shift | 特种 | 1 | basic | 3–6 / 0.3 | 10–18 / 0.91 | 25.07 | 24.0 | +4% | in_band | - |
| cmd_shell | 战术指挥 | 2 | basic | 3–7 / 0.4 | 10–21 / 1.24 | 50.1 | 48.0 | +4% | in_band | - |
| caster_nova | 术师 | 2 | basic | 4–7 / 0.4 | 13–21 / 1.25 | 49.94 | 48.0 | +4% | in_band | - |
| caster_burn | 术师 | 3 | basic | 3–6 / 0.3 | 10–19 / 0.95 | 74.91 | 72.0 | +4% | in_band | - |
| guard_wide | 近卫 | 2 | basic | 4–7 / 0.4 | 13–22 / 1.31 | 49.81 | 48.0 | +4% | in_band | - |
| sniper_extreme | 狙击 | 3 | elite | 10–15 / 1.0 | 16–23 / 1.5 | 74.05 | 72.0 | +3% | in_band | - |
| caster_void | 术师 | 3 | elite | 8–14 / 0.8 | 18–31 / 1.5 | 70.04 | 72.0 | -3% | in_band | - |
| cmd_rally | 战术指挥 | 1 | basic | 4–8 / 0.3 | 8–16 / 0.59 | 23.35 | 24.0 | -3% | in_band | - |
| sniper_rapid | 狙击 | 1 | basic | 3–6 / 0.3 | 9–17 / 0.87 | 24.53 | 24.0 | +2% | in_band | - |
| cmd_order | 战术指挥 | 1 | basic | 3–6 / 0.3 | 9–17 / 0.87 | 24.53 | 24.0 | +2% | in_band | - |
| vang_formation | 先锋 | 2 | elite | 5–10 / 0.4 | 8–16 / 0.63 | 47.03 | 48.0 | -2% | in_band | - |
| sniper_weakpoint | 狙击 | 2 | basic | 8–13 / 0.7 | 18–29 / 1.5 | 47.08 | 48.0 | -2% | in_band | - |
| caster_inferno | 术师 | 3 | elite | 6–10 / 0.7 | 13–22 / 1.5 | 71.06 | 72.0 | -1% | in_band | - |
| caster_bolt | 术师 | 1 | basic | 4–8 / 0.4 | 9–18 / 0.88 | 24.04 | 24.0 | +0% | in_band | - |
| spec_trap | 特种 | 1 | basic | 4–8 / 0.4 | 9–18 / 0.88 | 24.04 | 24.0 | +0% | in_band | - |
