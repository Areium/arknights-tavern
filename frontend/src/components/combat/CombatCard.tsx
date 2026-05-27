import { useState } from "react";
import type { CardDTO, SkinCrop } from "../../types";

interface Props {
  card: CardDTO;
  index: number;
  affordable: boolean;
  selected: boolean;
  highlighted?: boolean;
  skinUrl?: string;
  skinCrop?: SkinCrop | null;
  playing?: boolean;
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

const DMG_TEXT_COLORS: Record<string, string> = {
  physical: "text-dmg-physical", arts: "text-dmg-arts",
  healing: "text-dmg-healing", mixed: "text-dmg-mixed",
};

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

const CLASS_DOT_COLORS: Record<string, string> = {
  "先锋": "#d4a574", "近卫": "#c44b3c", "重装": "#4a6b8a",
  "狙击": "#3c8c4a", "术师": "#8b5ca8", "医疗": "#5c9a8b",
  "辅助": "#c4a83c", "特种": "#6b5c8a",
};

function renderStars(tier: string) {
  const filled = tier === "elite" ? 3 : 1;
  return Array.from({ length: 5 }, (_, i) => (
    <span className={i < filled ? "text-yellow-400 text-[10px]" : "text-gray-700 text-[10px] star-empty"} key={i}>
      ★
    </span>
  ));
}

export default function CombatCard({ card, index, affordable, selected, highlighted, skinUrl, skinCrop, playing, onClick, onDragStart, onDragEnd }: Props) {
  const classKey = CLASS_CSS[card.class_required] || "";
  const tierClass = card.tier === "elite" ? "elite" : "";
  const selectedClass = selected ? "selected" : "";
  const highlightedClass = highlighted ? "highlighted" : "";
  const disabledClass = !affordable ? "disabled" : "";
  const artBg = cardArtGradient(card.card_id, card.damage_type);
  const [imgError, setImgError] = useState(false);
  const hasSkin = skinUrl && !imgError;

  const handleDragStart = (e: React.DragEvent) => {
    if (!affordable) {
      e.preventDefault();
      return;
    }
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(index));
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    const ctx = canvas.getContext("2d");
    if (ctx) ctx.clearRect(0, 0, 1, 1);
    e.dataTransfer.setDragImage(canvas, -10, -10);
    onDragStart?.();
  };

  const handleDragEnd = () => {
    onDragEnd?.();
  };

  const classDotColor = CLASS_DOT_COLORS[card.class_required] || "#6b6b80";
  const showWatermark = !hasSkin;
  const dmgColorClass = DMG_TEXT_COLORS[card.damage_type] || "text-dmg-physical";
  const isHealing = card.damage_type === "healing";
  const damageFormula = `基础${isHealing ? "治疗" : "伤害"} ${card.min_damage}-${card.max_damage} + 攻击力 × ${card.atk_scale.toFixed(1)}`;

  const targetLabel = card.target === "SINGLE" ? "单体" :
    card.target === "ADJACENT" ? "邻接" :
    card.target === "CROSS" ? "十字" :
    card.target === "LINE_3" ? "直线" :
    card.target === "ROW" ? "整行" :
    card.target;
  const rangeLabel = card.range < 0 ? "全图" : `${card.range}格`;

  return (
    <button
      className={`combat-card ${classKey} ${tierClass} ${selectedClass} ${highlightedClass} ${disabledClass} ${playing ? 'card-playing' : ''}`}
      onClick={onClick}
      disabled={!affordable || playing}
      draggable={affordable && !playing}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      {/* 头部：稀有度 + 职业 */}
      <div className="card-header-bar">
        <div className="card-rarity-stars">{renderStars(card.tier)}</div>
        <div className="flex items-center gap-1 text-[10px] text-gray-500">
          <span className="inline-block w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: classDotColor }} />
          <span>{card.class_required === "any" ? "通用" : card.class_required}</span>
          {card.owner && <span className="text-combat-gold">@{card.owner}</span>}
        </div>
      </div>

      {/* 卡面（120px） */}
      <div className="card-art-area w-full h-[80px] relative" style={hasSkin ? {} : { background: artBg }}>
        {hasSkin && skinCrop ? (
          <div className="card-art-crop">
            <img
              src={skinUrl}
              alt=""
              draggable={false}
              style={{
                position: "absolute",
                left: `${-(skinCrop.x / skinCrop.w) * 100}%`,
                top: `${-(skinCrop.y / skinCrop.h) * 100}%`,
                width: `${(100 / skinCrop.w) * 100}%`,
                height: `${(100 / skinCrop.h) * 100}%`,
              }}
              onError={() => setImgError(true)}
            />
          </div>
        ) : hasSkin ? (
          <img
            src={skinUrl}
            alt=""
            draggable={false}
            className="card-art-cover"
            onError={() => setImgError(true)}
          />
        ) : null}
        <span className={`absolute top-1 right-1 text-[10px] font-bold ${DMG_ICON_COLORS[card.damage_type] || "text-gray-400"}`}>
          {DMG_LABELS[card.damage_type]?.charAt(0) || "?"}
        </span>
        {showWatermark && (
          <span className="text-gray-600 text-[9px] font-mono opacity-30 rotate-[-30deg] select-none absolute inset-0 flex items-center justify-center">
            {card.name.length > 4 ? card.name.slice(0, 2) : card.name}
          </span>
        )}
      </div>

      {/* 信息区 */}
      <div className="p-2 pt-1">
        <div className="flex justify-between items-start">
          <span className="text-xs font-bold text-gray-100 truncate max-w-[90px]">
            {card.name}
          </span>
          <span className="text-[11px] text-combat-ap font-mono font-bold">{card.cost}</span>
        </div>

        {card.description && (
          <div className="card-description" title={damageFormula}>
            {card.description}，造成
            <span className={`font-mono font-bold ${dmgColorClass}`}>
              {Math.floor(card.min_damage)}~{Math.floor(card.max_damage)}
            </span>
            伤害 · {targetLabel} · {rangeLabel}
          </div>
        )}

        {!card.description && (
          <div className="card-description" title={damageFormula}>
            造成
            <span className={`font-mono font-bold ${dmgColorClass}`}>
              {Math.floor(card.min_damage)}~{Math.floor(card.max_damage)}
            </span>
            伤害 · {targetLabel} · {rangeLabel}
          </div>
        )}
      </div>
    </button>
  );
}
