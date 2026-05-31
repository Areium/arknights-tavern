import React, { useRef, useCallback, useEffect } from "react";
import type { CombatUnitDTO } from "../../types";
import GridCell from "./GridCell";
import { getCellCenter } from "./gridUtils";

/** Find the closest cell by comparing mouse position to precomputed cell screen centers */
function findClosestByCenters(
  clientX: number, clientY: number,
  centers: ({ x: number; y: number } | null)[][],
  gridSize: number,
): [number, number] | null {
  let best: [number, number] | null = null;
  let bestDist = Infinity;
  for (let r = 0; r < gridSize; r++) {
    const row = centers[r];
    if (!row) continue;
    for (let c = 0; c < gridSize; c++) {
      const pt = row[c];
      if (!pt) continue;
      const dx = clientX - pt.x;
      const dy = clientY - pt.y;
      const dist = dx * dx + dy * dy;
      if (dist < bestDist) {
        bestDist = dist;
        best = [r, c];
      }
    }
  }
  return best;
}

interface Props {
  gridSize: number;
  cellSize?: number;
  units: CombatUnitDTO[];
  moveHighlights: Set<string>;
  rangeHighlights: Set<string>;
  aoeHighlights?: Set<string>;
  selectedUnitId: string | null;
  uiMode: string;
  cursor: [number, number] | null;
  dragCell: [number, number] | null;
  onCellClick: (row: number, col: number) => void;
  onCellHover?: (unit: CombatUnitDTO, rect: DOMRect) => void;
  onCellLeave?: () => void;
  onCellHoverCell?: (cell: [number, number] | null) => void;
  onCellDrop: (row: number, col: number) => void;
  onGridDragMove: (cell: [number, number] | null, clientX?: number, clientY?: number) => void;
  onGridMount?: (el: HTMLDivElement) => void;
  children?: React.ReactNode;
}

export default function CombatGrid({
  gridSize, cellSize = 64, units,
  moveHighlights, rangeHighlights, aoeHighlights, selectedUnitId, uiMode, cursor,
  dragCell, onCellClick, onCellHover, onCellLeave, onCellHoverCell, onCellDrop, onGridDragMove, onGridMount,
  children,
}: Props) {
  const posToUnit: Record<string, CombatUnitDTO> = {};
  for (const u of units) {
    if (u.is_alive) {
      posToUnit[`${u.pos[0]},${u.pos[1]}`] = u;
    }
  }

  const gridRef = useRef<HTMLDivElement>(null);
  const cellCentersRef = useRef<({ x: number; y: number } | null)[][]>([]);

  // Recompute cell screen centers from DOM (handles margins, gaps, 3D perspective)
  const recomputeCenters = useCallback(() => {
    const g = gridRef.current;
    if (!g) return;
    const centers: ({ x: number; y: number } | null)[][] = [];
    for (let r = 0; r < gridSize; r++) {
      const rowCenters: ({ x: number; y: number } | null)[] = [];
      for (let c = 0; c < gridSize; c++) {
        rowCenters.push(getCellCenter(g, r, c));
      }
      centers.push(rowCenters);
    }
    cellCentersRef.current = centers;
  }, [gridSize]);

  useEffect(() => {
    recomputeCenters();
    const onResize = () => recomputeCenters();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [recomputeCenters]);

  useEffect(() => {
    if (gridRef.current && onGridMount) {
      onGridMount(gridRef.current);
    }
  }, [onGridMount]);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();  // don't bubble to parent overlay handler
    e.dataTransfer.dropEffect = "move";
    const cell = findClosestByCenters(e.clientX, e.clientY, cellCentersRef.current, gridSize);
    onGridDragMove(cell, e.clientX, e.clientY);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();  // don't bubble to parent overlay handler
    const cell = findClosestByCenters(e.clientX, e.clientY, cellCentersRef.current, gridSize);
    if (cell) onCellDrop(cell[0], cell[1]);
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
      let highlight: "" | "cursor" | "target" | "move" | "selected" | "range" | "aoe" = "";

      if (aoeHighlights?.has(key)) {
        highlight = "aoe";
      } else if (dragCell && dragCell[0] === r && dragCell[1] === c) {
        highlight = "target";
      } else if (cursor && cursor[0] === r && cursor[1] === c) {
        highlight = "cursor";
      } else if (uiMode === "TARGETING" && rangeHighlights.has(key)) {
        highlight = "range";
      } else if (uiMode === "VIEWING" && moveHighlights.has(key)) {
        highlight = "move";
      } else if (selectedUnitId && unit && unit.unit_id === selectedUnitId) {
        highlight = "selected";
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
            onCellHoverCell?.([r, c]);
          }}
          onMouseLeave={() => {
            onCellLeave?.();
            onCellHoverCell?.(null);
          }}
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
      <div className="combat-grid-3d" style={{ position: "relative" }}>
        <div
          ref={gridRef}
          className="flex flex-col gap-0.5 items-center relative"
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          onDragLeave={handleDragLeave}
        >
          {/* Column labels */}
          <div className="flex gap-0.5 mb-0.5">
            <div style={{ width: cellSize }} />
            {Array.from({ length: gridSize }, (_, c) => (
              <div
                key={c}
                className="text-center text-[9px] text-gray-600 font-mono"
                style={{ width: cellSize }}
              >
                {c}
              </div>
            ))}
          </div>
          {rows.map((row, i) => (
            <div key={i} className="flex gap-0.5 items-center">
              <div
                className="text-center text-[9px] text-gray-600 font-mono"
                style={{ width: cellSize }}
              >
                {i}
              </div>
              {row}
            </div>
          ))}
        </div>
        {children}
      </div>
    </div>
  );
}
