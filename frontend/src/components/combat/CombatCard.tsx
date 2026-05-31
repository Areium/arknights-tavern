import { useState } from "react";
import type { CardDTO, SkinCrop } from "../../types";
import { DMG_LABELS, DMG_COLORS } from "./combatConfig";

interface Props {
  card: CardDTO;
  index: number;
  affordable: boolean;
  selected: boolean;
  highlighted?: boolean;
  skinUrl?: string;
  skinCrop?: SkinCrop | null;
  playing?: boolean;
  compact?: boolean;
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
  return Array.from({ length: 6 }, (_, i) => (
    <span className={i < filled ? "text-yellow-400 text-[11px]" : "text-gray-700 text-[11px] star-empty"} key={i}>
      ★
    </span>
  ));
}

export default function CombatCard({ card, index, affordable, selected, highlighted, skinUrl, skinCrop, playing, compact, onClick, onDragStart, onDragEnd }: Props) {
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
  const dmgColorClass = DMG_COLORS[card.damage_type] || "text-dmg-physical";
  const dmgLabel = DMG_LABELS[card.damage_type] || "物理";
  const isHealing = card.damage_type === "healing";
  const damageVerb = isHealing ? "恢复" : "造成";
  const damageUnit = isHealing ? "生命" : `${dmgLabel}伤害`;
  const damageFormula = `基础${isHealing ? "治疗" : dmgLabel + "伤害"} ${card.min_damage}-${card.max_damage} + 攻击力 × ${card.atk_scale.toFixed(1)}`;

  const targetLabel = card.target === "SINGLE" ? "单体" :
    card.target === "ADJACENT" ? "邻接" :
    card.target === "CROSS" ? "十字" :
    card.target === "LINE_3" ? "直线" :
    card.target === "ROW" ? "整行" :
    card.target === "AREA_2X2" ? "2×2范围" :
    card.target === "SELF" ? "自身" :
    card.target === "ALL_ALLIES" ? "全体友军" :
    card.target === "GLOBAL" ? "全图" :
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
      {/* 顶部信息栏：星级、职业 */}
      <div className="card-header-bar">
        <div className="flex items-center gap-1">
          {renderStars(card.tier)}
        </div>
        {!compact && (
          <div className="flex items-center gap-1">
            <span className="inline-block w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: classDotColor }} />
            <span className="text-[11px] text-gray-500">{card.class_required === "any" ? "通用" : card.class_required}</span>
            {card.owner && <span className="text-[11px] text-combat-gold">{card.owner}</span>}
          </div>
        )}
      </div>

      {/* 卡面 */}
      <div className={`card-art-area w-full relative ${compact ? 'h-[60px]' : 'h-[120px]'}`} style={hasSkin ? {} : { background: artBg }}>
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
        <span className={`absolute top-1 right-1 text-[11px] font-bold ${DMG_COLORS[card.damage_type] || "text-gray-400"}`}>
          {DMG_LABELS[card.damage_type]?.charAt(0) || "?"}
        </span>
        {showWatermark && (
          <span className="text-gray-600 text-[10px] font-mono opacity-30 rotate-[-30deg] select-none absolute inset-0 flex items-center justify-center">
            {card.name.length > 4 ? card.name.slice(0, 2) : card.name}
          </span>
        )}
      </div>

      {/* 信息区 */}
      <div className="p-2 pt-1">
        <div className="flex justify-between items-center mb-0.5">
          <span className="text-sm font-bold text-gray-100 truncate max-w-[70px]">{card.name}</span>
          <span className="text-xs text-combat-ap font-mono font-bold">AP:{card.cost}</span>
        </div>

        {card.description && (
          <div className="card-description" title={damageFormula}>
            {card.description}，{damageVerb}
            <span className={`font-mono font-bold ${dmgColorClass}`}>
              {Math.floor(card.min_damage)}~{Math.floor(card.max_damage)}
            </span>
            {damageUnit}
          </div>
        )}

        {!card.description && (
          <div className="card-description" title={damageFormula}>
            {damageVerb}
            <span className={`font-mono font-bold ${dmgColorClass}`}>
              {Math.floor(card.min_damage)}~{Math.floor(card.max_damage)}
            </span>
            {damageUnit}
          </div>
        )}

        <div className="damage-range-row font-bold">
          <span className="text-combat-gold">{targetLabel}</span>
          <span> · </span>
          <span className="text-combat-ap">{rangeLabel}</span>
        </div>
      </div>
    </button>
  );
}
