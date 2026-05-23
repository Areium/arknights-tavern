# 战斗 UI 美化方案

> 基于明日方舟美术风格的俯视视角战斗界面设计
> 当前版本：v1.0 · 2026-05-23

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

---

## 概述

### 当前状态

- **地图**：正投影棋盘，9×8 方格，纯色背景，单元格 40×40px
- **单位**：单元格内显示角色名前两字，无立绘/小人
- **卡牌**：136×96px 长方形色块，仅显示文字数值
- **状态面板**：半透明 overlay，HP 条 + AP 点
- **事件日志**：纯文本滚动列表
- **配色**：Tailwind gray-900 系暗色底，cyan/red 区分敌我

### 目标状态

- **俯视视角地图**：等距透视（2.5D），从远到近的空间纵深感
- **单位**：Q 版战斗小人（chibi sprites）站在格子上，带朝向、待机动画
- **卡牌**：完整卡面设计（卡图 + 边框 + 稀有度特效），参考明日方舟游戏内卡牌
- **状态面板**：角色头像 + HP/AP 条 + 职业图标，融入整体 UI
- **特效**：攻击动画、伤害数字、移动轨迹、卡牌打出特效
- **配色**：明日方舟 UI 风格 —— 深蓝黑底 + 金色描边 + 科技感线条

### 核心参考：《明日方舟》俯视视角

明日方舟的战斗视角特点：
1. **45° 俯视等距**（isometric-like，非真等距，而是透视缩短的正俯视）
2. **地面格子有透视**——远处格子比近处略小，形成深度感
3. **角色小人**是预渲染的 2D spine 动画，站在格子上
4. **部署方向**箭头指示角色朝向
5. **格子高亮**用发光的边框而非纯色填充
6. **技能特效**叠加在格子上，有粒子感
7. **伤害数字**弹出动画，字体粗大有描边

---

## 一、网格/地图系统

### 1.1 透视方案：伪等距俯视（Pseudo-Isometric Top-Down）

在正俯视基础上加入透视缩短（foreshortening），用 CSS 3D transform 实现：

```
原理：将整个棋盘容器绕 X 轴旋转 15-20°，产生"从前往后看"的深度感。

CSS:
  .combat-grid-container {
    perspective: 1200px;
    perspective-origin: 50% 40%;
  }
  .combat-grid {
    transform: rotateX(18deg);
    transform-style: preserve-3d;
  }
```

**效果**：
- 近处的格子（屏幕下方，玩家侧）比远处（屏幕上方，敌人侧）视觉上略大
- 角色小人近大远小，自然形成空间感
- 不需要真正的 3D 渲染，纯 CSS 即可实现

### 1.2 格子视觉设计

每个格子从当前的纯色方块升级为：

```
┌──────────────────────────────┐
│  格子状态                    │
│                              │
│  默认：半透明深色底 + 细边框  │
│  ┌──────────┐               │
│  │ ·········│  ← 虚线网格线  │
│  │ ·········│               │
│  │ ·········│               │
│  └──────────┘               │
│                              │
│  高亮：发光边框 + 微弱填充   │
│  可移动：蓝色光晕边框        │
│  可攻击：红色光晕边框        │
│  已选中：金色脉冲边框        │
└──────────────────────────────┘
```

#### 格子 CSS 设计

```css
/* 默认格子 */
.grid-cell {
  width: 64px;
  height: 64px;
  background: rgba(15, 20, 35, 0.6);
  border: 1px solid rgba(100, 120, 160, 0.3);
  /* 内部虚线纹理 */
  background-image: 
    radial-gradient(circle at center, rgba(60, 80, 120, 0.15) 0%, transparent 70%);
  transition: all 0.2s ease;
}

/* 部署格子（player zone） */
.grid-cell.player-zone {
  border-color: rgba(0, 180, 220, 0.25);
  background: rgba(0, 40, 60, 0.3);
}

/* 敌方格子（enemy zone） */
.grid-cell.enemy-zone {
  border-color: rgba(220, 60, 60, 0.2);
  background: rgba(40, 10, 10, 0.25);
}

/* 可移动高亮 */
.grid-cell.move-highlight {
  border-color: rgba(0, 180, 255, 0.8);
  box-shadow: 
    inset 0 0 12px rgba(0, 180, 255, 0.2),
    0 0 8px rgba(0, 180, 255, 0.3);
}

/* 可攻击高亮 */
.grid-cell.target-highlight {
  border-color: rgba(255, 80, 60, 0.8);
  box-shadow: 
    inset 0 0 12px rgba(255, 80, 60, 0.2),
    0 0 8px rgba(255, 80, 60, 0.3);
}

/* 选中格子 */
.grid-cell.selected {
  border-color: rgba(255, 200, 60, 1);
  box-shadow: 
    inset 0 0 16px rgba(255, 200, 60, 0.2),
    0 0 12px rgba(255, 200, 60, 0.4);
  animation: cell-pulse 1.5s ease-in-out infinite;
}

@keyframes cell-pulse {
  0%, 100% { box-shadow: inset 0 0 16px rgba(255, 200, 60, 0.2), 0 0 12px rgba(255, 200, 60, 0.4); }
  50%      { box-shadow: inset 0 0 20px rgba(255, 200, 60, 0.35), 0 0 18px rgba(255, 200, 60, 0.55); }
}
```

### 1.3 地图背景

当前是纯色背景，改为分层背景：

```
层级结构（从远到近）：
┌─────────────────────────────┐
│  远景层：天空/环境氛围渐变    │  ← 远处云雾/城市轮廓
│  中景层：战场地面纹理        │  ← 石板/沙地/金属地面
│  近景层：网格线              │  ← 虚线战术网格覆盖
│  单位层：角色 & 特效         │  ← chibi sprites
│  UI 层：高亮/选框/伤害数字    │  ← 交互元素
└─────────────────────────────┘
```

**实现方式**：
- 远景层用 CSS `linear-gradient` 模拟场景氛围
- 地面纹理用可配置的 tile 图片或 SVG pattern
- 不同遭遇战可切换不同地面纹理（城市石板 / 雪地 / 荒野 / 室内）

```css
/* 示例：城市夜景战场 */
.combat-bg-urban {
  background:
    /* 远景：深蓝到黑的天空渐变 */
    linear-gradient(to bottom, 
      rgba(10, 15, 30, 1) 0%,      /* 远处天空 */
      rgba(20, 25, 45, 0.8) 40%,   /* 中景 */
      rgba(30, 35, 55, 0.5) 100%   /* 近景 */
    ),
    /* 地面纹理（SVG pattern 或 CSS） */
    repeating-linear-gradient(
      90deg,
      transparent,
      transparent 63px,
      rgba(60, 80, 120, 0.08) 63px,
      rgba(60, 80, 120, 0.08) 64px
    ),
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 63px,
      rgba(60, 80, 120, 0.08) 63px,
      rgba(60, 80, 120, 0.08) 64px
    );
}
```

### 1.4 地图装饰

在格子上添加战斗相关的环境元素（纯装饰）：

- **部署点标记**：玩家侧有发光箭头/圆圈标记可部署位置
- **出生点特效**：战斗开始时角色出现的短暂粒子效果
- **障碍物/掩体**：半高方块或光柱，阻挡移动和视线
- **区域分界线**：玩家区与敌方区之间有一条发光的战术分界线

---

## 二、战斗小人系统

### 2.1 资源规格

| 项目 | 规格 |
|------|------|
| 格式 | PNG 序列帧 或 Spine 骨骼动画（推荐） |
| 分辨率 | 128×128 或 256×256（支持 Retina） |
| 帧率 | 24-30fps |
| 动画 | 待机（idle）、攻击（attack）、受伤（hit）、移动（walk）、技能（skill）、死亡（death） |
| 朝向 | 4 方向（上/下/左/右）或 8 方向 |

### 2.2 占位方案（资源到位之前）

在没有实际战斗小人资源时，使用以下占位方案：

```
阶段 1 — 纯 CSS 像素小人
  用 div + CSS 构建简易的 Q 版角色造型
  每种职业有不同的像素配色

阶段 2 — 静态 PNG + CSS 动画
  准备每个角色的正面站立图
  用 CSS transform 实现简单的晃动、缩放动画

阶段 3 — Spine/序列帧动画
  完整的战斗小人动画系统
```

#### CSS 像素小人示例

```tsx
// 简易的职业色块小人（占位用）
function PlaceholderChibi({ charClass, team, direction }: {
  charClass: string; team: "player" | "enemy"; direction: number;
}) {
  const colorMap: Record<string, string> = {
    "先锋": "#d4a574", "近卫": "#c44b3c", "重装": "#4a6b8a",
    "狙击": "#3c8c4a", "术师": "#8b5ca8", "医疗": "#5c9a8b",
    "辅助": "#c4a83c", "特种": "#6b5c8a",
  };
  
  return (
    <div className={`chibi-placeholder ${team}`}
      style={{
        transform: `rotateY(${direction * 90}deg)`,
        backgroundColor: colorMap[charClass] || "#666",
      }}
    >
      <div className="chibi-head" />
      <div className="chibi-body" />
    </div>
  );
}
```

### 2.3 小人容器组件

```tsx
interface ChibiSpriteProps {
  unit: CombatUnitDTO;
  animation: "idle" | "attack" | "hit" | "move" | "skill" | "death";
  direction: number; // 0-3，对应上下左右
  scale?: number;     // 默认 1.0
}

function ChibiSprite({ unit, animation, direction, scale = 1 }: ChibiSpriteProps) {
  const spritePath = `/assets/combat/chibis/${unit.name}/${animation}.png`;
  const hasSprite = useSpriteExists(spritePath);
  
  if (!hasSprite) {
    return <PlaceholderChibi charClass={unit.char_class} team={unit.team} direction={direction} />;
  }
  
  return (
    <div className="chibi-container" style={{ transform: `scale(${scale})` }}>
      <img src={spritePath} alt={unit.name} />
      {/* 血条（悬浮在小人上方） */}
      <div className="chibi-hp-bar">
        <div className="fill" style={{ width: `${(unit.hp / unit.max_hp) * 100}%` }} />
      </div>
    </div>
  );
}
```

### 2.4 方向系统

角色朝向由其所在位置和最后行动方向决定：

```
方向定义（棋盘坐标）：
  0 (上) — 向 row 减小的方向（屏幕上方，远处）
  1 (右) — 向 col 增大的方向
  2 (下) — 向 row 增大的方向（屏幕下方，近处）
  3 (左) — 向 col 减小的方向
```

攻击时自动朝向目标方向，并在攻击动画结束后恢复默认朝向（玩家角色朝右，敌方朝左）。

---

## 三、卡牌展示系统

### 3.1 卡面设计

每张卡牌有完整的卡面设计，参考明日方舟和 Slay the Spire 的风格融合：

```
┌────────────────────────────┐
│  ╔══════════════════════╗  │
│  ║    [卡图区域]        ║  │  ← 卡面插图（职业图标/角色剪影/技能特效）
│  ║    128×80px          ║  │
│  ║                      ║  │
│  ╚══════════════════════╝  │
│  ┌──────────────────────┐  │
│  │ ◆ 冲锋              │  │  ← 卡牌名称
│  │ 15-25  物 ×1.2      │  │  ← 伤害范围 + 类型 + 倍率
│  │ ─────────────────── │  │  ← 分割线
│  │ 目标: 单体  范围: 1  │  │  ← 目标模式 + 范围
│  │ 消耗: 2AP  职业: 先锋 │  │  ← AP 消耗 + 职业限制
│  └──────────────────────┘  │
│  [稀有度边框发光]          │  ← basic=无光, elite=金色光效
└────────────────────────────┘
```

### 3.2 卡牌尺寸与布局

| 状态 | 尺寸 | 用途 |
|------|------|------|
| 手牌中 | 140×200px | 可点击查看详情 |
| 悬停放大 | 210×300px | 显示完整卡面信息 |
| 打出动画 | 全屏居中 280×400px | 卡牌使用时的特写 |

### 3.3 卡牌 CSS 设计

```css
.combat-card {
  width: 140px;
  height: 200px;
  border-radius: 8px;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
  border: 2px solid #2a3a5e;
  position: relative;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 稀有度边框 */
.combat-card.basic {
  border-color: #3a4a6e;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
}

.combat-card.elite {
  border-color: #c8a840;
  box-shadow: 
    0 0 12px rgba(200, 168, 64, 0.3),
    0 2px 8px rgba(0, 0, 0, 0.4);
}

/* 职业色带（左侧） */
.combat-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
}
.combat-card.class-先锋::before { background: #d4a574; }
.combat-card.class-近卫::before { background: #c44b3c; }
.combat-card.class-重装::before { background: #4a6b8a; }
.combat-card.class-狙击::before { background: #3c8c4a; }
.combat-card.class-术师::before { background: #8b5ca8; }
.combat-card.class-医疗::before { background: #5c9a8b; }
.combat-card.class-辅助::before { background: #c4a83c; }
.combat-card.class-特种::before { background: #6b5c8a; }

/* 悬停效果 */
.combat-card:hover {
  transform: translateY(-8px) scale(1.05);
  z-index: 10;
}

.combat-card.elite:hover {
  box-shadow: 
    0 0 24px rgba(200, 168, 64, 0.5),
    0 8px 24px rgba(0, 0, 0, 0.6);
}

/* 选中效果 */
.combat-card.selected {
  border-color: #ffc840;
  transform: translateY(-12px);
  box-shadow: 
    0 0 20px rgba(255, 200, 64, 0.6),
    0 4px 16px rgba(0, 0, 0, 0.5);
  animation: card-selected-glow 1.5s ease-in-out infinite;
}

@keyframes card-selected-glow {
  0%, 100% { box-shadow: 0 0 20px rgba(255, 200, 64, 0.6), 0 4px 16px rgba(0, 0, 0, 0.5); }
  50% { box-shadow: 0 0 32px rgba(255, 200, 64, 0.8), 0 4px 20px rgba(0, 0, 0, 0.6); }
}

/* 不可用状态 */
.combat-card.disabled {
  opacity: 0.45;
  filter: grayscale(0.6);
  cursor: not-allowed;
}

.combat-card.disabled:hover {
  transform: none;
}
```

### 3.4 卡牌插图区域

```css
.card-art {
  width: 100%;
  height: 100px;
  background-size: cover;
  background-position: center;
  position: relative;
}

/* 卡图上的渐变遮罩（底部延伸到文字区） */
.card-art::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 40px;
  background: linear-gradient(to bottom, transparent, var(--card-bg, #16213e));
}
```

### 3.5 卡面资源

| 资源 | 规格 | 说明 |
|------|------|------|
| 卡图 | 280×200px PNG | 每张卡牌的插图，反映技能效果 |
| 职业图标 | 32×32px SVG | 8 种职业的小图标 |
| 稀有度边框 | CSS | basic/elite 两组样式 |
| 伤害类型图标 | 16×16px SVG | 物/法/治/混 四种小图标 |

### 3.6 手牌区域重新设计

当前手牌是水平滚动的 card list。改为：

```
┌─────────────────────────────────────────────────┐
│  共用 AP: ◆◆◇◇  │  当前角色: 阿米娅  │  结束回合  │  ← 顶栏
├─────────────────────────────────────────────────┤
│     [卡1]  [卡2]  [卡3]  [卡4]  [卡5]  [卡6]   │  ← 手牌（弧形排列）
│        ╱  ╲                                      │
│       ╱    ╲    —— 轻微弧形布局，模拟手持扇面    │
│      ╱      ╲                                    │
└─────────────────────────────────────────────────┘
```

**弧形手牌布局**：使用 CSS transform rotate，中间卡牌角度为 0°，两侧逐渐倾斜 ±3°、±6°，形成扇形展开的效果。

```tsx
function CombatHand({ cards, ... }: Props) {
  const fanAngle = 3; // 每张牌偏移角度
  
  return (
    <div className="hand-fan-container">
      {cards.map((card, i) => {
        const offset = i - (cards.length - 1) / 2;
        const rotation = offset * fanAngle;
        const translateY = Math.abs(offset) * 12; // 两侧略低
        
        return (
          <div
            key={card.card_id}
            className="hand-card-wrapper"
            style={{
              transform: `rotate(${rotation}deg) translateY(${translateY}px)`,
              zIndex: i,
            }}
          >
            <CombatCard card={card} index={i} ... />
          </div>
        );
      })}
    </div>
  );
}
```

---

## 四、单位状态面板

### 4.1 设计概念

从当前纯文字列表升级为角色卡片式面板：

```
┌─────────────────────┐
│  [头像]  阿米娅      │  ← 108×108 头像
│          术师 ★★★★★ │  ← 职业 + 稀有度星标
│  ┌─────────────────┐│
│  │████████░░░ 78% ││  ← HP 条（渐变绿→黄→红）
│  │ 154 / 198      ││  ← 数值
│  └─────────────────┘│
│  AP: ◆◆◇  SP: ◆◆◇◇ │  ← 个人 AP + SP 点数
│  ATK: 28  DEF: 12   │  ← 关键数值
│  [移动] [技能] [等待]│  ← 如果当前回合是该角色
└─────────────────────┘
```

### 4.2 HP 条增强

```css
.hp-bar {
  height: 8px;
  border-radius: 4px;
  background: #1a1a2e;
  border: 1px solid #2a2a3e;
  overflow: hidden;
}

.hp-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.4s ease;
}

.hp-bar-fill.high   { background: linear-gradient(90deg, #2ecc71, #27ae60); }
.hp-bar-fill.medium { background: linear-gradient(90deg, #f39c12, #e67e22); }
.hp-bar-fill.low    { background: linear-gradient(90deg, #e74c3c, #c0392b); animation: hp-pulse 0.8s infinite; }

@keyframes hp-pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.6; }
}
```

### 4.3 布局位置

- **我方状态面板**：左侧垂直排列，每个角色一张卡片
- **敌方状态面板**：右侧垂直排列，简化信息（仅 HP 条 + 名称）
- **当前行动角色**：高亮边框 + 金色脉冲光效

### 4.4 角色头像资源

| 资源 | 规格 | 用途 |
|------|------|------|
| 头像 | 256×256px PNG | 状态面板显示 |
| 头像（小） | 64×64px PNG | 手牌区域上方显示当前角色 |
| 职业底框 | SVG overlay | 根据职业显示不同边框样式 |

---

## 五、战斗事件与特效

### 5.1 伤害数字

参考明日方舟的伤害数字样式：

```css
.damage-number {
  font-family: 'Impact', 'Arial Black', sans-serif;
  font-weight: 900;
  font-size: 28px;
  color: #fff;
  text-shadow:
    -1px -1px 0 #000,
     1px -1px 0 #000,
    -1px  1px 0 #000,
     1px  1px 0 #000,
    0 0 8px rgba(255, 60, 30, 0.8);  /* 红色光晕 */
  animation: damage-float 1s ease-out forwards;
  pointer-events: none;
}

.damage-number.physical { color: #ff6b4a; }
.damage-number.arts     { color: #b44af0; }
.damage-number.heal     { color: #4aff8b; text-shadow: ... green glow; }
.damage-number.crit     { font-size: 38px; color: #ffd700; }

@keyframes damage-float {
  0%   { transform: translateY(0) scale(0.8); opacity: 1; }
  20%  { transform: translateY(-8px) scale(1.1); opacity: 1; }
  100% { transform: translateY(-40px) scale(0.9); opacity: 0; }
}
```

### 5.2 攻击动画序列

```
卡牌打出 → 卡面放大飞出 → 攻击者闪烁 → 弹道/特效飞向目标 → 目标震动 + 伤害数字弹出

时间线:
  0ms    : 卡牌飞入屏幕中央（scale 1.5）
  300ms  : 攻击者高亮闪烁（白色 flash）
  400ms  : 特效粒子沿贝塞尔曲线飞向目标
  600ms  : 目标震动（shake animation）
  700ms  : 伤害数字弹出
  1000ms : 特效消散
```

### 5.3 移动动画

```css
.unit-moving {
  transition: transform 0.3s ease-out;
}

/* 经过的路径单元格短暂高亮 */
.path-cell {
  animation: path-flash 0.5s ease-out;
}

@keyframes path-flash {
  0%   { background: rgba(0, 180, 255, 0.4); }
  100% { background: transparent; }
}
```

### 5.4 战斗事件日志美化

从纯文本列表升级为带图标的 timeline：

```
┌─────────────────────────────────────────┐
│  Round 3 · 我方回合                     │
│  ───────────────────────────────────── │
│  ⚔ 阿米娅 对 整合运动士兵 使用「法术冲击」 │  ← 图标 + 彩色角色名
│    造成 24 点法术伤害                     │
│                                         │
│  🛡 整合运动士兵 攻击 临光                │
│    临光 格挡！伤害减免 8 点               │
│                                         │
│  💀 整合运动术师 被击倒                   │
│  ───────────────────────────────────── │
│  Round 4 · 敌方回合                     │
└─────────────────────────────────────────┘
```

### 5.5 粒子特效系统

使用 Canvas 或 WebGL（PixiJS）叠加层：

```
需要用粒子特效的场景：

1. 卡牌打出 — 金色粒子从卡牌位置爆散
2. 攻击命中 — 根据伤害类型不同颜色的粒子
   - 物理：橙色火花粒子
   - 法术：紫色能量粒子
   - 治疗：绿色光点粒子
3. 角色死亡 — 角色消散粒子
4. 战斗胜利 — 全屏金色粒子庆祝
5. 回合开始 — AP 恢复的蓝色光环
```

**轻量方案**（不用 WebGL）：使用 CSS `@keyframes` + 多个绝对定位的 `<span>` 元素模拟粒子。

---

## 六、整体布局与配色

### 6.1 全局布局

```
┌─────────────────────────────────────────────────────┐
│  ╔══════════════╗                                   │
│  ║  顶部信息栏   ║  Round 3 | 我方回合 | 当前: 阿米娅  │
│  ╚══════════════╝                                   │
├────────┬───────────────────────────────┬────────────┤
│        │                               │            │
│  我方  │                               │  敌方      │
│  状态  │      战斗地图 (俯视视角)        │  状态      │
│  面板  │      9 rows × 8 cols          │  面板      │
│        │      + 单位小人                │            │
│        │      + 特效粒子层              │            │
│        │                               │            │
│        │                               │            │
├────────┴───────────────────────────────┴────────────┤
│  ┌─────────────────────────────────────────────────┐│
│  │              手牌区域（弧形扇形排列）              ││
│  │  [卡1]  [卡2]  [卡3]  [卡4]  [卡5]  [卡6]      ││
│  └─────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────┐│
│  │  共用AP: ◆◆◇◇  │  [结束回合]  [取消]             ││
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

### 6.2 配色方案

基于明日方舟 UI 的配色提取：

| 用途 | 颜色 | Tailwind 参考 |
|------|------|-------------|
| 背景底色 | `#0a0e17` | 最深蓝黑 |
| 面板背景 | `#111827` + 半透明 | gray-900 |
| 边框 | `#1e3a5f` | blue-900 |
| 分割线 | `#2a3a5e` | — |
| 主色调（玩家） | `#00b4d8` | cyan-500 |
| 主色调（敌人） | `#e74c3c` | red-500 |
| 金色高亮 | `#f0c060` | amber-400 |
| 文字（主要） | `#e0e6f0` | gray-200 |
| 文字（次要） | `#6b7c93` | gray-500 |
| AP 点 | `#00d4ff` | cyan-400 |
| HP 满 | `#2ecc71` | green-500 |
| HP 低 | `#e74c3c` | red-500 |
| 卡牌 elite 边框 | `#c8a840` | — |

### 6.3 字体

| 用途 | 字体 | 说明 |
|------|------|------|
| 标题/数字 | `'Orbitron', sans-serif` | 科技感英文字体（回合数、伤害数字） |
| 中文正文 | `'Noto Sans SC', sans-serif` | 思源黑体 |
| 代码/数值 | `'JetBrains Mono', monospace` | AP 数值等 |

Google Fonts 引入：
```html
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&family=Orbitron:wght@500;700;900&display=swap" rel="stylesheet">
```

---

## 七、动画系统

### 7.1 动画清单

| 动画 | 触发条件 | 时长 | 曲线 |
|------|---------|------|------|
| 格子高亮出现 | 选中角色/卡牌 | 200ms | ease-out |
| 角色移动 | 点击移动目标 | 300ms | ease-in-out |
| 卡牌悬停抬起 | hover | 200ms | cubic-bezier |
| 卡牌选中浮起 | click | 200ms | ease-out |
| 卡牌飞出 | 打出卡牌 | 300ms | ease-in |
| 攻击特效飞行 | 卡牌打出后 | 200ms | ease-in |
| 伤害数字弹出 | 伤害结算 | 1000ms | ease-out |
| 角色受击震动 | 受到伤害 | 300ms | ease-in-out |
| 角色死亡消散 | HP=0 | 600ms | ease-in |
| HP 条变化 | 受到伤害/治疗 | 400ms | ease-out |
| 回合切换 | 回合结束 | 300ms | ease-in-out |
| 胜利/失败 overlay | 战斗结束 | 500ms | ease-out |

### 7.2 动画实现技术选型

| 技术 | 用途 |
|------|------|
| CSS transitions | 简单状态切换（悬停、选中） |
| CSS @keyframes | 循环动画（脉冲、呼吸灯） |
| Framer Motion | React 组件进出动画、布局动画 |
| Canvas (PixiJS) | 复杂粒子特效、弹道轨迹 |

### 7.3 Framer Motion 组件示例

```tsx
import { motion, AnimatePresence } from 'framer-motion';

// 卡牌打出动画
<AnimatePresence>
  {playingCard && (
    <motion.div
      className="card-play-overlay"
      initial={{ scale: 0.8, opacity: 0, y: 100 }}
      animate={{ scale: 1.2, opacity: 1, y: 0 }}
      exit={{ scale: 0.5, opacity: 0, y: -200 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
    >
      <CombatCard card={playingCard} />
    </motion.div>
  )}
</AnimatePresence>

// 伤害数字弹出
<motion.span
  className="damage-number"
  initial={{ opacity: 0, y: 10, scale: 0.5 }}
  animate={{ opacity: 1, y: -30, scale: 1 }}
  exit={{ opacity: 0 }}
  transition={{ duration: 0.8, ease: 'easeOut' }}
>
  {damage}
</motion.span>
```

---

## 八、资源管线

### 8.1 资源目录结构

```
frontend/public/assets/combat/
├── chibis/                    # 战斗小人
│   ├── 阿米娅/
│   │   ├── idle.png          # 待机（序列帧合并图 或 单帧）
│   │   ├── attack.png        # 攻击
│   │   ├── hit.png           # 受伤
│   │   ├── move.png          # 移动
│   │   ├── skill.png         # 技能
│   │   └── death.png         # 死亡
│   ├── 银灰/
│   └── ...
├── cards/                     # 卡面插图
│   ├── 先锋/
│   │   ├── 冲锋.png
│   │   ├── 突刺.png
│   │   └── ...
│   ├── 术师/
│   └── ...
├── icons/                     # UI 图标
│   ├── classes/              # 职业图标
│   │   ├── 先锋.svg
│   │   ├── 近卫.svg
│   │   └── ...
│   ├── damage-types/         # 伤害类型图标
│   │   ├── physical.svg
│   │   ├── arts.svg
│   │   ├── healing.svg
│   │   └── mixed.svg
│   └── ui/                   # 通用 UI 图标
├── backgrounds/               # 地图背景
│   ├── urban.png
│   ├── snowfield.png
│   ├── wasteland.png
│   └── indoor.png
├── effects/                   # 特效精灵图
│   ├── hit-spark.png
│   ├── heal-glow.png
│   └── death-dissolve.png
└── avatars/                   # 角色头像
    ├── 阿米娅.png
    ├── 银灰.png
    └── ...
```

### 8.2 资源加载策略

1. **首屏加载**：仅加载 UI 图标（SVG，体积小）和当前角色的 idle sprite
2. **按需加载**：攻击/技能动画在第一次使用时加载
3. **预加载**：在当前回合空闲时预加载下一个可能使用的资源
4. **缓存**：所有战斗资源使用 Service Worker 缓存

### 8.3 开发阶段占位资源

使用程序化生成的占位资源：
- 小人：CSS 像素风色块 + 职业图标组合
- 卡图：渐变色 + 职业图标 + 卡牌名称文字
- 头像：首字大写 + 职业底色（类似 Google 联系人头像）

---

## 九、分阶段实施路线

### Phase 1：基础视觉升级（1-2 周）
- [ ] CSS 配色方案迁移（gray-900 → Arknights 深蓝黑 + 金色）
- [ ] 格子视觉升级（尺寸 40→64px，发光边框，高亮系统）
- [ ] 地图透视（CSS rotateX 俯视效果）
- [ ] 卡牌基础美化（圆角、阴影、悬停效果、职业色带）
- [ ] HP/AP 条视觉升级（渐变、脉冲动画）

### Phase 2：布局与交互（1-2 周）
- [ ] 弧形手牌布局
- [ ] 状态面板重构为角色卡片式
- [ ] 事件日志 timeline 化
- [ ] 伤害数字弹出动画
- [ ] Framer Motion 过渡动画

### Phase 3：角色与卡面（2-3 周）
- [ ] CSS 占位小人实现
- [ ] 角色头像系统（程序化生成）
- [ ] 卡面模板（带卡图区域）
- [ ] 职业图标系统
- [ ] 移动/攻击动画序列

### Phase 4：特效与资源（3-4 周）
- [ ] 粒子特效系统（Canvas 层）
- [ ] 地图背景分层（远景 + 地面纹理）
- [ ] 战斗小人静态 PNG 资源导入
- [ ] 卡面插图资源导入
- [ ] 音效预留接口

### Phase 5：打磨（持续）
- [ ] Spine/序列帧动画支持
- [ ] 全资源管线就绪
- [ ] 性能优化（虚拟化、懒加载）
- [ ] 无障碍支持（键盘导航、屏幕阅读器）

---

## 附录 A：技术栈推荐

| 用途 | 推荐 | 原因 |
|------|------|------|
| 动画框架 | Framer Motion | React 原生支持，API 简洁，布局动画强大 |
| 粒子特效 | 自研 Canvas 层 | 轻量，不引入 WebGL 依赖 |
| 序列帧播放 | 自研 SpritePlayer | 简单可控 |
| 骨骼动画 | PixiJS + pixi-spine | 如需 Spine 支持 |
| 音效 | Howler.js | 轻量，支持音频精灵 |
| SVG 图标 | Lucide React | 图标库，也可用自定义 SVG |

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
  
  /* 透视 */
  --grid-perspective: 1200px;
  --grid-rotate-x: 18deg;
  --cell-size: 64px;
}
```
