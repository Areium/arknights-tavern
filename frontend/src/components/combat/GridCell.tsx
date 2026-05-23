import type { CombatUnitDTO } from "../../types";
import ChibiSprite from "./ChibiSprite";

interface Props {
  row: number;
  col: number;
  unit: CombatUnitDTO | null;
  highlight: "" | "cursor" | "target" | "move";
  onClick: (row: number, col: number) => void;
}

function getHighlightClass(highlight: string, isPlayerZone: boolean): string {
  const zone = isPlayerZone ? "player-zone" : "enemy-zone";
  switch (highlight) {
    case "cursor": return `combat-cell ${zone} highlight-cursor`;
    case "target": return `combat-cell ${zone} highlight-target`;
    case "move":   return `combat-cell ${zone} highlight-move`;
    default:       return `combat-cell ${zone}`;
  }
}

export default function GridCell({ row, col, unit, highlight, onClick }: Props) {
  const isPlayerZone = col <= 2;
  const cellClass = getHighlightClass(highlight, isPlayerZone);

  return (
    <button
      className={`${cellClass} flex items-center justify-center`}
      onClick={() => onClick(row, col)}
      title={
        unit
          ? `${unit.name} (${unit.char_class}) HP:${unit.hp}/${unit.max_hp} ATK:${unit.patk}/${unit.matk}`
          : `(${row},${col})`
      }
      style={{ position: "relative" }}
    >
      {unit ? (
        <ChibiSprite unit={unit} />
      ) : (
        <span className="text-[9px] text-gray-700 font-mono">{row},{col}</span>
      )}
    </button>
  );
}
