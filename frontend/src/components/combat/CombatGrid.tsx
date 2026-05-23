import type { CombatUnitDTO } from "../../types";
import GridCell from "./GridCell";

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
  onCellClick: (row: number, col: number) => void;
  onCellHover?: (unit: CombatUnitDTO, rect: DOMRect) => void;
  onCellLeave?: () => void;
}

export default function CombatGrid({
  gridSize, units, grid, validTargets, validMoves, moveHighlights, rangeHighlights, selectedUnitId, uiMode, cursor, onCellClick, onCellHover, onCellLeave,
}: Props) {
  const posToUnit: Record<string, CombatUnitDTO> = {};
  for (const u of units) {
    if (u.is_alive) {
      posToUnit[`${u.pos[0]},${u.pos[1]}`] = u;
    }
  }

  const targetSet = new Set(validTargets.map(([r, c]) => `${r},${c}`));

  const rows: React.ReactNode[] = [];
  for (let r = 0; r < gridSize; r++) {
    const cells: React.ReactNode[] = [];
    for (let c = 0; c < gridSize; c++) {
      const key = `${r},${c}`;
      const unit = posToUnit[key] || null;
      let highlight: "" | "cursor" | "target" | "move" = "";

      if (cursor && cursor[0] === r && cursor[1] === c) {
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
    <div className="flex flex-col gap-0.5 items-center">
      {/* Column labels */}
      <div className="flex gap-0.5 mb-0.5">
        <div className="w-10" />
        {Array.from({ length: gridSize }, (_, c) => (
          <div key={c} className="w-10 text-center text-[10px] text-gray-500">{c}</div>
        ))}
      </div>
      {rows.map((row, i) => (
        <div key={i} className="flex gap-0.5 items-center">
          <div className="w-10 text-center text-[10px] text-gray-500">{i}</div>
          {row}
        </div>
      ))}
    </div>
  );
}
