import { memo } from "react";
import type { TileTypeDTO } from "../../types";

interface Props {
  row: number;
  col: number;
  highlight: "" | "cursor" | "target" | "move" | "selected" | "range" | "aoe";
  /** 该格地形（来自服务端 tile_defs；缺省为普通地面） */
  tile?: TileTypeDTO;
  /** 部署区归属：用于给玩家/敌方部署格着色 */
  deployTeam?: "player" | "enemy" | "";
  onClick: (row: number, col: number) => void;
  onMouseEnter?: (e: React.MouseEvent) => void;
  onMouseLeave?: () => void;
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

/** 地形底色：在既有 combat-cell 底纹上叠一层低透明度颜色；阻挡格加深。 */
function tileStyle(tile?: TileTypeDTO): React.CSSProperties {
  if (!tile || tile.tile_id === "ground") return {};
  if (tile.blocks_movement) {
    return { backgroundColor: `${tile.color}cc`, borderColor: tile.color };
  }
  return { backgroundColor: `${tile.color}55`, borderColor: `${tile.color}aa` };
}

const GridCell = memo(function GridCell({
  row, col, highlight, tile, deployTeam, onClick, onMouseEnter, onMouseLeave,
}: Props) {
  const cellClass = getHighlightClass(highlight);
  const deployRing =
    deployTeam === "player" ? "ring-1 ring-inset ring-cyan-800/40"
      : deployTeam === "enemy" ? "ring-1 ring-inset ring-red-900/40"
        : "";
  const glyph = tile && tile.tile_id !== "ground" ? tile.glyph : "";

  return (
    <button
      className={`${cellClass} ${deployRing} flex items-center justify-center`}
      onClick={(e) => { e.stopPropagation(); onClick(row, col); }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      style={{ position: "relative", ...tileStyle(tile) }}
      title={glyph ? `${tile?.name}（移动代价 ${tile?.move_cost}）` : undefined}
    >
      {glyph
        ? <span className="text-[10px] leading-none opacity-70">{glyph}</span>
        : <span className="text-[9px] text-gray-700 font-mono">{row},{col}</span>}
    </button>
  );
}, (prev, next) => {
  return prev.row === next.row
    && prev.col === next.col
    && prev.highlight === next.highlight
    && prev.deployTeam === next.deployTeam
    && prev.tile?.tile_id === next.tile?.tile_id;
});

export default GridCell;
