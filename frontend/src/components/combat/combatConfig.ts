/**
 * Combat layout configuration.
 *
 * Values can differ between "fullscreen" (maximized) and "windowed" modes.
 * Detection: window.innerHeight >= screen.availHeight - 4 && same for width.
 *
 * Edit this file to tune layout without hunting through components.
 */

export type LayoutMode = "fullscreen" | "windowed";

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

// ── Derived helpers ──
export function getCellSize(mode: LayoutMode): number {
  return config[mode].cellSize;
}

export function getCardSize(mode: LayoutMode): { w: number; h: number } {
  return { w: config[mode].cardWidth, h: config[mode].cardHeight };
}
