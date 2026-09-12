/**
 * PixiJS transparent overlay — renders Spine-animated characters on top of
 * the CSS combat grid.  The canvas sits flat (no CSS 3D transform) while
 * character positions are computed via DOM `getBoundingClientRect`, which
 * naturally accounts for the grid's CSS 3D perspective tilt.
 *
 * This component does NOT render cells, highlights, labels, or handle
 * interaction.  Those are handled by the CSS-based CombatGrid.
 */
import { useEffect, useRef, useState, useCallback, forwardRef, useImperativeHandle } from "react";
import { Application, Container, Graphics, Text, Texture } from "pixi.js";
import { AtlasAttachmentLoader, SkeletonBinary, Spine } from "@pixi-spine/runtime-3.8";
import { TextureAtlas } from "@pixi-spine/base";
import type { CombatUnitDTO } from "../../types";
import { getCellCenter } from "./gridUtils";
import { resolveAnimSpec, type AnimSpec } from "./spineAnimSpecs";
import { makeFallbackToken } from "./fallbackToken";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// 战斗变体（含 Idle/Attack/Die/Skill 动画）。基础/大厅变体（char_148_nearl 等）
// 只有 Relax/Default，无战斗动画，故切换到这里。
// 玛恩纳·临光用 iteration_3（动画名干净，Skill_1_* 兜底攻击）。
const SPINE_VARIANT: Record<string, string> = {
  "临光": "char_148_nearl_summer_2",
  "佐菲娅": "char_265_sophia_epoque_11",
  "德克萨斯": "char_1028_texas2_epoque_36",
  "玛恩纳·临光": "char_4064_mlynar/char_4064_mlynar_iteration_3",
  "瑕光": "char_423_blemsh/char_423_blemsh_witch_2",
  "砾": "char_237_gravel/char_237_gravel_winter_2",
  "银灰": "char_172_svrash/char_172_svrash_snow_1",
  "闪灵": "char_147_shining/char_147_shining_summer_1",
  "阿米娅": "char_002_amiya/char_002_amiya_test_1",
  "陈": "char_010_chen/char_010_chen_nian_2",
  "灵知": "char_206_gnosis",
  "初雪": "char_174_slbell",
  "崖心": "char_173_slchan",
  "锏": "char_4116_blkkgt",
  // 红松骑士团 / 卡西米尔线（fexli/ArknightsResource main，含 Idle/Attack/Die）
  "焰尾": "char_420_flamtl",
  "灰毫": "char_431_ashlok",
  "野鬃": "char_496_wildmn",
  "远牙": "char_430_fartth",
  "薇薇安娜": "char_4098_vvana",
  // 使徒 / 罗德岛线
  "白金": "char_204_platnm",
  "暴行": "char_230_savage",
  "耶拉": "char_4013_kjera",
  "凯尔希": "char_003_kalts",
};

// 敌人 Spine 变体 — 约定与角色一致：文件放 data/characters/<敌名>/spine/<变体>/Front|Back/，
// 在此注册敌名即可启用；未注册或加载失败的敌人自动回退 fallback token。
// 来源 Ark-Models models_enemies（tools/import_spine.py enemies），均含 Idle/Attack/Die。
const ENEMY_SPINE_VARIANT: Record<string, string> = {
  "整合运动士兵": "enemy_1002_nsabr",
  "整合运动术师": "enemy_1011_wizard",
  "整合运动狙击手": "enemy_1003_ncbow",
  "整合运动盾卫": "enemy_1006_shield",
  "冰原战士": "enemy_1189_krgaxe",
  "冰原猎人": "enemy_1190_krgbow",
  "冰原术师": "enemy_1192_krgscr",
  "冰原狂战士": "enemy_1193_krgbsk",
  "山雪鬼": "enemy_1194_krgmtr",
  "山雪鬼队长": "enemy_1194_krgmtr_2",
  "雪原爪兽": "enemy_1187_krghd",
};

const SPINE_VARIANT_ALL: Record<string, string> = { ...SPINE_VARIANT, ...ENEMY_SPINE_VARIANT };

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
  /** 敌方小人高度缩放系数（相对我方目标高度）。等比缩放，不改素材宽高比。 */
  enemyScale?: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function hasSpine(name: string): boolean { return name in SPINE_VARIANT_ALL; }
function spineFileName(name: string): string {
  // 变体可能是嵌套路径（如 char_4064_mlynar/char_4064_mlynar_iteration_3），文件名取 basename
  return SPINE_VARIANT_ALL[name].split("/").pop()!;
}
function spineAssetUrl(name: string, dir: "Front" | "Back"): string {
  return `/api/assets/characters/${encodeURIComponent(name)}/spine/${SPINE_VARIANT_ALL[name]}/${dir}`;
}

interface UnitEntry {
  displayObject: Container;
  cell: [number, number];
  yAnchorOffset: number;
  /** 是否为 Spine（false = fallback 圆点，动画方法 no-op） */
  isSpine?: boolean;
  spec?: AnimSpec;
  /** 是否正在播死亡动画（销毁前不再 remove） */
  dying?: boolean;
  /** 移动 tween 进行中（防止 resize 重排覆盖） */
  tweening?: boolean;
  baseScale?: number;
  flipped?: boolean;
  killTimeout?: ReturnType<typeof setTimeout>;
  /** fallback 令牌 HP 条（isSpine=false 时存在；scale.x = hp/max_hp 控制宽度） */
  hpBar?: Graphics;
  /** fallback 令牌 HP 条满宽（px），用于按比例更新宽度 */
  hpWidth?: number;
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
          // 兼容「附件存放在命名 skin、defaultSkin 为空」的模型（如 enemy_1011_wizard）：
          // 这类模型 Skeleton.getAttachment() 对每个插槽都返回 null，装配不出任何 sprite，
          // getBounds() 得到 0×0 → 小人完全不显示。此处把首个命名 skin 当作默认皮肤。
          if (!skeletonData.defaultSkin && skeletonData.skins.length > 0) {
            skeletonData.defaultSkin = skeletonData.skins[0];
          }
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

export interface PixiCombatSceneHandle {
  playAttack(unitId: string): void;
  playHit(unitId: string): void;
  playDeath(unitId: string): void;
  playStart(unitId: string): void;
  moveTo(unitId: string, to: [number, number], durationMs?: number): void;
  /**
   * 单位当前的实际渲染包围盒，坐标系与覆盖层容器（= 网格相对容器）一致。
   * 供 UI（如敌方意图徽标）按真实尺寸定位，避免硬编码偏移。
   */
  getUnitRect(unitId: string): { left: number; top: number; width: number; height: number } | null;
}

/** 顺序播放动画链，末段结束回 finalIdle。listener 挂在 entry 上，被新动画中断时自动失效。 */
function playChain(spine: Spine, names: string[], finalIdle: string) {
  if (names.length === 0) return;
  let i = 0;
  const advance = (entry: any) => {
    if (spine.state.tracks[0] !== entry) return; // 已被新动画打断
    i += 1;
    if (i < names.length) {
      const e = spine.state.setAnimation(0, names[i], false);
      if (e) e.listener = { complete: advance };
    } else if (finalIdle) {
      spine.state.setAnimation(0, finalIdle, true);
    }
  };
  const first = spine.state.setAnimation(0, names[0], false);
  if (first) first.listener = { complete: advance };
}

const PixiCombatScene = forwardRef<PixiCombatSceneHandle, PixiCombatSceneProps>(function PixiCombatScene(
  { units, gridEl, containerEl, resizeTick, cellSize = 64, enemyScale = 1 }, ref,
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const appRef = useRef<Application | null>(null);
  const unitLayerRef = useRef<Container | null>(null);
  const unitMapRef = useRef<Map<string, UnitEntry>>(new Map());
  const loadedRef = useRef<Set<string>>(new Set());
  const loadingRef = useRef<Map<string, Promise<Spine | void>>>(new Map());
  const loadingUnitsRef = useRef<Set<string>>(new Set());
  /** 加载失败的资产负缓存（cacheKey）：避免每次重渲染重复请求 404 */
  const failedRef = useRef<Set<string>>(new Set());
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

  // Keep a ref to latest cellSize：动画 handle（deps 为 []）需读取最新值，避免闭包过期
  const cellSizeRef = useRef(cellSize);
  cellSizeRef.current = cellSize;

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
      failedRef.current.clear();
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

    // Remove departed — 尊重 dying（死亡动画播完再销毁，由 playDeath 的 timeout 负责）
    for (const [id, entry] of map) {
      if (!aliveIds.has(id)) {
        if (entry.dying) continue;
        if (entry.killTimeout) clearTimeout(entry.killTimeout);
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
        // fallback 令牌：按最新 hp/max_hp 更新 HP 条宽度（前景几何左锚定，scale.x 即宽度比例）
        if (exists.hpBar && exists.hpWidth) {
          const ratio = u.max_hp > 0 ? Math.max(0, Math.min(1, u.hp / u.max_hp)) : 0;
          exists.hpBar.scale.x = ratio;
        }
        // moveTo tween 进行中跳过位置重排，避免覆盖 tween
        if (!exists.tweening) {
          exists.cell = [u.pos[0], u.pos[1]];
          exists.displayObject.x = sx;
          exists.displayObject.y = sy + exists.yAnchorOffset;
        }
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

        // 曾加载失败的资产（负缓存）直接走 fallback，不再重复请求
        if (failedRef.current.has(cacheKey)) {
          loadingUnitsRef.current.delete(u.unit_id);
          const fb = makeFallbackToken(u, sx, sy, cellSize);
          fb.container.zIndex = zIndex;
          ul.addChild(fb.container);
          map.set(u.unit_id, {
            displayObject: fb.container, cell: [u.pos[0], u.pos[1]], yAnchorOffset: 0,
            isSpine: false, flipped: u.team === "enemy", hpBar: fb.hpBar, hpWidth: fb.hpWidth,
          });
          continue;
        }

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
            // 用实际渲染 bounds 高度归一化，避免不同角色的 spineData.height 不可靠
            // 导致显示大小不一致（如银灰骨骼高度偏小 → scale 过大）。
            // 敌方额外乘以 enemyScale 缩小体积；scale 为等比（x 取负仅做水平镜像），不拉伸。
            const TARGET_H = cellSize * 1.6 * (u.team === "enemy" ? enemyScale : 1);
            let renderHeight = TARGET_H;
            try {
              spine.update(0);
              const bounds = spine.getBounds();
              if (bounds && bounds.height > 0) renderHeight = bounds.height;
            } catch { /* 保持默认 */ }
            const scale = TARGET_H / renderHeight;
            // 实际渲染高度已被 scale 归一化为 TARGET_H，锚点基于它计算
            const yOff = calcYOffset(TARGET_H, cellSize);
            spine.zIndex = zIndex;
            spine.x = finalSx;
            spine.y = finalSy + yOff;
            // 解析动画规格（战斗变体动画名带角色后缀，用前缀匹配）
            const spec = resolveAnimSpec(spine.spineData.animations.map((a: any) => a.name));
            const flipped = u.team === "enemy";
            const startAnim = spec.start ?? spec.idle;
            spine.state.setAnimation(0, startAnim, !spec.start);
            if (spec.start) {
              const e = spine.state.tracks[0];
              if (e) e.listener = { complete: () => spine.state.setAnimation(0, spec.idle, true) };
            }
            if (flipped) { spine.scale.set(-scale, scale); }
            else { spine.scale.set(scale); }

            ul.addChild(spine);
            map.set(u.unit_id, {
              displayObject: spine, cell: [u.pos[0], u.pos[1]], yAnchorOffset: yOff,
              isSpine: true, spec, baseScale: scale, flipped,
            });
            loadingUnitsRef.current.delete(u.unit_id);
            setPosTick((t) => t + 1);
          } catch (err) {
            // 负缓存：失败资产只记一次详细日志，之后直接走 fallback
            if (!failedRef.current.has(cacheKey)) {
              console.error(`[PixiCombatScene] Spine load failed for ${u.name}:`, err);
              if (err instanceof Error) {
                console.error(`[PixiCombatScene]   message: ${err.message}`);
                console.error(`[PixiCombatScene]   stack:`, err.stack);
              }
            }
            failedRef.current.add(cacheKey);
            const fb = makeFallbackToken(u, sx, sy, cellSize);
            fb.container.zIndex = zIndex;
            ul.addChild(fb.container);
            map.set(u.unit_id, {
              displayObject: fb.container, cell: [u.pos[0], u.pos[1]], yAnchorOffset: 0,
              isSpine: false, flipped: u.team === "enemy", hpBar: fb.hpBar, hpWidth: fb.hpWidth,
            });
            loadingUnitsRef.current.delete(u.unit_id);
            setPosTick((t) => t + 1);
          }
        })();
      } else {
        const fb = makeFallbackToken(u, sx, sy, cellSize);
        fb.container.zIndex = zIndex;
        ul.addChild(fb.container);
        map.set(u.unit_id, {
          displayObject: fb.container, cell: [u.pos[0], u.pos[1]], yAnchorOffset: 0,
          isSpine: false, flipped: u.team === "enemy", hpBar: fb.hpBar, hpWidth: fb.hpWidth,
        });
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
  }, [ready, units, getCanvasPos, gridReady, posTick, enemyScale]);

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

  // ── Fallback（非 Spine 令牌）动画辅助 ──────────────────────────────
  // 时间驱动 tween：与 moveTo 同以 app.ticker.lastTime 为基准；ticker 不可用时直接落终态
  const runFallbackTween = (durationMs: number, onUpdate: (t: number) => void, onDone?: () => void) => {
    const ticker = appRef.current?.ticker;
    if (!ticker) { onUpdate(1); onDone?.(); return; }
    const startT = ticker.lastTime;
    const tick = () => {
      const t = Math.min(1, (ticker.lastTime - startT) / durationMs);
      onUpdate(t);
      if (t >= 1) { ticker.remove(tick); onDone?.(); }
    };
    ticker.add(tick);
  };

  // 攻击：向朝向方向快速冲刺（±10~14px 来回，约 200ms）+ scale 1.15 punch
  const fallbackAttack = (entry: UnitEntry) => {
    const obj = entry.displayObject;
    const lunge = Math.min(14, Math.max(10, cellSizeRef.current * 0.2));
    const dir = entry.flipped ? -1 : 1; // 敌方默认镜像朝左
    const baseX = obj.x;
    // moveTo tween 进行中则只做 scale punch，避免两段位移互相覆盖
    const canLunge = !entry.tweening;
    if (canLunge) entry.tweening = true;
    runFallbackTween(200, (t) => {
      if (obj.destroyed) return;
      const k = Math.sin(Math.PI * t); // 0→1→0：冲出再收回
      if (canLunge) obj.x = baseX + dir * lunge * k;
      obj.scale.set(1 + 0.15 * k); // 峰值 1.15
    }, () => {
      if (!obj.destroyed) { obj.x = baseX; obj.scale.set(1); }
      if (canLunge) entry.tweening = false;
    });
  };

  // 受击：tint 闪红（递归给 Graphics/Text 子对象染色，beginFill 颜色可 tint）
  //       + 整体 alpha 闪烁兜底（覆盖头像 Sprite 等不可 tint 部分）+ 小幅衰减抖动
  const fallbackHit = (entry: UnitEntry) => {
    const obj = entry.displayObject;
    const tintTree = (node: Container, tint: number) => {
      for (const child of node.children) {
        if (child instanceof Graphics || child instanceof Text) child.tint = tint;
        else if (child instanceof Container) tintTree(child, tint);
      }
    };
    tintTree(obj, 0xff5a4c);
    obj.alpha = 0.6;
    const baseX = obj.x;
    const amp = Math.max(2, cellSizeRef.current * 0.05);
    runFallbackTween(160, (t) => {
      if (obj.destroyed) return;
      obj.x = baseX + amp * Math.sin(t * Math.PI * 6) * (1 - t); // 快速往返且衰减
    }, () => {
      if (!obj.destroyed) obj.x = baseX;
    });
    setTimeout(() => {
      if (obj.destroyed) return;
      tintTree(obj, 0xffffff);
      obj.alpha = 1;
    }, 120);
  };

  // 死亡：alpha 渐隐 + 下沉（y +10px，约 600ms），随后销毁移除（沿用 killTimeout 模式）
  const fallbackDeath = (unitId: string, entry: UnitEntry) => {
    entry.dying = true;
    const obj = entry.displayObject;
    const baseY = obj.y;
    runFallbackTween(600, (t) => {
      if (obj.destroyed) return;
      obj.alpha = 1 - t;
      obj.y = baseY + 10 * t;
    });
    const ul = unitLayerRef.current;
    if (entry.killTimeout) clearTimeout(entry.killTimeout);
    entry.killTimeout = setTimeout(() => {
      if (ul && ul.children.includes(obj)) ul.removeChild(obj);
      obj.destroy({ children: true });
      unitMapRef.current.delete(unitId);
    }, 650);
  };

  // ── 动画控制（CombatView 通过 ref 驱动） ─────────────────────────
  useImperativeHandle(ref, () => ({
    playAttack(unitId: string) {
      const entry = unitMapRef.current.get(unitId);
      if (!entry || entry.dying) return;
      // 非 Spine 令牌：fallback 冲刺 + scale punch
      if (!entry.isSpine) { fallbackAttack(entry); return; }
      if (!entry.spec) return;
      const spine = entry.displayObject as Spine;
      if (entry.spec.attack.length === 0) {
        // 无攻击动画（理论上 resolveAnimSpec 已兜底到 Skill）→ 仅 scale punch
        this.playHit(unitId);
        return;
      }
      playChain(spine, entry.spec.attack, entry.spec.idle);
    },

    playHit(unitId: string) {
      const entry = unitMapRef.current.get(unitId);
      if (!entry || entry.dying) return;
      // 非 Spine 令牌：tint 闪红 + 抖动
      if (!entry.isSpine) { fallbackHit(entry); return; }
      const spine = entry.displayObject as Spine;
      // tint 闪红（pixi-spine 4.0.6 可能不可用 → try 回退纯 scale punch）
      try { (spine as any).tint = 0xff6666; } catch { /* ignore */ }
      const base = entry.baseScale ?? 1;
      const fx = entry.flipped ? -base : base;
      spine.scale.set(fx * 1.15, base * 1.15);
      setTimeout(() => {
        try { (spine as any).tint = 0xffffff; } catch { /* ignore */ }
        spine.scale.set(fx, base);
      }, 100);
    },

    playDeath(unitId: string) {
      const entry = unitMapRef.current.get(unitId);
      if (!entry || entry.dying) return;
      // 非 Spine 令牌：渐隐下沉后销毁
      if (!entry.isSpine) { fallbackDeath(unitId, entry); return; }
      entry.dying = true;
      const spine = entry.displayObject as Spine;
      const spec = entry.spec!;
      const ul = unitLayerRef.current;
      if (spec.die) {
        playChain(spine, [spec.die], "");
      }
      // Die 播完（约 1.5s）或超时后销毁；同时「Remove departed」已尊重 dying 不再提前移除
      if (entry.killTimeout) clearTimeout(entry.killTimeout);
      entry.killTimeout = setTimeout(() => {
        if (ul && ul.children.includes(spine)) ul.removeChild(spine);
        spine.destroy({ children: true });
        unitMapRef.current.delete(unitId);
      }, 1600);
    },

    playStart(unitId: string) {
      const entry = unitMapRef.current.get(unitId);
      if (!entry || !entry.isSpine || !entry.spec) return;
      const spine = entry.displayObject as Spine;
      const spec = entry.spec;
      if (spec.start) {
        const e = spine.state.setAnimation(0, spec.start, false);
        if (e) e.listener = { complete: () => spine.state.setAnimation(0, spec.idle, true) };
      } else {
        spine.state.setAnimation(0, spec.idle, true);
      }
    },

    moveTo(unitId: string, to: [number, number], durationMs = 300) {
      const entry = unitMapRef.current.get(unitId);
      if (!entry || entry.dying) return;
      const from = getCanvasPosRef.current(entry.cell[0], entry.cell[1]);
      const target = getCanvasPosRef.current(to[0], to[1]);
      if (!from || !target) { entry.cell = to; return; }
      entry.tweening = true;
      const ticker = appRef.current?.ticker;
      if (!ticker) { entry.cell = to; entry.tweening = false; return; }
      const startT = ticker.lastTime;
      const dur = Math.max(50, durationMs);
      const tick = () => {
        const t = Math.min(1, (ticker.lastTime - startT) / dur);
        entry.displayObject.x = from[0] + (target[0] - from[0]) * t;
        entry.displayObject.y = from[1] + (target[1] - from[1]) * t + entry.yAnchorOffset;
        if (t >= 1) {
          entry.cell = to;
          entry.tweening = false;
          ticker.remove(tick);
        }
      };
      ticker.add(tick);
    },

    getUnitRect: (unitId: string) => {
      const entry = unitMapRef.current.get(unitId);
      if (!entry) return null;
      // unitLayer 位于 stage 原点，故 getBounds() 即覆盖层局部坐标
      const b = entry.displayObject.getBounds();
      if (!b || b.width <= 0 || b.height <= 0) return null;
      return { left: b.x, top: b.y, width: b.width, height: b.height };
    },
  }), []);

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
});

export default PixiCombatScene;
