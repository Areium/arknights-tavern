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
    cardHeight: 330,
    handFanMarginTop: -36,
    bottomBarMarginTop: -72,
  },
  windowed: {
    cellSize: 56,
    gridMarginTop: 24,
    cardWidth: 122,
    cardHeight: 235,
    handFanMarginTop: -24,
    bottomBarMarginTop: -48,
  },
};

export function getCombatConfig(mode: LayoutMode) {
  return config[mode];
}

