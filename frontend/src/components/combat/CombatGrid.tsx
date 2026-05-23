import React from "react";
import type { CombatUnitDTO } from "../../types";
import GridCell from "./GridCell";

const CELL = 56; // px
const CELL_GAP = 2; // gap-0.5 = 2px

/* ── Grid-to-pixel coordinate helpers (relative to grid inner div) ── */
function cellCenter(row: number, col: number): { x: number; y: number } {
  // x = row-label + col * (cell + gap) + half-cell
  // y = col-label-height + row * (cell + gap) + half-cell
  // col-label row: CELL height + mb-0.5 (2px) = CELL + CELL_GAP
  const colLabelH = CELL + CELL_GAP;
  return {
    x: CELL + col * (CELL + CELL_GAP) + CELL / 2,
    y: colLabelH + row * (CELL + CELL_GAP) + CELL / 2,
  };
}

/* ── Bezier helpers ── */
type Point = { x: number; y: number };

function qBezier(p0: Point, p1: Point, p2: Point, t: number): Point {
  const mt = 1 - t;
  return {
    x: mt * mt * p0.x + 2 * mt * t * p1.x + t * t * p2.x,
    y: mt * mt * p0.y + 2 * mt * t * p1.y + t * t * p2.y,
  };
}

function qBezierTangent(p0: Point, p1: Point, p2: Point, t: number): Point {
  const mt = 1 - t;
  return {
    x: 2 * mt * (p1.x - p0.x) + 2 * t * (p2.x - p1.x),
    y: 2 * mt * (p1.y - p0.y) + 2 * t * (p2.y - p1.y),
  };
}

/* ── Attack arrow: curved arc from source to target ── */
const TRIM_START = 0.18; // hide first 18% of arc
const TRIM_END = 0.82;   // hide last 18% of arc
const ARC_STEPS = 48;     // polyline segments for smooth curve

function AttackArrow({ from, to }: { from: Point; to: Point }) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const len = Math.sqrt(dx * dx + dy * dy);
  if (len < 1) return null;

  // Control point: midpoint + perpendicular offset, always curving upward on screen
  const mx = (from.x + to.x) / 2;
  const my = (from.y + to.y) / 2;
  const arcHeight = Math.max(len * 0.35, 30);
  // Two perpendicular candidates: (-dy, dx) and (dy, -dx)
  // Pick the one with smaller y (more upward on screen)
  const p1y = dx / len;   // y of (-dy, dx) normalized
  const p2y = -dx / len;  // y of (dy, -dx) normalized
  const useFirst = p1y < p2y;
  const perpX = useFirst ? -dy / len : dy / len;
  const perpY = useFirst ? dx / len : -dx / len;
  const cp: Point = {
    x: mx + perpX * arcHeight,
    y: my + perpY * arcHeight,
  };

  // Build polyline from trimStart to trimEnd
  const points: string[] = [];
  for (let i = 0; i <= ARC_STEPS; i++) {
    const t = TRIM_START + (TRIM_END - TRIM_START) * (i / ARC_STEPS);
    const pt = qBezier(from, cp, to, t);
    points.push(`${pt.x},${pt.y}`);
  }

  // Arrowhead at trimEnd
  const tip = qBezier(from, cp, to, TRIM_END);
  const tan = qBezierTangent(from, cp, to, TRIM_END);
  const tLen = Math.sqrt(tan.x * tan.x + tan.y * tan.y);
  if (tLen < 0.001) return null;
  const tux = tan.x / tLen;
  const tuy = tan.y / tLen;

  const headLen = 10;
  const headW = 5;
  const bx = tip.x - tux * headLen;
  const by = tip.y - tuy * headLen;
  const hx = -tuy * headW;
  const hy = tux * headW;

  return (
    <g className="attack-arrow-group">
      <polyline
        points={points.join(" ")}
        fill="none"
        className="attack-arrow-glow"
      />
      <polyline
        points={points.join(" ")}
        fill="none"
        className="attack-arrow-line"
      />
      <polygon
        points={`${tip.x},${tip.y} ${bx + hx},${by + hy} ${bx - hx},${by - hy}`}
        className="attack-arrow-head"
      />
    </g>
  );
}

function findClosestCell(
  clientX: number, clientY: number,
  gridRect: DOMRect, gridSize: number
): [number, number] | null {
  const relX = clientX - gridRect.left;
  const relY = clientY - gridRect.top;
  const col = Math.round((relX - CELL) / (CELL + 2));
  const row = Math.round(relY / (CELL + 2));
  if (row >= 0 && row < gridSize && col >= 0 && col < gridSize) {
    return [row, col];
  }
  return null;
}

interface Props {
  gridSize: number;
  units: CombatUnitDTO[];
  grid: Record<string, string>;
  validTargets: [number, number][];
  validMoves: [number, number][];
  moveHighlights: Set<string>;
  rangeHighlights: Set<string>;
  selectedUnitId: string | null;
  uiMode: string;
  cursor: [number, number] | null;
  dragCell: [number, number] | null;
  arrowFrom: [number, number] | null;
  onCellClick: (row: number, col: number) => void;
  onCellHover?: (unit: CombatUnitDTO, rect: DOMRect) => void;
  onCellLeave?: () => void;
  onCellDrop: (row: number, col: number) => void;
  onGridDragMove: (cell: [number, number] | null) => void;
}

export default function CombatGrid({
  gridSize, units, grid, validTargets, validMoves,
  moveHighlights, rangeHighlights, selectedUnitId, uiMode, cursor,
  dragCell, arrowFrom, onCellClick, onCellHover, onCellLeave, onCellDrop, onGridDragMove,
}: Props) {
  const posToUnit: Record<string, CombatUnitDTO> = {};
  for (const u of units) {
    if (u.is_alive) {
      posToUnit[`${u.pos[0]},${u.pos[1]}`] = u;
    }
  }

  const gridRef = React.useRef<HTMLDivElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (gridRef.current) {
      const cell = findClosestCell(e.clientX, e.clientY, gridRef.current.getBoundingClientRect(), gridSize);
      onGridDragMove(cell);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (gridRef.current) {
      const cell = findClosestCell(e.clientX, e.clientY, gridRef.current.getBoundingClientRect(), gridSize);
      if (cell) onCellDrop(cell[0], cell[1]);
    }
    onGridDragMove(null);
  };

  const handleDragLeave = () => {
    onGridDragMove(null);
  };

  const rows: React.ReactNode[] = [];
  for (let r = 0; r < gridSize; r++) {
    const cells: React.ReactNode[] = [];
    for (let c = 0; c < gridSize; c++) {
      const key = `${r},${c}`;
      const unit = posToUnit[key] || null;
      let highlight: "" | "cursor" | "target" | "move" = "";

      if (dragCell && dragCell[0] === r && dragCell[1] === c) {
        highlight = "target";
      } else if (cursor && cursor[0] === r && cursor[1] === c) {
        highlight = "cursor";
      } else if (uiMode === "TARGETING" && rangeHighlights.has(key)) {
        highlight = "target";
      } else if (uiMode === "VIEWING" && moveHighlights.has(key)) {
        highlight = "move";
      }

      cells.push(
        <GridCell
          key={key}
          row={r}
          col={c}
          unit={unit}
          highlight={highlight}
          onClick={onCellClick}
          onMouseEnter={(e) => {
            if (unit && onCellHover) {
              onCellHover(unit, (e.currentTarget as HTMLElement).getBoundingClientRect());
            }
          }}
          onMouseLeave={onCellLeave}
        />
      );
    }
    rows.push(
      <div key={r} className="flex gap-0.5">
        {cells}
      </div>
    );
  }

  return (
    <div className="combat-grid-perspective">
      <div className="combat-grid-3d">
        <div
          ref={gridRef}
          className="flex flex-col gap-0.5 items-center relative"
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          onDragLeave={handleDragLeave}
        >
          {/* Column labels */}
          <div className="flex gap-0.5 mb-0.5">
            <div style={{ width: CELL }} />
            {Array.from({ length: gridSize }, (_, c) => (
              <div
                key={c}
                className="text-center text-[9px] text-gray-600 font-mono"
                style={{ width: CELL }}
              >
                {c}
              </div>
            ))}
          </div>
          {rows.map((row, i) => (
            <div key={i} className="flex gap-0.5 items-center">
              <div
                className="text-center text-[9px] text-gray-600 font-mono"
                style={{ width: CELL }}
              >
                {i}
              </div>
              {row}
            </div>
          ))}

          {/* Attack arrow overlay during drag */}
          {arrowFrom && dragCell && (
            <svg
              className="absolute inset-0 pointer-events-none"
              style={{ width: "100%", height: "100%", zIndex: 50 }}
            >
              <AttackArrow
                from={cellCenter(arrowFrom[0], arrowFrom[1])}
                to={cellCenter(dragCell[0], dragCell[1])}
              />
            </svg>
          )}
        </div>
      </div>
    </div>
  );
}
