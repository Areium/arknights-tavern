import { memo } from "react";
import type { CombatUnitDTO } from "../../types";

interface Props {
  row: number;
  col: number;
  unit: CombatUnitDTO | null;
  highlight: "" | "cursor" | "target" | "move" | "selected" | "range" | "aoe";
  onClick: (row: number, col: number) => void;
  onMouseEnter?: (e: React.MouseEvent) => void;
  onMouseLeave?: (e: React.MouseEvent) => void;
}

function getHighlightClass(highlight: string): string {
  switch (highlight) {
    case "cursor":   return "combat-cell highlight-cursor";
    case "target":   return "combat-cell highlight-target";
    case "move":     return "combat-cell highlight-move";
    case "selected": return "combat-cell highlight-selected";
    case "range":    return "combat-cell highlight-range";
    case "aoe":      return "combat-cell highlight-aoe";
    default:         return "combat-cell";
  }
}

const GridCell = memo(function GridCell({ row, col, unit, highlight, onClick, onMouseEnter, onMouseLeave }: Props) {
  const cellClass = getHighlightClass(highlight);

  return (
    <button
      className={`${cellClass} flex items-center justify-center`}
      onClick={(e) => { e.stopPropagation(); onClick(row, col); }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      style={{ position: "relative" }}
    >
      <span className="text-[9px] text-gray-700 font-mono">{row},{col}</span>
    </button>
  );
}, (prev, next) => {
  return prev.row === next.row
    && prev.col === next.col
    && prev.highlight === next.highlight
    && prev.unit === next.unit;
});

export default GridCell;
