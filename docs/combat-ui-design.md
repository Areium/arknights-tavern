# 战斗 UI 美化方案

> 基于明日方舟美术风格的俯视视角战斗界面设计
> 当前版本：v2.0 · 2026-05-23

---

## 目录

1. [概述：从正投影到俯视视角](#概述)
2. [网格/地图系统](#一网格地图系统)
3. [战斗小人系统](#二战斗小人系统)
4. [卡牌展示系统](#三卡牌展示系统)
5. [单位状态面板](#四单位状态面板)
6. [战斗事件与特效](#五战斗事件与特效)
7. [整体布局与配色](#六整体布局与配色)
8. [动画系统](#七动画系统)
9. [资源管线](#八资源管线)
10. [分阶段实施路线](#九分阶段实施路线)
11. [卡牌拖动交互](#十卡牌拖动交互)
12. [单位悬浮提示框](#十一单位悬浮提示框)
13. [战斗回写与会话覆盖](#十二战斗回写与会话覆盖)
14. [附录 A：技术栈](#附录-a技术栈推荐)
15. [附录 B：CSS 变量](#附录-b样式变量定义css-custom-properties)
16. [附录 C：实施记录](#附录-c实施记录)

---

## 概述

### 当前状态（v2.0 已实施）

- **地图**：CSS 3D 俯视棋盘，9×8 方格，rotateX(6deg) 透视，单元格 56×56px，带有 glow 高亮系统
- **单位**：CSS 像素小人（ChibiSprite），职业色 + 武器形状，悬浮 HP 条，部署方向箭头，受击震动动画
- **卡牌**：140×190px 完整卡面，程序化卡图（CSS 渐变），职业色带（左侧 4px），稀有度金边，选中浮起 + 脉冲光效
- **状态面板**：角色卡片式面板，头像占位 + HP 条（三级渐变色）+ AP 点阵 + 职业标签
- **事件日志**：Timeline 风格，Unicode 图标 + 彩色事件类型
- **特效**：Canvas 粒子系统（spark/heal/death/victory），浮空伤害数字（Orbitron 字体 + 类型色 + 描边）
- **配色**：深蓝黑底（#0a0e17）+ 金色高亮（#f0c060）+ 青色玩家 / 红色敌方
- **交互**：卡牌拖拽到目标、数字键快捷选牌、F 结束回合、Esc 取消、单位点击选中
- **新功能**：CombatUnitTooltip（悬浮属性 + 战斗数值详情）、战斗回写到会话

### 核心参考：《明日方舟》俯视视角

1. **轻微俯视透视**（foreshortened top-down）- 远处格子略小，形成深度感
2. **地面格子有透视**——CSS rotateX 绕 X 轴旋转
3. **角色小人**——CSS 像素风占位，预留 Spine 动画接口
4. **格子高亮**——发光边框而非纯色填充
5. **技能特效**——Canvas 粒子叠加层
6. **伤害数字**——弹出动画，粗体描边

---

## 一、网格/地图系统

### 1.1 透视方案：CSS 3D 俯视

```css
.combat-grid-perspective {
  perspective: 2000px;
  perspective-origin: 50% 45%;
}
.combat-grid-3d {
  transform: rotateX(6deg);
  transform-style: preserve-3d;
}
```

**效果**：轻微的深度感，保持整体高度紧凑，不占用过多纵向空间。

### 1.2 格子视觉设计（56×56px）

```css
.combat-cell {
  width: 56px;
  height: 56px;
  background: rgba(15, 20, 35, 0.6);
  border: 1px solid rgba(100, 120, 160, 0.25);
  background-image:
    radial-gradient(circle at center, rgba(60, 80, 120, 0.12) 0%, transparent 70%);
  transition: all 0.2s ease;
  position: relative;
}

.combat-cell.player-zone {
  border-color: rgba(0, 180, 220, 0.2);
  background: rgba(0, 40, 60, 0.25);
}

.combat-cell.enemy-zone {
  border-color: rgba(220, 60, 60, 0.15);
  background: rgba(40, 10, 10, 0.2);
}

/* 可移动高亮 */
.combat-cell.highlight-move {
  border-color: rgba(0, 180, 255, 0.8) !important;
  box-shadow: inset 0 0 14px rgba(0, 180, 255, 0.15), 0 0 10px rgba(0, 180, 255, 0.25);
}

/* 可攻击高亮 */
.combat-cell.highlight-target {
  border-color: rgba(255, 80, 60, 0.85) !important;
  box-shadow: inset 0 0 14px rgba(255, 80, 60, 0.15), 0 0 10px rgba(255, 80, 60, 0.25);
}

/* 选中高亮（金色脉冲） */
.combat-cell.highlight-selected {
  border-color: rgba(240, 192, 96, 1) !important;
  box-shadow: inset 0 0 18px rgba(240, 192, 96, 0.15), 0 0 14px rgba(240, 192, 96, 0.35);
  animation: cell-pulse 1.5s ease-in-out infinite;
}

/* 拖动预览高亮 */
.combat-cell.highlight-cursor {
  border-color: rgba(240, 192, 96, 0.7);
  box-shadow: 0 0 8px rgba(240, 192, 96, 0.3);
}

@keyframes cell-pulse {
  0%, 100% { box-shadow: inset 0 0 18px rgba(240, 192, 96, 0.15), 0 0 14px rgba(240, 192, 96, 0.35); }
  50%      { box-shadow: inset 0 0 24px rgba(240, 192, 96, 0.25), 0 0 20px rgba(240, 192, 96, 0.5); }
}
```

### 1.3 地图背景

分层背景（远景天空渐变 + 地面纹理 + 网格线 + 单位层 + UI 层）：

```css
.combat-bg-urban {
  background:
    linear-gradient(to bottom,
      rgba(10, 15, 30, 1) 0%,
      rgba(20, 25, 45, 0.8) 40%,
      rgba(30, 35, 55, 0.5) 100%
    ),
    repeating-linear-gradient(90deg, transparent, transparent 55px, rgba(60,80,120,0.08) 55px, rgba(60,80,120,0.08) 56px),
    repeating-linear-gradient(0deg, transparent, transparent 55px, rgba(60,80,120,0.08) 55px, rgba(60,80,120,0.08) 56px);
}
```

不同遭遇战可切换不同地面纹理（预留接口）。

### 1.4 地图装饰（预留）

- **部署点标记**：玩家侧发光边框区分玩家区 / 敌方区
- **行列标签**：行号 0-8（左侧）、列号 0-7（顶部），monospace 字体
- **无障碍网格**：空单元格内显示淡色坐标提示

---

## 二、战斗小人系统

### 2.1 资源规格

| 项目 | 规格 |
|------|------|
| 格式 | PNG 序列帧 或 Spine 骨骼动画 |
| 分辨率 | 128×128 或 256×256 |
| 朝向 | 4 方向（0=上, 1=右, 2=下, 3=左） |
| 动画 | idle / attack / hit / death |

### 2.2 当前占位方案：CSS 像素小人

已实现的 `ChibiSprite` 组件（48×60px）：

- **身体**：28×30px 梯形，职业色渐变 + 装甲线 + 腰带
- **头部**：22×24px 圆形，强调色渐变 + 深色边框 + 白眼 + 瞳孔（根据 attack 动画位移）
- **武器**（`ChibiWeapon` 子组件）：8 种职业各有独特 CSS 形状
  - 近卫=剑形三角，狙击=长枪管，重装=方形盾，术师=发光球
  - 医疗=绿球，先锋=单线，辅助=边框方块，特种=短线
- **HP 条**：悬浮在头顶上方（仅 hp < maxHP 时显示）
- **部署方向箭头**：三角形指示朝向
- **动画**：hit-shake（0.3s 震动）、death（opacity+grayscale+scaleY）

后续阶段将支持 Spine 动画替换。

### 2.3 方向系统

```
0 (上) — row 减小方向（屏幕上方，远处）
1 (右) — col 增大方向
2 (下) — row 增大方向（屏幕下方，近处）
3 (左) — col 减小方向
```

---

## 三、卡牌展示系统

### 3.1 卡面设计（140×190px）

```
┌────────────────────────────┐
│  ╔══════════════════════╗  │
│  ║   [卡图区域 80px 高]  ║  │  ← 程序化 CSS 渐变 + 名称水印
│  ║   伤害类型图标（角标）  ║  │  ← 物/法/治/混 + elite ★
│  ╚══════════════════════╝  │
│  名称              AP 消耗  │
│  15-25  ×1.2               │  ← 伤害范围 + 倍率
│  单体 · 1格                │  ← 目标模式 + 范围
│  职业 @拥有者      [热键]   │  ← 职业限制 + 数字快捷键
└────────────────────────────┘
│← 4px 职业色带（左侧竖条）
```

### 3.2 程序化卡图

使用 card_id hash + damage_type hue 生成确定性 CSS 渐变背景，确保同一张卡始终显示相同卡图：

```tsx
function cardArtGradient(cardId: string, damageType: string): string {
  const hash = cardId.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
  const hue1 = (hash * 37) % 360;
  const hue2 = (hue1 + 40) % 360;
  const dmgHues = { physical: 15, arts: 270, healing: 140, mixed: 45 };
  const base = dmgHues[damageType] || 220;
  return `linear-gradient(135deg, hsl(${base}, 40%, 18%) 0%, hsl(${base + 30}, 35%, 12%) 50%, hsl(${base - 20}, 30%, 8%) 100%)`;
}
```

### 3.3 卡牌 CSS（实际实现）

```css
.combat-card {
  width: 140px;
  height: 190px;
  border-radius: 8px;
  background: linear-gradient(160deg, #16192b 0%, #111827 50%, #0d1525 100%);
  border: 2px solid #2a3a5e;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 职业色带（左侧 4px） */
.combat-card::before {
  content: '';
  position: absolute; left: 0; top: 0; bottom: 0;
  width: 4px; z-index: 2;
}
.combat-card.class-vanguard::before { background: #d4a574; }
.combat-card.class-guard::before { background: #c44b3c; }
/* ... 其余 6 种职业类似 */

/* elite 金边 */
.combat-card.elite {
  border-color: #c8a840;
  box-shadow: 0 0 10px rgba(200, 168, 64, 0.25), 0 2px 8px rgba(0,0,0,0.4);
}

/* 悬停：抬起 + 放大 */
.combat-card:hover {
  transform: translateY(-8px) scale(1.05);
  z-index: 10;
}

/* 选中：更高浮起 + 金色脉冲 */
.combat-card.selected {
  border-color: #f0c060 !important;
  transform: translateY(-14px);
  box-shadow: 0 0 18px rgba(240, 192, 96, 0.5), 0 4px 16px rgba(0,0,0,0.5);
  animation: card-selected-glow 1.5s ease-in-out infinite;
}

/* 不可用：灰度 + 禁止点击 */
.combat-card.disabled {
  opacity: 0.4;
  filter: grayscale(0.5);
  cursor: not-allowed;
}
.combat-card.disabled:hover { transform: none; }

@keyframes card-selected-glow {
  0%, 100% { box-shadow: 0 0 18px rgba(240, 192, 96, 0.5), 0 4px 16px rgba(0,0,0,0.5); }
  50% { box-shadow: 0 0 28px rgba(240, 192, 96, 0.7), 0 4px 20px rgba(0,0,0,0.6); }
}
```

### 3.4 手牌弧形布局

```tsx
// CombatHand.tsx — 扇形排列
const fanAngle = 3.5; // 每张牌偏移度数
const fanY = 8;       // 每张牌垂直偏移 px

cards.map((card, i) => {
  const offset = i - (cards.length - 1) / 2;
  const rotation = offset * fanAngle;
  const translateY = Math.abs(offset) * fanY;
  // transform: `rotate(${rotation}deg) translateY(${translateY}px)`
});

// 悬停：抬起 + 放大，z-index 提升到最前
.combat-hand-fan .hand-card-wrapper:hover {
  transform: translateY(-16px) scale(1.08) !important;
  z-index: 50 !important;
}
```

---

## 四、单位状态面板

### 4.1 设计概念（UnitStatusPanel）

角色卡片式面板，选中/悬停状态区分：

```
┌─────────────────────┐
│  [头像 40px] 阿米娅   │  ← 首字头像 + 职业色背景 + 光晕
│  ═══════════════════ │
│  HP ████████░░ 78%  │  ← 6px 高渐变 HP 条（绿→黄→红）
│     154 / 198       │  ← monospace 数值
│  AP ◆◆◇ (2/3)      │  ← 10×10px 方块 + glow
└─────────────────────┘
```

### 4.2 HP 条渐变

```css
.combat-hp-fill.high   { background: linear-gradient(90deg, #2ecc71, #27ae60); }
.combat-hp-fill.medium { background: linear-gradient(90deg, #f39c12, #e67e22); }
.combat-hp-fill.low    { background: linear-gradient(90deg, #e74c3c, #c0392b); animation: hp-pulse 0.8s infinite; }
```

### 4.3 布局位置

- **我方状态面板**：左侧 w-56，垂直排列，顶部显示共享 AP 条
- **敌方状态面板**：右侧 w-56，简化信息
- **当前行动角色**：高亮边框 + 金色光效

---

## 五、战斗事件与特效

### 5.1 伤害数字

```css
.damage-number {
  font-family: 'Orbitron', 'Arial Black', sans-serif;
  font-weight: 900; font-size: 28px; color: #fff;
  text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000,
    0 0 8px rgba(255, 60, 30, 0.8);
  animation: damage-float 1s ease-out forwards;
  pointer-events: none;
}
.damage-number.physical { color: #ff6b4a; }  /* 橙红 + 对应光晕 */
.damage-number.arts     { color: #b44af0; }  /* 紫色 */
.damage-number.heal     { color: #4aff8b; }  /* 绿色 */
.damage-number.crit     { font-size: 38px; color: #ffd700; }

@keyframes damage-float {
  0%   { transform: translateY(0) scale(0.8); opacity: 1; }
  20%  { transform: translateY(-6px) scale(1.15); opacity: 1; }
  100% { transform: translateY(-36px) scale(0.85); opacity: 0; }
}
```

### 5.2 Canvas 粒子系统（CombatParticles）

不使用 WebGL 依赖，纯 Canvas 2D 实现：

```tsx
// 4 种粒子发射器配置
spark:  { count: 8-20,  speed: 1.5-3, size: 2-4, life: 400-800ms, colors: orange/red }
heal:   { count: 6-10,  speed: 0.8-2, size: 2-5, life: 600-1000ms, colors: green/cyan }
death:  { count: 12-20, speed: 1-3,   size: 2-5, life: 500-900ms, colors: gray/purple }
victory:{ count: 30-50, speed: 1-4,   size: 2-6, life: 800-1500ms, colors: gold/yellow }
```

**渲染循环**：requestAnimationFrame 驱动，粒子 x+=vx / y+=vy，globalAlpha 随 life 衰减，自动清理已死亡粒子。支持 HiDPI（devicePixelRatio）。

### 5.3 SSE 事件驱动的特效触发

```tsx
// CombatView.tsx — SSE handler
onEvent: (ev) => {
  if (ev.type === "damage" && ev.data?.damage > 0) {
    addDamageNumber(ev.data.damage, ev.data.damage_type, pos);
    spawnParticles("spark", pos, 8 + Math.floor(ev.data.damage / 5));
  }
  if (ev.type === "heal") { addDamageNumber(ev.data.amount, "heal", pos); spawnParticles("heal", pos, 6); }
  if (ev.type === "death") { spawnParticles("death", pos, 15); }
  if (ev.type === "battle_end" && winner === "player") { spawnParticles("victory", [4,4], 40); }
}
```

### 5.4 战斗事件日志（CombatEventLog）

Timeline 风格，Unicode 图标：

| 事件类型 | 图标 | 说明 | 状态 |
|---------|------|------|------|
| round_start | ◎ | 回合开始 | ✅ |
| damage | ⚔ | 伤害事件 | ✅ |
| heal | ✦ | 治疗事件 | ✅ |
| death | ☠ | 死亡事件 | ✅ |
| battle_end | ◈ | 战斗结束 | ✅ |
| move | ↗ | 移动 | ✅ |
| card_played | 🃏 | 卡牌打出 | ✅ |
| block_attempt | 🛡 | 格挡尝试 | 📐 未实现 |
| block_success | ✓ | 格挡成功 | 📐 未实现 |
| block_fail | ✗ | 格挡失败 | 📐 未实现 |
| intercept_prompt | ⚡ | 拦截提示 | 📐 未实现 |

日志限制最近 80 条，类型使用 combat color token 区分颜色。

### 5.5 攻击动画序列

```
卡牌打出动画 → API 请求并行 → 攻击者闪烁 → 特效飞向目标 → 目标震动 + 伤害数字弹出

时间线（乐观动画）:
  0ms    : 卡牌打出动画开始（card-play-out: 放大 1.15× → 发光 → 淡出上浮 36px）
  0ms    : API 请求并行发起
  400ms  : 动画结束 + 手牌刷新，剩余卡牌 CSS transition 平滑重排（0.3s）
  600ms  : 目标震动（unit-hit-shake, 0.3s）
  700ms  : 伤害数字弹出
  1000ms : 粒子消散
```

### 5.6 卡牌打出动画

```css
/* 打出时应用 .card-playing 类 */
.combat-card.card-playing {
  animation: card-play-out 0.45s ease-out forwards;
  pointer-events: none;
}

@keyframes card-play-out {
  0%   { transform: scale(1);    opacity: 1; filter: brightness(1);   box-shadow: ...; }
  20%  { transform: scale(1.15); opacity: 1; filter: brightness(1.5); box-shadow: ...; }
  100% { transform: scale(1.2) translateY(-36px); opacity: 0; filter: brightness(2); }
}
```

手牌重排依赖 React key 稳定性：使用 `${card_id}-${owner}` 代替 `${card_id}-${index}`，
打出后剩余卡牌 DOM 节点保留，CSS `transition: transform 0.3s ease` 自动处理扇形位置过渡。

### 5.6 战斗结束 Overlay

```css
.combat-overlay-enter {
  animation: overlay-fade-in 0.5s ease-out;
}
@keyframes overlay-fade-in {
  0%   { opacity: 0; backdrop-filter: blur(0); }
  100% { opacity: 1; backdrop-filter: blur(4px); }
}
```

VICTORY / DEFEAT 使用 Orbitron 字体，金色 / 红色显示，含回合统计。

---

## 六、整体布局与配色

### 6.1 全局布局

```
┌─────────────────────────────────────────────────────┐
│  Round N · 我方行动 · 共用 AP: ◆◆◇◇               │  ← 顶部信息栏（共享回合制，无当前角色名）
├────────┬───────────────────────────────┬────────────┤
│  我方  │                               │  敌方      │
│  状态  │      战斗地图（俯视 + 透视）     │  状态      │
│  面板  │      9 rows × 8 cols          │  面板      │
│  w-56  │      + ChibiSprite            │  w-56      │
│        │      + 伤害数字 overlay        │            │
│        │      + Canvas 粒子层           │            │
├────────┴───────────────────────────────┴────────────┤
│  AP: ◆◆◇◇  |  手牌: 5  |  [结束回合(F)] [取消(Esc)] │  ← 操作栏
│  ┌─────────────────────────────────────────────────┐│
│  │       手牌区域（弧形扇形排列 + 拖动支持）          ││
│  │   [卡1]  [卡2]  [卡3]  [卡4]  [卡5]             ││
│  └─────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────┐│
│  │  事件日志（Timeline 滚动）                        ││
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

### 6.2 配色方案（Tailwind 扩展）

```js
// tailwind.config.js
colors: {
  combat: {
    bg: '#0a0e17',        // 最深蓝黑
    panel: '#111827',     // 面板背景
    border: '#1e3a5f',   // 边框
    divider: '#2a3a5e',   // 分割线
    player: '#00b4d8',   // 玩家色（cyan）
    enemy: '#e74c3c',    // 敌方色（red）
    gold: '#f0c060',     // 金色高亮
    ap: '#00d4ff',       // AP 点色
  },
  class: {                // 8 种职业色
    vanguard: '#d4a574', guard: '#c44b3c',
    defender: '#4a6b8a', sniper: '#3c8c4a',
    caster: '#8b5ca8',   medic: '#5c9a8b',
    supporter: '#c4a83c', specialist: '#6b5c8a',
  },
  dmg: {                  // 4 种伤害类型色
    physical: '#ff6b4a', arts: '#b44af0',
    healing: '#4aff8b',  mixed: '#f0c060',
  },
}
```

### 6.3 字体

| 用途 | 字体 | 引入 |
|------|------|------|
| 标题/数字 | Orbitron (500/700/900) | Google Fonts |
| 中文正文 | Noto Sans SC (400/500/700) | Google Fonts |
| 代码/数值 | JetBrains Mono (400/500) | Google Fonts |

### 6.4 浅色主题

通过 `html.light` 选择器覆盖深色主题，涵盖背景、文字、边框、面板、按钮等全部 combat 相关样式。

---

## 七、动画系统

### 7.1 动画清单

| 动画 | 触发条件 | 时长 | 技术 |
|------|---------|------|------|
| 格子高亮出现 | 选中角色/卡牌 | 200ms | CSS transition |
| 选中脉冲 | 持续 | 1.5s loop | CSS @keyframes |
| 卡牌悬停抬起 | hover | 250ms | CSS transition |
| 卡牌选中浮起 | click | 250ms | CSS transition |
| 卡牌选中光晕 | 持续 | 1.5s loop | CSS @keyframes |
| 卡牌打出（放大淡出） | play_card API 调用 | 0.45s | CSS @keyframes |
| 手牌重排 | 打出后 state 刷新 | 0.3s | CSS transition |
| 伤害数字弹出 | SSE damage 事件 | 1s | CSS @keyframes |
| 角色受击震动 | SSE damage 事件 | 0.3s | CSS @keyframes |
| HP 条变化 | state 更新 | 400ms | CSS transition |
| HP 低闪烁 | HP < 阈值 | 0.8s loop | CSS @keyframes |
| 粒子特效 | SSE 事件 | 0.4-1.5s | Canvas requestAnimationFrame |
| 战斗结束 overlay | 战斗结束 | 500ms | CSS @keyframes |

### 7.2 实现技术

| 技术 | 用途 |
|------|------|
| CSS transitions | 简单状态切换（悬停、选中、HP 条） |
| CSS @keyframes | 循环动画（脉冲、呼吸灯、伤害数字浮空） |
| Canvas 2D | 粒子特效（轻量，无 WebGL 依赖） |
| HTML5 Drag API | 卡牌拖拽到目标格子 |
| Framer Motion | 预留（当前未引入依赖） |

---

## 八、资源管线

### 8.1 资源目录结构

```
frontend/public/assets/combat/
├── chibis/                    # 战斗小人（预留 Spine/PNG 资源）
│   ├── 阿米娅/               # idle / attack / hit / death
│   └── ...
├── cards/                     # 卡面插图（预留，当前用程序化渐变）
├── icons/                     # UI 图标
│   ├── classes/              # 职业图标（预留 SVG）
│   └── damage-types/         # 伤害类型图标（预留 SVG）
├── backgrounds/               # 地图背景（预留）
└── avatars/                   # 角色头像（预留，当前用首字占位）
```

### 8.2 当前占位策略

| 资源 | 占位方案 | 替换接口 |
|------|---------|---------|
| 战斗小人 | CSS 像素小人（ChibiSprite）+ 职业武器 | `<img>` 替换 CSS |
| 卡面插图 | 程序化 CSS 渐变（cardArtGradient） | `background-image` 替换 |
| 角色头像 | 首字 + 职业色背景（AvatarPlaceholder） | `<img>` 替换 |
| 粒子特效 | Canvas 2D 绘制 | 可直接替换粒子图片 |
| 地图背景 | CSS linear-gradient | 切换 className 加载不同背景 |

---

## 九、分阶段实施路线

### Phase 1：基础视觉升级 ✅ 已完成
- [x] CSS 配色方案迁移（深蓝黑 + 金色 + 职业色 + 伤害类型色）
- [x] 格子视觉升级（56×56px，发光边框，高亮系统，zone 区分）
- [x] 地图透视（CSS rotateX 6deg + perspective 2000px）
- [x] 卡牌基础美化（圆角、阴影、悬停效果、职业色带、elite 金边）
- [x] HP/AP 条视觉升级（渐变、脉冲动画、AP 点阵 glow）

### Phase 2：布局与交互 ✅ 已完成
- [x] 弧形手牌布局（扇形 fanAngle 3.5° + fanY 8px）
- [x] 状态面板重构为角色卡片式（UnitStatusPanel）
- [x] 事件日志 Timeline 化（CombatEventLog + Unicode 图标）
- [x] 伤害数字弹出动画（Orbitron 字体 + 类型色 + 描边）
- [x] CSS transition/keyframes 动画
- [x] 键盘快捷键（F=结束回合, Esc=取消, 数字键=选牌）

### Phase 3：角色与卡面 ✅ 已完成
- [x] CSS 像素小人（ChibiSprite + ChibiWeapon 8 种职业武器）
- [x] 角色头像占位（AvatarPlaceholder 首字 + 职业色背景）
- [x] 程序化卡面（cardArtGradient 基于 card_id hash）
- [x] 职业图标系统（CSS class 色带 + Unicode 标签）
- [x] 受击震动动画（unit-hit-shake）

### Phase 4：特效 ✅ 已完成
- [x] Canvas 粒子系统（CombatParticles：spark/heal/death/victory）
- [x] SSE 事件驱动的特效触发（damage/heal/death/battle_end）
- [x] 战斗结束 overlay（VICTORY/DEFEAT + blur 背景）
- [x] 卡牌不可用状态（灰度 + 禁止点击）
- [x] 浅色主题（html.light CSS 覆盖）

### Phase 5：交互增强 ✅ 已完成
- [x] 卡牌拖拽到目标格子（HTML5 Drag & Drop + findClosestCell）
- [x] 拖动中格子高亮（dragCell state + highlight-cursor）
- [x] 单位悬浮提示框（CombatUnitTooltip：8 属性 + 战斗数值 + 物品）
- [x] 战斗回写到会话（combat writeback）
- [ ] 平板/手机触屏支持
- [ ] 音效系统

### Phase 6：资源升级（待开始）
- [ ] 战斗小人静态 PNG 资源导入
- [ ] 卡面插图资源导入
- [ ] 多地图背景切换
- [ ] Spine/序列帧动画支持
- [ ] Service Worker 资源缓存

---

## 十、卡牌拖动交互

### 10.1 实现原理

HTML5 Drag and Drop API + React state 管理：

```tsx
// CombatCard.tsx — 拖动源
const handleDragStart = (e: React.DragEvent) => {
  if (!affordable) { e.preventDefault(); return; }
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", String(index));
  // 透明拖拽图片，不遮挡光标
  const img = new Image();
  img.src = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
  e.dataTransfer.setDragImage(img, 0, 0);
  onDragStart?.();
};

// CombatGrid.tsx — 放置目标
const findClosestCell = (clientX, clientY, gridRect, gridSize) => {
  // 计算鼠标相对网格的位置，映射到最近格子
  const relX = clientX - gridRect.left;
  const relY = clientY - gridRect.top;
  const col = Math.round((relX - CELL) / (CELL + 2)); // 减行列标签宽
  const row = Math.round(relY / (CELL + 2));
  if (row >= 0 && row < gridSize && col >= 0 && col < gridSize) return [row, col];
  return null;
};

// CombatView.tsx — 拖放处理
handleCardDragStart → 设置 dragCardIndex + 进入 TARGETING 模式
handleGridDragMove  → 更新 dragCell 高亮
handleGridDrop      → 执行 play_card 动作（复用 TARGETING 点击逻辑）
handleCardDragEnd   → 清除拖拽状态
```

### 10.2 交互流程

1. 玩家按住可支付的卡牌开始拖动
2. 手牌保持原位，隐藏原生拖拽预览图
3. 鼠标移动到网格上时，对应格子高亮（金色光标）
4. 松开鼠标：执行卡牌打出动作，清除高亮
5. 拖到无效区域松开：取消拖动，清除状态

---

## 十一、单位悬浮提示框

### 11.1 CombatUnitTooltip

在 UnitStatusPanel 中悬停单位时，使用 `createPortal` 渲染到 body 的浮动提示框：

```
┌─────────────────────────────┐
│  阿米娅              [术师]  │  ← 名称 + 职业标签（team 色）
│  ─────────────────────────  │
│  属性                       │
│  物理强度  ████░░  8        │  ← 8 项属性，带进度条 + 数值
│  战场机动  ███░░░  6        │     颜色按值分级（>=8 黄, >=6 绿, >=4 蓝）
│  ...                        │
│  ─────────────────────────  │
│  战斗数值                   │
│  HP 154/198  物理攻击 28    │  ← 3 列网格排列
│  法术攻击 15  防御 12       │
│  法术抗性 5   速度 8        │
│  命中 7       闪避 3        │
│  AP 2/3                     │
│  ─────────────────────────  │
│  携带物品                   │
│  暂未携带物品               │  ← 预留
└─────────────────────────────┘
```

**定位**：智能避让视口边缘，优先显示在锚点右侧，空间不足时切换到左侧。

---

## 十二、战斗回写与会话覆盖

### 12.1 功能说明

战斗结束后，战斗结果和角色状态变化（HP 变化、受伤、死亡等）会回写到当前会话中：

- **会话覆盖层**（session_overlay）：临时修改会话中的角色数据，不影响原始数据文件
- **combat_end 回调**：战斗引擎结束时计算 units 和 entities 的最终状态
- **前端 API**：`api.combatEnd(sessionId)` 触发回写流程

### 12.2 后端实现

```python
# src/app.py — combat_end endpoint
# 1. 获取当前战斗 state
# 2. 提取 units 的 HP/状态变化
# 3. 写入会话覆盖层（session_overlay）
# 4. 清理战斗 session
```

---

## 附录 A：技术栈推荐

| 用途 | 当前实现 | 备注 |
|------|---------|------|
| 动画框架 | CSS + Canvas 2D | 无额外依赖 |
| 粒子特效 | 自研 Canvas 层 | 轻量，无 WebGL 依赖 |
| 序列帧播放 | 预留 | 可自研 SpritePlayer |
| 骨骼动画 | 预留 PixiJS + pixi-spine | 如需 Spine 支持 |
| 音效 | 预留 Howler.js | 轻量，支持音频精灵 |
| SVG 图标 | Unicode 字符 | 当前无图标库依赖 |
| 字体 | Google Fonts | Orbitron + Noto Sans SC + JetBrains Mono |

## 附录 B：样式变量定义（CSS custom properties）

```css
:root {
  /* 背景与面板 */
  --combat-bg: #0a0e17;
  --combat-panel: rgba(17, 24, 39, 0.85);
  --combat-border: #1e3a5f;
  --combat-divider: #2a3a5e;

  /* 主色调 */
  --color-player: #00b4d8;
  --color-enemy: #e74c3c;
  --color-gold: #f0c060;
  --color-ap: #00d4ff;

  /* HP 颜色 */
  --hp-high: #2ecc71;
  --hp-medium: #f39c12;
  --hp-low: #e74c3c;

  /* 职业颜色 */
  --class-vanguard: #d4a574;
  --class-guard: #c44b3c;
  --class-defender: #4a6b8a;
  --class-sniper: #3c8c4a;
  --class-caster: #8b5ca8;
  --class-medic: #5c9a8b;
  --class-supporter: #c4a83c;
  --class-specialist: #6b5c8a;

  /* 伤害类型 */
  --dmg-physical: #ff6b4a;
  --dmg-arts: #b44af0;
  --dmg-healing: #4aff8b;
  --dmg-mixed: #f0c060;

  /* 动画 */
  --ease-combat: cubic-bezier(0.4, 0, 0.2, 1);
  --duration-fast: 150ms;
  --duration-normal: 250ms;
  --duration-slow: 400ms;

  /* 字体 */
  --font-display: 'Orbitron', sans-serif;
  --font-body: 'Noto Sans SC', sans-serif;
  --font-mono: 'JetBrains Mono', monospace;

  /* 透视（实际实现值） */
  --grid-perspective: 2000px;
  --grid-rotate-x: 6deg;
  --cell-size: 56px;
}
```

## 附录 C：实施记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-05-23 | v1.0 | 初始设计方案 |
| 2026-05-23 | v2.0 | Phase 1-5 全部实施完成：CSS 3D 透视、56px 格子、像素小人、程序化卡面、Canvas 粒子、伤害数字、弧形手牌、拖拽交互、单位提示框、战斗回写、浅色主题 |
