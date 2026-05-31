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
  },
  windowed: {
    cellSize: 56,
    gridMarginTop: 24,
    cardWidth: 122,
    cardHeight: 166,
    handFanMarginTop: -24,
    bottomBarMarginTop: -48,
  },
};

export function getCombatConfig(mode: LayoutMode) {
  return config[mode];
}

