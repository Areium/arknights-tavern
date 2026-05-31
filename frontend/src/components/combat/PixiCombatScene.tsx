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
import { Application, Container, Graphics, Text, Texture } from "pixi.js";
import { AtlasAttachmentLoader, SkeletonBinary, Spine } from "@pixi-spine/runtime-3.8";
import { TextureAtlas } from "@pixi-spine/base";
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
  /** Grid cell size in px (used to compute spine scale). */
  cellSize?: number;
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
  yAnchorOffset: number;
}

/** Compute the y-offset so a display object's origin maps to the cell center
 *  with a 1/4 cell downward nudge, plus 1 cell offset to align with grid. */
function calcYOffset(renderHeight: number, cellSize: number): number {
  return -renderHeight * 0.5 + cellSize * 1.0;
}

/** Load a Spine 3.8 character from .atlas + .skel files. */
async function loadSpine(baseUrl: string, fn: string): Promise<Spine> {
  const atlasUrl = `${baseUrl}/${fn}.atlas`;
  const skelUrl = `${baseUrl}/${fn}.skel`;

  const [atlasText, skelBuffer] = await Promise.all([
    fetch(atlasUrl).then((r) => r.text()),
    fetch(skelUrl).then((r) => r.arrayBuffer()),
  ]);

  return new Promise((resolve, reject) => {
    new TextureAtlas(
      atlasText,
      (path, loaderFn) => {
        const imgUrl = `${baseUrl}/${path}`;
        Texture.fromURL(imgUrl).then((tex) => {
          loaderFn(tex.baseTexture);
        }).catch((e) => {
          console.error(`[loadSpine] Texture load error for ${path}:`, e);
          loaderFn(null as any);
        });
      },
      (atlas) => {
        if (!atlas) { console.error(`[loadSpine] TextureAtlas callback got null`); reject(new Error("TextureAtlas returned null")); return; }
        try {
          const al = new AtlasAttachmentLoader(atlas);
          const skeletonData = new SkeletonBinary(al).readSkeletonData(new Uint8Array(skelBuffer));
          const spine = new Spine(skeletonData);
          resolve(spine);
        } catch (e) {
          console.error(`[loadSpine] Parse/Skeleton error:`, e);
          reject(e);
        }
      },
    );
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PixiCombatScene({ units, gridEl, containerEl, resizeTick, cellSize = 64 }: PixiCombatSceneProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const appRef = useRef<Application | null>(null);
  const unitLayerRef = useRef<Container | null>(null);
  const unitMapRef = useRef<Map<string, UnitEntry>>(new Map());
  const loadedRef = useRef<Set<string>>(new Set());
  const loadingRef = useRef<Map<string, Promise<Spine | void>>>(new Map());
  const loadingUnitsRef = useRef<Set<string>>(new Set());
  const [ready, setReady] = useState(false);
  const [gridReady, setGridReady] = useState(false);
  const [posTick, setPosTick] = useState(0);
  const initialPosDoneRef = useRef(false);
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

  // Keep a ref to the latest syncCanvasSize so the init effect can call it
  const syncCanvasSizeRef = useRef(syncCanvasSize);
  syncCanvasSizeRef.current = syncCanvasSize;

  // ── Compute a unit's screen position relative to the canvas ─────────
  const getCanvasPos = useCallback((row: number, col: number): [number, number] | null => {
    if (!gridEl || !containerEl) return null;
    const screen = getCellCenter(gridEl, row, col);
    if (!screen) return null;
    const cr = containerEl.getBoundingClientRect();
    return [screen.x - cr.left, screen.y - cr.top];
  }, [gridEl, containerEl]);

  // Keep a ref to latest getCanvasPos so async callbacks always use current positions
  const getCanvasPosRef = useRef(getCanvasPos);
  getCanvasPosRef.current = getCanvasPos;

  // ── Init / destroy PixiJS app ──────────────────────────────────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const { w, h } = canvasSizeRef.current;

    const app = new Application({
      width: w, height: h,
      backgroundAlpha: 0,
      antialias: true,
      resolution: window.devicePixelRatio || 1,
      autoDensity: true,
    });

    const canvas = app.view as HTMLCanvasElement;
    canvas.style.background = "transparent";
    canvas.style.pointerEvents = "none";
    container.appendChild(canvas);
    appRef.current = app;

    const unitLayer = new Container();
    unitLayer.sortableChildren = true;
    app.stage.addChild(unitLayer);
    unitLayerRef.current = unitLayer;
    setReady(true);
    // Sync canvas size now that the renderer is initialized
    syncCanvasSizeRef.current();

    return () => {
      app.destroy(true);
      appRef.current = null;
      unitLayerRef.current = null;
      unitMapRef.current.clear();
      loadedRef.current.clear();
      loadingRef.current.clear();
      loadingUnitsRef.current.clear();
      initialPosDoneRef.current = false;
      setReady(false);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Wait for CSS 3D layout to settle before computing positions ─────
  // Double rAF ensures both layout AND compositing of the 3D perspective are complete.
  useEffect(() => {
    if (gridEl && containerEl) {
      let cancelled = false;
      requestAnimationFrame(() => {
        if (cancelled) return;
        const firstCell = getCellCenter(gridEl, 0, 0);
        if (firstCell && firstCell.x > 0 && firstCell.y > 0) {
          requestAnimationFrame(() => {
            if (!cancelled) {
              setGridReady(true);
            }
          });
        } else {
          requestAnimationFrame(() => {
            if (!cancelled) {
              setGridReady(true);
            }
          });
        }
      });
      return () => { cancelled = true; };
    } else {
      setGridReady(false);
      initialPosDoneRef.current = false;
    }
  }, [gridEl, containerEl]);

  // ── Resize canvas when container size changes ──────────────────────
  useEffect(() => {
    if (!ready) return;
    syncCanvasSize();
    const onResize = () => syncCanvasSize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [syncCanvasSize, ready]);

  // ── Unit management ───────────────────────────────────────────────
  useEffect(() => {
    if (!ready || !gridReady) return;
    const ul = unitLayerRef.current;
    if (!ul) return;

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
      const zIndex = u.pos[0]; // higher row = closer to camera = render on top

      if (exists) {
        exists.cell = [u.pos[0], u.pos[1]];
        exists.displayObject.x = sx;
        exists.displayObject.y = sy + exists.yAnchorOffset;
        if (exists.displayObject.zIndex !== zIndex) {
          exists.displayObject.zIndex = zIndex;
        }
      } else if (hasSpine(u.name)) {
        // Guard: skip if this unit is already being loaded (prevents duplicate on re-render)
        if (loadingUnitsRef.current.has(u.unit_id)) continue;
        loadingUnitsRef.current.add(u.unit_id);

        const dir: "Front" | "Back" = u.team === "player" ? "Front" : "Back";
        const baseUrl = spineAssetUrl(u.name, dir);
        const fn = spineFileName(u.name);
        const cacheKey = `${fn}_${dir}`;

        (async () => {
          try {
            let spine: Spine;
            if (loadedRef.current.has(cacheKey)) {
              const pending = loadingRef.current.get(cacheKey);
              spine = (pending ? await pending : null) as Spine;
            } else {
              const p = loadSpine(baseUrl, fn);
              loadingRef.current.set(cacheKey, p);
              spine = await p;
              loadedRef.current.add(cacheKey);
            }
            if (!aliveIds.has(u.unit_id)) { loadingUnitsRef.current.delete(u.unit_id); return; }
            if (!spine) { loadingUnitsRef.current.delete(u.unit_id); return; }

            // Re-compute position from DOM now that Spine is ready (layout has settled)
            const latestPos = getCanvasPosRef.current(u.pos[0], u.pos[1]);
            const finalSx = latestPos?.[0] ?? sx;
            const finalSy = latestPos?.[1] ?? sy;
            const rawHeight = spine.spineData.height || cellSize;
            const scale = (cellSize * 1.6) / rawHeight;
            const renderHeight = rawHeight * scale;
            const yOff = calcYOffset(renderHeight, cellSize);
            spine.zIndex = zIndex;
            spine.x = finalSx;
            spine.y = finalSy + yOff;
            const animNames = spine.spineData.animations.map((a: any) => a.name);
            const idleAnim = animNames.find((n: string) => /idle|relax|normal/i.test(n)) || animNames[0];
            spine.state.setAnimation(0, idleAnim, true);
            if (u.team === "enemy") { spine.scale.set(-scale, scale); }
            else { spine.scale.set(scale); }

            ul.addChild(spine);
            map.set(u.unit_id, { displayObject: spine, cell: [u.pos[0], u.pos[1]], yAnchorOffset: yOff });
            loadingUnitsRef.current.delete(u.unit_id);
            setPosTick((t) => t + 1);
          } catch (err) {
            console.error(`[PixiCombatScene] Spine load failed for ${u.name}:`, err);
            if (err instanceof Error) {
              console.error(`[PixiCombatScene]   message: ${err.message}`);
              console.error(`[PixiCombatScene]   stack:`, err.stack);
            }
            const fb = makeFallback(u, sx, sy);
            fb.zIndex = zIndex;
            ul.addChild(fb);
            map.set(u.unit_id, { displayObject: fb, cell: [u.pos[0], u.pos[1]], yAnchorOffset: 0 });
            loadingUnitsRef.current.delete(u.unit_id);
            setPosTick((t) => t + 1);
          }
        })();
      } else {
        const fb = makeFallback(u, sx, sy);
        fb.zIndex = zIndex;
        ul.addChild(fb);
        map.set(u.unit_id, { displayObject: fb, cell: [u.pos[0], u.pos[1]], yAnchorOffset: 0 });
      }
    }

    ul.sortChildren();

    // On first layout, re-check positions after browser fully settles CSS 3D transforms
    if (!initialPosDoneRef.current && alive.length > 0) {
      initialPosDoneRef.current = true;
      requestAnimationFrame(() => {
        setPosTick((t) => t + 1);
      });
    }
  }, [ready, units, getCanvasPos, gridReady, posTick]);

  // ── Reposition units on resize ─────────────────────────────────────
  useEffect(() => {
    if (!ready || !gridReady) return;
    const map = unitMapRef.current;
    for (const [, entry] of map) {
      const pos = getCanvasPos(entry.cell[0], entry.cell[1]);
      if (pos) {
        entry.displayObject.x = pos[0];
        entry.displayObject.y = pos[1] + entry.yAnchorOffset;
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
  g.beginFill(color);
  g.drawCircle(0, 0, 10);
  g.endFill();
  c.addChild(g);

  const t = new Text(unit.name.slice(0, 3), {
    fontSize: 10, fill: 0xffffff, fontFamily: "sans-serif",
  });
  t.anchor.set(0.5, -1.2);
  c.addChild(t);

  return c;
}
