import { useState } from "react";
import type { CardDTO, CombatUnitDTO, PlayerPoolDTO } from "../../types";
import { DMG_LABELS, DMG_COLORS } from "./combatConfig";

export type DeckFilterMode = "all" | "deck" | "discard";

interface Props {
  units: CombatUnitDTO[];
  sharedPool: PlayerPoolDTO;
  filterMode?: DeckFilterMode;
  onClose: () => void;
}

type PoolSection = "hand" | "deck" | "discard" | "exhaust";

const SECTION_LABELS: Record<PoolSection, string> = {
  hand: "手牌",
  deck: "抽牌堆",
  discard: "弃牌堆",
  exhaust: "消耗",
};

const TITLES: Record<DeckFilterMode, string> = {
  all: "卡组查看",
  deck: "抽牌堆",
  discard: "弃牌堆",
};

const TARGET_LABELS: Record<string, string> = {
  SINGLE: "单体", ADJACENT: "邻接", CROSS: "十字",
  LINE_3: "直线3格", ROW: "整行", AREA_2X2: "2×2区域",
  ALL_ALLIES: "全体友方", GLOBAL: "全体敌方", SELF: "自身",
};

function sortCards(cards: CardDTO[]): CardDTO[] {
  return [...cards].sort((a, b) => {
    const tierOrder = (t: string) => (t === "elite" ? 2 : t === "basic" ? 1 : 0);
    return tierOrder(b.tier) - tierOrder(a.tier);
  });
}

function groupByOwner(cards: CardDTO[]): Record<string, CardDTO[]> {
  const groups: Record<string, CardDTO[]> = {};
  for (const c of cards) {
    const owner = c.owner || "未知";
    if (!groups[owner]) groups[owner] = [];
    groups[owner].push(c);
  }
  return groups;
}

const TGT_ABBREV: Record<string, string> = {
  SINGLE: "单", ADJACENT: "邻", CROSS: "十", LINE_3: "直", ROW: "行",
};

function CardMini({ card, onClick }: { card: CardDTO; onClick: () => void }) {
  const dmgColor = DMG_COLORS[card.damage_type] || "text-dmg-mixed";
  const tgtLabel = TGT_ABBREV[card.target] || card.target;

  return (
    <button
      className={`flex items-center gap-2 px-2 py-1 rounded text-xs w-full text-left hover:brightness-125 transition-all ${
        card.tier === "elite"
          ? "bg-yellow-900/15 border border-yellow-800/30"
          : "bg-surface-dark/60 border border-surface-border/30"
      }`}
      onClick={onClick}
    >
      <span className={`font-mono font-bold w-5 text-center ${dmgColor}`}>{card.cost}</span>
      <span className="flex-1 truncate text-gray-200">{card.name}</span>
      {card.owner && <span className="text-[10px] text-combat-gold">@{card.owner}</span>}
      <span className="text-[10px] text-gray-500">{tgtLabel}</span>
      <span className="text-[10px] text-gray-600 font-mono">
        {card.range < 0 ? "∞" : card.range}
      </span>
      {card.tier === "elite" && <span className="text-yellow-400 text-[10px]">★</span>}
    </button>
  );
}

function CardDetail({ card, onClose }: { card: CardDTO; onClose: () => void }) {
  const dmgColor = DMG_COLORS[card.damage_type] || "text-dmg-mixed";
  const dmgLabel = DMG_LABELS[card.damage_type] || card.damage_type;
  const tgtLabel = TARGET_LABELS[card.target] || card.target;
  const rangeLabel = card.range < 0 ? "全图" : `${card.range} 格`;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-surface-card border border-combat-border rounded-2xl shadow-2xl w-[320px] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Art header */}
        <div
          className="w-full h-[120px] relative flex items-center justify-center"
          style={{
            background: `linear-gradient(135deg, hsl(${card.card_id.split("").reduce((a, c) => a + c.charCodeAt(0), 0) * 37 % 360}, 40%, 18%) 0%, hsl(${(card.card_id.split("").reduce((a, c) => a + c.charCodeAt(0), 0) * 37 + 40) % 360}, 35%, 12%) 100%)`,
          }}
        >
          {card.tier === "elite" && (
            <span className="absolute top-2 left-3 text-yellow-400 text-lg">★</span>
          )}
          <span className={`absolute top-2 right-3 text-xs font-bold ${dmgColor}`}>
            {dmgLabel}
          </span>
          <span className="text-gray-500 text-2xl font-bold opacity-20 select-none tracking-[0.3em]">
            {card.name}
          </span>
        </div>

        {/* Info */}
        <div className="p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-bold text-gray-100">{card.name}</h3>
            <span className={`text-lg font-mono font-bold ${dmgColor}`}>{card.cost} AP</span>
          </div>

          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <div className="bg-surface-dark/60 rounded-lg px-3 py-2">
              <span className="text-gray-500">伤害</span>
              <span className="text-gray-200 ml-2 font-mono">{card.min_damage}-{card.max_damage}</span>
            </div>
            <div className="bg-surface-dark/60 rounded-lg px-3 py-2">
              <span className="text-gray-500">攻击倍率</span>
              <span className="text-gray-200 ml-2 font-mono">×{card.atk_scale.toFixed(1)}</span>
            </div>
            <div className="bg-surface-dark/60 rounded-lg px-3 py-2">
              <span className="text-gray-500">目标</span>
              <span className="text-gray-200 ml-2">{tgtLabel}</span>
            </div>
            <div className="bg-surface-dark/60 rounded-lg px-3 py-2">
              <span className="text-gray-500">范围</span>
              <span className="text-gray-200 ml-2">{rangeLabel}</span>
            </div>
            <div className="bg-surface-dark/60 rounded-lg px-3 py-2">
              <span className="text-gray-500">职业</span>
              <span className="text-gray-200 ml-2">
                {card.class_required === "any" ? "通用" : card.class_required}
              </span>
            </div>
            <div className="bg-surface-dark/60 rounded-lg px-3 py-2">
              <span className="text-gray-500">品质</span>
              <span className={`ml-2 ${card.tier === "elite" ? "text-yellow-400" : "text-gray-400"}`}>
                {card.tier === "elite" ? "精英" : "基础"}
              </span>
            </div>
          </div>

          {card.owner && (
            <div className="text-[11px] text-combat-gold text-right">@{card.owner}</div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function DeckViewer({ units, sharedPool, filterMode = "all", onClose }: Props) {
  const [detailCard, setDetailCard] = useState<CardDTO | null>(null);

  const allCards: CardDTO[] = [
    ...(sharedPool.hand || []),
    ...(sharedPool.deck || []),
    ...(sharedPool.discard || []),
    ...(sharedPool.exhaust || []),
  ];

  const playerUnits = units.filter((u) => u.team === "player" && u.is_alive);
  const grandTotal = allCards.length;

  // For "all" mode: group all cards by owner
  const allByOwner = groupByOwner(sortCards(allCards));
  const ownerList = Object.keys(allByOwner).sort((a, b) => {
    const aUnit = playerUnits.find((u) => u.name === a);
    const bUnit = playerUnits.find((u) => u.name === b);
    if (aUnit && !bUnit) return -1;
    if (!aUnit && bUnit) return 1;
    return a.localeCompare(b);
  });

  // For single-pile modes: just show that pile
  const pileSections: PoolSection[] = filterMode === "all"
    ? []  // Don't show pile sections in "all" mode — use character grouping instead
    : filterMode === "deck" ? ["deck"] : ["discard"];

  return (
    <>
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      >
        <div
          className="bg-surface-card border border-combat-border rounded-2xl shadow-2xl w-[720px] max-h-[85vh] flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-combat-border">
            <h2 className="text-sm font-bold text-gray-200 font-display tracking-wider">
              {TITLES[filterMode]}
            </h2>
            <span className="text-[11px] text-gray-500 font-display">{grandTotal} 张</span>
            <div className="flex-1" />
            <button
              onClick={onClose}
              className="text-gray-500 hover:text-gray-300 text-lg leading-none px-1"
            >
              ×
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {grandTotal === 0 && (
              <p className="text-gray-500 text-sm text-center py-8">卡组为空</p>
            )}

            {/* "All" mode: character-grouped cards */}
            {filterMode === "all" && ownerList.map((owner) => {
              const cards = allByOwner[owner];
              const unit = playerUnits.find((u) => u.name === owner);
              return (
                <div key={owner} className="border border-combat-border rounded-xl overflow-hidden">
                  <div className="bg-surface-dark/80 px-4 py-2.5 flex items-center gap-2 border-b border-combat-border">
                    <span className="text-sm font-bold text-gray-200 font-display tracking-wider">
                      {owner}
                    </span>
                    {unit && (
                      <span className="text-[10px] text-gray-500">{unit.char_class}</span>
                    )}
                    <span className="text-[11px] text-combat-gold font-mono ml-auto">
                      {cards.length} 张
                    </span>
                  </div>
                  <div className="p-3 space-y-1">
                    {cards.map((card, i) => (
                      <CardMini
                        key={`${card.card_id}-${i}`}
                        card={card}
                        onClick={() => setDetailCard(card)}
                      />
                    ))}
                  </div>
                </div>
              );
            })}

            {/* Single-pile modes: simple section display */}
            {pileSections.map((section) => {
              const cards = sharedPool[section] || [];
              if (cards.length === 0) return null;
              const sorted = sortCards(cards);
              const groups = groupByOwner(sorted);
              const owners = Object.keys(groups);

              return (
                <div key={section} className="border border-combat-border rounded-xl overflow-hidden">
                  <div className="bg-surface-dark/80 px-4 py-2.5 flex items-center gap-2 border-b border-combat-border">
                    <span className="text-sm font-bold text-gray-200 font-display tracking-wider">
                      {SECTION_LABELS[section]}
                    </span>
                    <span className="text-[11px] text-gray-500 font-mono">({cards.length})</span>
                  </div>
                  <div className="p-3 space-y-3">
                    {owners.map((owner) => {
                      const ownerCards = groups[owner];
                      return (
                        <div key={owner}>
                          <div className="text-[10px] text-combat-gold mb-1">@{owner}</div>
                          <div className="space-y-1">
                            {ownerCards.map((card, i) => (
                              <CardMini
                                key={`${card.card_id}-${i}`}
                                card={card}
                                onClick={() => setDetailCard(card)}
                              />
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Card detail overlay */}
      {detailCard && (
        <CardDetail card={detailCard} onClose={() => setDetailCard(null)} />
      )}
    </>
  );
}
