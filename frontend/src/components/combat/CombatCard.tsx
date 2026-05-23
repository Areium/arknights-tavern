import type { CardDTO } from "../../types";

interface Props {
  card: CardDTO;
  index: number;
  affordable: boolean;
  selected: boolean;
  onClick: () => void;
  onDragStart?: () => void;
  onDragEnd?: () => void;
}

const CLASS_CSS: Record<string, string> = {
  "先锋": "class-vanguard", "近卫": "class-guard",
  "重装": "class-defender", "狙击": "class-sniper",
  "术师": "class-caster", "医疗": "class-medic",
  "辅助": "class-supporter", "特种": "class-specialist",
};

const DMG_LABELS: Record<string, string> = {
  physical: "物理", arts: "法术", healing: "治疗", mixed: "混合",
};

const DMG_ICON_COLORS: Record<string, string> = {
  physical: "text-dmg-physical", arts: "text-dmg-arts",
  healing: "text-dmg-healing", mixed: "text-dmg-mixed",
};

// Generate a pseudo card-art gradient based on card_id for visual variety
function cardArtGradient(cardId: string, damageType: string): string {
  const hash = cardId.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
  const hue1 = (hash * 37) % 360;
  const hue2 = (hue1 + 40) % 360;
  const dmgHues: Record<string, number> = {
    physical: 15, arts: 270, healing: 140, mixed: 45,
  };
  const base = dmgHues[damageType] || 220;
  return `linear-gradient(135deg, hsl(${base}, 40%, 18%) 0%, hsl(${base + 30}, 35%, 12%) 50%, hsl(${base - 20}, 30%, 8%) 100%)`;
}

export default function CombatCard({ card, index, affordable, selected, onClick, onDragStart, onDragEnd }: Props) {
  const classKey = CLASS_CSS[card.class_required] || "";
  const tierClass = card.tier === "elite" ? "elite" : "";
  const selectedClass = selected ? "selected" : "";
  const disabledClass = !affordable ? "disabled" : "";
  const artBg = cardArtGradient(card.card_id, card.damage_type);

  const handleDragStart = (e: React.DragEvent) => {
    if (!affordable) {
      e.preventDefault();
      return;
    }
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(index));
    // Set a small transparent drag image so the cursor isn't obscured
    const img = new Image();
    img.src = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
    e.dataTransfer.setDragImage(img, 0, 0);
    onDragStart?.();
  };

  const handleDragEnd = () => {
    onDragEnd?.();
  };

  return (
    <button
      className={`combat-card ${classKey} ${tierClass} ${selectedClass} ${disabledClass}`}
      onClick={onClick}
      disabled={!affordable}
      draggable={affordable}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      {/* Card art area */}
      <div
        className="w-full h-[80px] relative flex items-center justify-center"
        style={{ background: artBg }}
      >
        {/* Damage type icon in corner */}
        <span className={`absolute top-1 right-1 text-[10px] font-bold ${DMG_ICON_COLORS[card.damage_type] || "text-gray-400"}`}>
          {DMG_LABELS[card.damage_type]?.charAt(0) || "?"}
        </span>
        {/* Elite star */}
        {card.tier === "elite" && (
          <span className="absolute top-1 left-7 text-yellow-400 text-sm">★</span>
        )}
        {/* Card ID watermark */}
        <span className="text-gray-600 text-[9px] font-mono opacity-30 rotate-[-30deg] select-none">
          {card.name.length > 4 ? card.name.slice(0, 2) : card.name}
        </span>
      </div>

      {/* Card info */}
      <div className="p-2 pt-1">
        {/* Name + Cost */}
        <div className="flex justify-between items-start">
          <span className="text-xs font-bold text-gray-100 truncate max-w-[90px]">
            {card.name}
          </span>
          <span className="text-[11px] text-combat-ap font-mono font-bold">{card.cost}</span>
        </div>

        {/* Damage range */}
        <div className="text-[10px] text-gray-400 mt-0.5 font-mono">
          <span>{card.min_damage}-{card.max_damage}</span>
          <span className="text-gray-600 ml-1">×{card.atk_scale.toFixed(1)}</span>
        </div>

        {/* Target + Range */}
        <div className="text-[9px] text-gray-500 mt-0.5">
          {card.target === "SINGLE" ? "单体" :
           card.target === "ADJACENT" ? "邻接" :
           card.target === "CROSS" ? "十字" :
           card.target === "LINE_3" ? "直线" :
           card.target === "ROW" ? "整行" :
           card.target}
          {" · "}
          {card.range < 0 ? "全图" : `${card.range}格`}
        </div>

        {/* Class + Owner + hotkey */}
        <div className="text-[9px] text-gray-600 mt-1 flex justify-between">
          <span>
            {card.class_required === "any" ? "通用" : card.class_required}
            {card.owner && <span className="text-combat-gold ml-0.5">@{card.owner}</span>}
          </span>
          <span className="font-mono text-gray-700">[{index + 1}]</span>
        </div>
      </div>
    </button>
  );
}
