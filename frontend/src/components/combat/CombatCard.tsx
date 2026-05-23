import type { CardDTO } from "../../types";

interface Props {
  card: CardDTO;
  index: number;
  affordable: boolean;
  selected: boolean;
  highlighted?: boolean;
  onClick: () => void;
}

const DAMAGE_COLORS: Record<string, string> = {
  physical: "border-red-700 bg-red-950/60",
  arts: "border-purple-700 bg-purple-950/60",
  healing: "border-green-700 bg-green-950/60",
  mixed: "border-amber-700 bg-amber-950/60",
};

const DMG_LABELS: Record<string, string> = {
  physical: "物",
  arts: "法",
  healing: "治",
  mixed: "混",
};

export default function CombatCard({ card, index, affordable, selected, highlighted, onClick }: Props) {
  const borderColor = DAMAGE_COLORS[card.damage_type] || "border-gray-700 bg-gray-900/60";
  const selectedRing = selected ? "ring-2 ring-yellow-400" : "";
  const highlightRing = highlighted ? "ring-1 ring-cyan-400 bg-cyan-900/10" : "";
  const opacity = affordable ? "" : "opacity-40";

  return (
    <button
      className={`flex-shrink-0 w-36 h-24 border rounded p-1.5 text-left
        transition-all hover:brightness-110 ${borderColor} ${selectedRing} ${highlightRing} ${opacity}`}
      onClick={onClick}
      disabled={!affordable}
    >
      <div className="flex justify-between items-start">
        <span className="text-xs font-bold text-gray-100 truncate max-w-[80px]">
          {card.tier === "elite" && <span className="text-yellow-400 mr-0.5">*</span>}
          {card.name}
        </span>
        <span className="text-[10px] text-cyan-400 font-mono">{card.cost}AP</span>
      </div>
      <div className="text-[10px] text-gray-400 mt-0.5">
        <span className="font-mono">{card.min_damage}-{card.max_damage}</span>
        {" "}
        <span className="text-gray-500">x{card.atk_scale.toFixed(1)}</span>
        <span className={`ml-1 px-0.5 rounded text-[9px] ${DAMAGE_COLORS[card.damage_type]}`}>
          {DMG_LABELS[card.damage_type] || card.damage_type}
        </span>
      </div>
      <div className="text-[9px] text-gray-500 mt-0.5 truncate">
        {card.target} {card.range < 0 ? "全图" : `${card.range}格`}
      </div>
      <div className="text-[9px] text-gray-600 mt-0.5">
        [{index + 1}] {card.class_required === "any" ? "通用" : card.class_required}
        {card.owner && <span className="text-yellow-500 ml-0.5">@{card.owner}</span>}
      </div>
    </button>
  );
}
