/**
 * Combat layout configuration.
 *
 * Values can differ between "fullscreen" (maximized) and "windowed" modes.
 * Detection: window.innerHeight >= screen.availHeight - 4 && same for width.
 *
 * Edit this file to tune layout without hunting through components.
 */

export type LayoutMode = "fullscreen" | "windowed";

export const DMG_LABELS: Record<string, string> = {
  physical: "物理", arts: "法术", healing: "治疗", mixed: "混合",
};

export const DMG_COLORS: Record<string, string> = {
  physical: "text-dmg-physical", arts: "text-dmg-arts",
  healing: "text-dmg-healing", mixed: "text-dmg-mixed",
};

// ── Per-mode overrides ──
// Any key can be overridden per mode.  "base" is the fallback.
const config: Record<LayoutMode, Record<string, number>> = {
  fullscreen: {
    cellSize: 72,
    gridMarginTop: 80,
    cardWidth: 192,
    cardHeight: 259,
    handFanMarginTop: -36,
    bottomBarMarginTop: -72,
    // 敌方小人缩放系数（相对我方统一比例）。我方与敌方共用同一美术尺度，
    // 但敌方模型（士兵/术师/兽类）本体比干员矮约 13%，故取 0.9 使
    // 「敌方比我方略小」的观感与逐角色归一化时代保持一致。等比缩放，不改宽高比。
    enemySpineScale: 0.9,
  },
  windowed: {
    cellSize: 56,
    gridMarginTop: 24,
    cardWidth: 122,
    cardHeight: 166,
    handFanMarginTop: -24,
    bottomBarMarginTop: -48,
    enemySpineScale: 0.9,
  },
};

export function getCombatConfig(mode: LayoutMode) {
  return config[mode];
}

// ── 手牌快捷键 ──
//
// 手牌可达 6 张以上（共享手牌 6 张 + 角色保底补牌），因此快捷键不能只覆盖 1–5：
// 1–9 对应第 1–9 张，0 对应第 10 张，超出该范围的第 11 张起不再绑定（改用鼠标）。
export const MAX_CARD_SHORTCUTS = 10;

/** 第 index 张（0 基）手牌的按键标签；超出可绑定范围返回 null。 */
export function cardShortcutLabel(index: number): string | null {
  if (index < 0 || index >= MAX_CARD_SHORTCUTS) return null;
  return index === 9 ? "0" : String(index + 1);
}

/** 按键 → 手牌下标（0 基）；不是快捷键返回 -1。 */
export function shortcutKeyToIndex(key: string): number {
  if (key.length !== 1) return -1;
  if (key >= "1" && key <= "9") return key.charCodeAt(0) - 49; // "1" → 0
  if (key === "0") return 9;
  return -1;
}

