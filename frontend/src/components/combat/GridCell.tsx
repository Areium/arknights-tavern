import type { CombatUnitDTO } from "../../types";

interface Props {
  row: number;
  col: number;
  unit: CombatUnitDTO | null;
  highlight: "" | "cursor" | "target" | "move";
  onClick: (row: number, col: number) => void;
  onMouseEnter?: (e: React.MouseEvent) => void;
  onMouseLeave?: (e: React.MouseEvent) => void;
}

const TEAM_COLORS: Record<string, string> = {
  player: "bg-cyan-900/60 border-cyan-600 text-cyan-200",
  enemy: "bg-red-900/60 border-red-600 text-red-200",
};

const HIGHLIGHT_COLORS: Record<string, string> = {
  cursor: "ring-2 ring-yellow-400 bg-yellow-900/40",
  target: "ring-2 ring-green-400 bg-green-900/30",
  move: "ring-2 ring-blue-400 bg-blue-900/30",
};

export default function GridCell({ row, col, unit, highlight, onClick, onMouseEnter, onMouseLeave }: Props) {
  const teamStyle = unit ? TEAM_COLORS[unit.team] || "" : "bg-gray-800/40 border-gray-700";
  const highlightStyle = highlight ? HIGHLIGHT_COLORS[highlight] || "" : "";
  const label = unit ? unit.name.slice(0, 2) : "";

  return (
    <button
      className={`w-10 h-10 border text-xs font-bold flex items-center justify-center
        transition-colors hover:brightness-125 ${teamStyle} ${highlightStyle}`}
      onClick={() => onClick(row, col)}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      {label}
    </button>
  );
}
