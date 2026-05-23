import React from "react";
import type { CombatUnitDTO } from "../../types";
import GridCell from "./GridCell";

const CELL = 56; // px

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
  onCellClick: (row: number, col: number) => void;
  onCellHover?: (unit: CombatUnitDTO, rect: DOMRect) => void;
  onCellLeave?: () => void;
  onCellDrop: (row: number, col: number) => void;
  onGridDragMove: (cell: [number, number] | null) => void;
}

export default function CombatGrid({
  gridSize, units, grid, validTargets, validMoves,
  moveHighlights, rangeHighlights, selectedUnitId, uiMode, cursor,
  dragCell, onCellClick, onCellHover, onCellLeave, onCellDrop, onGridDragMove,
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
          className="flex flex-col gap-0.5 items-center"
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
        </div>
      </div>
    </div>
  );
}
