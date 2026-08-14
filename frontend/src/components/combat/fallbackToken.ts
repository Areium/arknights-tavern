/**
 * 无 Spine 骨骼数据单位的「职业令牌」渲染（fallback token v2）。
 *
 * 由 PixiCombatScene 在 hasSpine() 为 false（或 Spine 加载失败）时创建，替代旧版 10px 圆点：
 *   - 队伍色圆环（玩家青 / 敌方红）+ 半透明深色底座，尺寸随 cellSize 缩放（直径 ≈ cellSize * 0.72）
 *   - 异步尝试加载角色头像（同源 /api 资源），成功后经 Graphics 圆形蒙版裁剪嵌入令牌
 *   - 加载失败（敌人无该资源会 404/onerror）→ 显示职业徽章：职业色填充 + 职业首字
 *   - 令牌上方名字（白字描边）、下方 HP 条（红底绿条，宽度 = 直径 × hp/max_hp）
 */
import { Container, Graphics, Sprite, Text, Texture } from "pixi.js";
import type { CombatUnitDTO } from "../../types";

// ---------------------------------------------------------------------------
// 配色
// ---------------------------------------------------------------------------

/** 队伍色环：玩家青 / 敌方红 */
const TEAM_RING: Record<"player" | "enemy", number> = { player: 0x35c0e6, enemy: 0xe74c3c };

/** 职业徽章配色（char_class → 填充色） */
const CLASS_BADGE: Record<string, number> = {
  "近卫": 0xc44b3c,
  "狙击": 0x3c8c4a,
  "术师": 0x8b5ca8,
  "医疗": 0x5c9a8b,
  "重装": 0x4a6b8a,
  "先锋": 0xd4a574,
  "辅助": 0xc4a83c,
  "特种": 0x6b5c8a,
};

/** 未知职业兜底色 */
const CLASS_BADGE_FALLBACK = 0x5a6472;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FallbackToken {
  /** 令牌根容器（锚点 = 格子中心 (sx, sy)） */
  container: Container;
  /** HP 条绿色前景：几何自左缘起画满宽，运行时以 scale.x = hp/max_hp 控制宽度（左锚定消耗） */
  hpBar: Graphics;
  /** HP 条满宽（px），供外部按比例更新宽度 */
  hpWidth: number;
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function makeFallbackToken(
  unit: CombatUnitDTO,
  sx: number,
  sy: number,
  cellSize: number,
): FallbackToken {
  const c = new Container();
  c.x = sx;
  c.y = sy;

  // ── 底座：半透明深色圆 + 队伍色圆环 ──
  const R = cellSize * 0.36; // 令牌半径（直径 ≈ cellSize * 0.72）
  const ringW = Math.max(2, cellSize * 0.055);
  const innerR = R - ringW * 0.5; // 环内侧可视半径（头像/徽章按此尺寸裁剪）

  const base = new Graphics();
  base.beginFill(0x141a24, 0.72);
  base.drawCircle(0, 0, R);
  base.endFill();
  base.lineStyle(ringW, TEAM_RING[unit.team], 1);
  base.drawCircle(0, 0, R);
  c.addChild(base);

  // ── 职业徽章：职业色填充 + 职业首字（默认呈现，头像加载成功后被覆盖）──
  const badge = new Container();
  const badgeBg = new Graphics();
  badgeBg.beginFill(CLASS_BADGE[unit.char_class] ?? CLASS_BADGE_FALLBACK, 1);
  badgeBg.drawCircle(0, 0, innerR);
  badgeBg.endFill();
  badge.addChild(badgeBg);

  const classChar = (unit.char_class ?? "").trim().charAt(0) || "?";
  const badgeText = new Text(classChar, {
    fontSize: Math.round(cellSize * 0.32),
    fontWeight: "bold",
    fill: 0xffffff,
    fontFamily: "sans-serif",
    stroke: 0x141a24,
    strokeThickness: Math.max(1, cellSize * 0.03),
  });
  badgeText.anchor.set(0.5);
  badge.addChild(badgeText);
  c.addChild(badge);

  // ── 头像槽：异步加载头像，成功后以圆形 Graphics 蒙版裁剪盖在徽章上 ──
  const photoSlot = new Container();
  const circleMask = new Graphics();
  circleMask.beginFill(0xffffff);
  circleMask.drawCircle(0, 0, innerR);
  circleMask.endFill();
  photoSlot.addChild(circleMask);
  photoSlot.mask = circleMask;
  c.addChild(photoSlot);

  // 玩家角色头像为同源 API 资源；敌人通常 404 → catch 兜底保留职业徽章
  const avatarUrl = `/api/characters/${encodeURIComponent(unit.name)}/avatar`;
  Texture.fromURL(avatarUrl)
    .then((tex) => {
      // 加载期间令牌可能已随单位离场被销毁
      if (c.destroyed || photoSlot.destroyed) return;
      const spr = new Sprite(tex);
      spr.anchor.set(0.5);
      // 以短边撑满圆形区域（cover 裁剪）；Math.max 防御异常 0 尺寸纹理
      spr.scale.set((innerR * 2) / Math.max(1, Math.min(tex.width, tex.height)));
      photoSlot.addChild(spr);
    })
    .catch(() => {
      /* 头像不可用（404 等）→ 保留职业徽章 */
    });

  // ── 名字：令牌上方，白字描边，字号按 cellSize 缩放（≈10~11px @64）──
  const name = new Text(unit.name.slice(0, 4), {
    fontSize: Math.max(10, Math.round(cellSize * 0.17)),
    fontWeight: "bold",
    fill: 0xffffff,
    fontFamily: "sans-serif",
    stroke: 0x141a24,
    strokeThickness: Math.max(2, cellSize * 0.045),
  });
  name.anchor.set(0.5, 1);
  name.y = -(R + cellSize * 0.1);
  c.addChild(name);

  // ── HP 条：令牌下方，红底绿条，宽 ≈ 令牌直径，高 4~5px ──
  const barW = R * 2;
  const barH = Math.min(5, Math.max(4, Math.round(cellSize * 0.07)));
  const barY = R + cellSize * 0.1;

  const hpBg = new Graphics();
  hpBg.beginFill(0x8c2f2f, 0.9);
  hpBg.drawRoundedRect(-barW / 2, -barH / 2, barW, barH, barH / 2);
  hpBg.endFill();
  hpBg.y = barY;
  c.addChild(hpBg);

  const hpBar = new Graphics();
  hpBar.beginFill(0x46c46a, 1);
  hpBar.drawRoundedRect(0, -barH / 2, barW, barH, barH / 2);
  hpBar.endFill();
  hpBar.position.set(-barW / 2, barY);
  hpBar.scale.x = unit.max_hp > 0 ? Math.max(0, Math.min(1, unit.hp / unit.max_hp)) : 0;
  c.addChild(hpBar);

  return { container: c, hpBar, hpWidth: barW };
}
