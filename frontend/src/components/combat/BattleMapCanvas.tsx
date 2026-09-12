import { useMemo } from "react";
import type { TileTypeDTO } from "../../types";

export type MapEditMode = "tile" | "deploy-player" | "deploy-enemy";

interface Props {
  rows: number;
  cols: number;
  /** 已归一的二维 tile_id（父组件负责把字符串简写展开） */
  tiles: string[][];
  tileDefs: Record<string, Partial<TileTypeDTO>>;
  deploy: { player: [number, number][]; enemy: [number, number][] };
  mode: MapEditMode;
  /** 当前笔刷 tile_id（tile 模式） */
  brush: string;
  onPaint: (row: number, col: number) => void;
  /** 站位摆放模式下的可选高亮（如部署区） */
  highlight?: Set<string>;
  onCellClick?: (row: number, col: number) => void;
  cellSize?: number;
}

function colorOf(def: Partial<TileTypeDTO> | undefined, fallback = "#374151"): string {
  return def?.color || fallback;
}

export default function BattleMapCanvas({
  rows, cols, tiles, tileDefs, deploy, mode, brush, onPaint,
  highlight, onCellClick, cellSize = 30,
}: Props) {
  const deployKeys = useMemo(() => {
    const player = new Set(deploy.player.map(([r, c]) => `${r},${c}`));
    const enemy = new Set(deploy.enemy.map(([r, c]) => `${r},${c}`));
    return { player, enemy };
  }, [deploy]);

  const handle = (r: number, c: number) => {
    if (mode === "tile") {
      onPaint(r, c);
    } else {
      onPaint(r, c);            // 部署区涂改
    }
    onCellClick?.(r, c);
  };

  return (
    <div className="inline-block select-none" data-map-canvas>
      <div className="flex gap-0.5 mb-0.5">
        <div style={{ width: 16 }} />
        {Array.from({ length: cols }, (_, c) => (
          <div key={c} className="text-center text-[9px] text-gray-600 font-mono"
               style={{ width: cellSize }}>{c}</div>
        ))}
      </div>
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex gap-0.5 items-center">
          <div className="text-center text-[9px] text-gray-600 font-mono"
               style={{ width: 16 }}>{r}</div>
          {Array.from({ length: cols }, (_, c) => {
            const key = `${r},${c}`;
            const tileId = tiles[r]?.[c] ?? "ground";
            const def = tileDefs[tileId];
            const isBrush = mode === "tile" && tileId === brush;
            const inDeploy = deployKeys.player.has(key) ? "player"
              : deployKeys.enemy.has(key) ? "enemy" : "";
            const hl = highlight?.has(key);
            return (
              <button
                key={key}
                onMouseDown={(e) => { e.preventDefault(); handle(r, c); }}
                onMouseEnter={(e) => { if (e.buttons === 1) handle(r, c); }}
                title={`${tileId}${def?.name ? ` · ${def.name}` : ""}${inDeploy ? ` · ${inDeploy} 部署区` : ""}`}
                className={
                  "border rounded-[3px] flex items-center justify-center transition-colors "
                  + (hl ? "ring-2 ring-amber-400/70 " : "")
                  + (inDeploy === "player" ? "ring-1 ring-cyan-500/60 "
                    : inDeploy === "enemy" ? "ring-1 ring-red-500/60 " : "")
                  + (isBrush ? "outline outline-1 outline-amber-500/40 " : "")
                }
                style={{
                  width: cellSize, height: cellSize,
                  backgroundColor: `${colorOf(def)}${tileId === "ground" ? "33" : "cc"}`,
                  borderColor: `${colorOf(def)}aa`,
                }}
              >
                <span className="text-[9px] opacity-70">
                  {tileId === "ground" ? "" : (def?.glyph ?? "")}
                </span>
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
