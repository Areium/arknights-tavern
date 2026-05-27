/**
 * PixiJS transparent overlay — renders Spine-animated characters on top of
 * the CSS combat grid.  The canvas sits flat (no CSS 3D transform) while
 * character positions are computed via DOM `getBoundingClientRect`, which
 * naturally accounts for the grid's CSS 3D perspective tilt.
 *
 * This component does NOT render cells, highlights, labels, or handle
 * interaction.  Those are handled by the CSS-based CombatGrid.
 */
import { useEffect, useRef, useState, useCallback } from "react";
import { Application, Container, Graphics, Text, Assets } from "pixi.js";
import { Spine } from "@esotericsoftware/spine-pixi-v8";
import type { CombatUnitDTO } from "../../types";
import { getCellCenter } from "./gridUtils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SPINE_VARIANT: Record<string, string> = {
  "临光": "char_148_nearl",
  "佐菲娅": "char_265_sophia",
  "德克萨斯": "char_1028_texas2",
  "玛恩纳·临光": "char_4064_mlynar",
  "瑕光": "char_423_blemsh",
  "砾": "char_237_gravel",
  "银灰": "char_172_svrash_ambienceSynesthesia_4",
  "闪灵": "char_147_shining",
  "阿米娅": "char_002_amiya_epoque_4",
  "陈": "char_010_chen",
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PixiCombatSceneProps {
  units: CombatUnitDTO[];
  /** The CSS grid's root DOM element (for computing cell screen positions). */
  gridEl: HTMLElement | null;
  /** The container element whose top-left corner serves as the coordinate origin. */
  containerEl: HTMLElement | null;
  /** Incremented on resize to trigger repositioning. */
  resizeTick: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function hasSpine(name: string): boolean { return name in SPINE_VARIANT; }
function spineFileName(name: string): string { return SPINE_VARIANT[name]; }
function spineAssetUrl(name: string, dir: "Front" | "Back"): string {
  return `/api/assets/characters/${encodeURIComponent(name)}/spine/${SPINE_VARIANT[name]}/${dir}`;
}

interface UnitEntry {
  displayObject: Container;
  cell: [number, number];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PixiCombatScene({ units, gridEl, containerEl, resizeTick }: PixiCombatSceneProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const appRef = useRef<Application | null>(null);
  const unitLayerRef = useRef<Container | null>(null);
  const unitMapRef = useRef<Map<string, UnitEntry>>(new Map());
  const loadedRef = useRef<Set<string>>(new Set());
  const loadingRef = useRef<Map<string, Promise<void>>>(new Map());
  const [ready, setReady] = useState(false);
  const canvasSizeRef = useRef({ w: 800, h: 600 });

  // ── Compute canvas size from container ────────────────────────────
  const syncCanvasSize = useCallback(() => {
    if (!containerEl) return;
    const rect = containerEl.getBoundingClientRect();
    const w = Math.max(rect.width, 100);
    const h = Math.max(rect.height, 100);
    canvasSizeRef.current = { w, h };
    appRef.current?.renderer.resize(w, h);
  }, [containerEl]);

  // ── Compute a unit's screen position relative to the canvas ─────────
  const getCanvasPos = useCallback((row: number, col: number): [number, number] | null => {
    if (!gridEl || !containerEl) return null;
    const screen = getCellCenter(gridEl, row, col);
    if (!screen) return null;
    const cr = containerEl.getBoundingClientRect();
    return [screen.x - cr.left, screen.y - cr.top];
  }, [gridEl, containerEl]);

  // ── Init / destroy PixiJS app ──────────────────────────────────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let disposed = false;
    const { w, h } = canvasSizeRef.current;

    (async () => {
      const app = new Application();
      await app.init({
        width: w, height: h,
        backgroundAlpha: 0,
        antialias: true,
        resolution: window.devicePixelRatio || 1,
        autoDensity: true,
      });
      if (disposed) { app.destroy(true); return; }

      app.canvas.style.background = "transparent";
      app.canvas.style.pointerEvents = "none";
      container.appendChild(app.canvas);
      appRef.current = app;

      const unitLayer = new Container();
      app.stage.addChild(unitLayer);
      unitLayerRef.current = unitLayer;
      setReady(true);
    })();

    return () => {
      disposed = true;
      appRef.current?.destroy(true);
      appRef.current = null;
      unitLayerRef.current = null;
      unitMapRef.current.clear();
      loadedRef.current.clear();
      loadingRef.current.clear();
      setReady(false);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Resize canvas when container size changes ──────────────────────
  useEffect(() => {
    syncCanvasSize();
    const onResize = () => syncCanvasSize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [syncCanvasSize]);

  // ── Unit management ───────────────────────────────────────────────
  useEffect(() => {
    if (!ready) return;
    const ul = unitLayerRef.current;
    if (!ul || !gridEl || !containerEl) return;

    const alive = units.filter((u) => u.is_alive);
    const aliveIds = new Set(alive.map((u) => u.unit_id));
    const map = unitMapRef.current;

    // Remove departed
    for (const [id, entry] of map) {
      if (!aliveIds.has(id)) {
        ul.removeChild(entry.displayObject);
        entry.displayObject.destroy({ children: true });
        map.delete(id);
      }
    }

    // Add / update
    for (const u of alive) {
      const exists = map.get(u.unit_id);
      const pos = getCanvasPos(u.pos[0], u.pos[1]);
      const sx = pos?.[0] ?? 0;
      const sy = pos?.[1] ?? 0;

      if (exists) {
        exists.cell = [u.pos[0], u.pos[1]];
        exists.displayObject.x = sx;
        exists.displayObject.y = sy;
      } else if (hasSpine(u.name)) {
        const dir: "Front" | "Back" = u.team === "player" ? "Front" : "Back";
        const baseUrl = spineAssetUrl(u.name, dir);
        const fn = spineFileName(u.name);
        const skelAlias = `spine_skel_${fn}_${dir}`;
        const atlasAlias = `spine_atlas_${fn}_${dir}`;

        (async () => {
          try {
            if (!loadedRef.current.has(skelAlias)) {
              const pending = loadingRef.current.get(skelAlias);
              if (pending) { await pending; }
              else {
                const p = (async () => {
                  Assets.add({ alias: skelAlias, src: `${baseUrl}/${fn}.skel` });
                  Assets.add({ alias: atlasAlias, src: `${baseUrl}/${fn}.atlas` });
                  await Assets.load([skelAlias, atlasAlias]);
                  loadedRef.current.add(skelAlias);
                })();
                loadingRef.current.set(skelAlias, p);
                await p;
              }
            }
            if (!aliveIds.has(u.unit_id)) return;

            const opts = Spine.createOptions({ skeleton: skelAlias, atlas: atlasAlias, autoUpdate: true });
            const spine = new Spine(opts);
            spine.x = sx;
            spine.y = sy;
            spine.state.setAnimation(0, "idle", true);
            if (u.team === "enemy") spine.scale.x = -1;

            ul.addChild(spine);
            map.set(u.unit_id, { displayObject: spine, cell: [u.pos[0], u.pos[1]] });
          } catch (err) {
            console.error(`[PixiCombatScene] Spine load failed for ${u.name}:`, err);
            const fb = makeFallback(u, sx, sy);
            ul.addChild(fb);
            map.set(u.unit_id, { displayObject: fb, cell: [u.pos[0], u.pos[1]] });
          }
        })();
      } else {
        const fb = makeFallback(u, sx, sy);
        ul.addChild(fb);
        map.set(u.unit_id, { displayObject: fb, cell: [u.pos[0], u.pos[1]] });
      }
    }
  }, [ready, units, getCanvasPos, gridEl, containerEl]);

  // ── Reposition units on resize ─────────────────────────────────────
  useEffect(() => {
    if (!ready) return;
    const map = unitMapRef.current;
    for (const [, entry] of map) {
      const pos = getCanvasPos(entry.cell[0], entry.cell[1]);
      if (pos) {
        entry.displayObject.x = pos[0];
        entry.displayObject.y = pos[1];
      }
    }
  }, [ready, getCanvasPos, resizeTick]);

  // ── Render ─────────────────────────────────────────────────────────
  return (
    <div
      ref={containerRef}
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: "100%",
        height: "100%",
        pointerEvents: "none",
        zIndex: 1,
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// Fallback unit (no Spine data)
// ---------------------------------------------------------------------------

function makeFallback(unit: CombatUnitDTO, sx: number, sy: number): Container {
  const c = new Container();
  c.x = sx;
  c.y = sy;

  const g = new Graphics();
  const color = unit.team === "player" ? 0x4488cc : 0xcc4444;
  g.circle(0, 0, 10);
  g.fill({ color });
  c.addChild(g);

  const t = new Text({
    text: unit.name.slice(0, 3),
    style: { fontSize: 10, fill: 0xffffff, fontFamily: "sans-serif" },
  });
  t.anchor.set(0.5, -1.2);
  c.addChild(t);

  return c;
}
