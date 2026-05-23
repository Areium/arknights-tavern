import type { CardDTO, CombatUnitDTO, PlayerPoolDTO } from "../../types";

interface Props {
  units: CombatUnitDTO[];
  sharedPool: PlayerPoolDTO;
  onClose: () => void;
}

const SECTION_LABELS: Record<string, string> = {
  hand: "手牌",
  deck: "抽牌堆",
  discard: "弃牌堆",
  exhaust: "消耗",
};

const SECTION_ORDER = ["hand", "deck", "discard", "exhaust"] as const;

type CardWithOwner = CardDTO & { owner?: string | null };

function sortCards<T extends { tier: string }>(cards: T[]): T[] {
  return [...cards].sort((a, b) => {
    const tierOrder = (t: string) => (t === "elite" ? 2 : t === "basic" ? 1 : 0);
    return tierOrder(a.tier) - tierOrder(b.tier);
  });
}

function CardMini({ card }: { card: CardWithOwner }) {
  const dmgColor =
    card.damage_type === "physical" ? "text-dmg-physical" :
    card.damage_type === "arts" ? "text-dmg-arts" :
    card.damage_type === "healing" ? "text-dmg-healing" : "text-dmg-mixed";

  const tgtLabel =
    card.target === "SINGLE" ? "单" :
    card.target === "ADJACENT" ? "邻" :
    card.target === "CROSS" ? "十" :
    card.target === "LINE_3" ? "直" :
    card.target === "ROW" ? "行" : card.target;

  return (
    <div className={`flex items-center gap-2 px-2 py-1 rounded text-xs ${
      card.tier === "elite" ? "bg-yellow-900/15 border border-yellow-800/30" : "bg-surface-dark/60 border border-surface-border/30"
    }`}>
      <span className={`font-mono font-bold w-5 text-center ${dmgColor}`}>
        {card.cost}
      </span>
      <span className="flex-1 truncate text-gray-200">{card.name}</span>
      {card.owner && (
        <span className="text-[10px] text-combat-gold">@{card.owner}</span>
      )}
      <span className="text-[10px] text-gray-500">{tgtLabel}</span>
      <span className="text-[10px] text-gray-600 font-mono">
        {card.range < 0 ? "∞" : card.range}
      </span>
      {card.tier === "elite" && <span className="text-yellow-400 text-[10px]">★</span>}
    </div>
  );
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

export default function DeckViewer({ units, sharedPool, onClose }: Props) {
  // Compute total card counts per character across all piles
  const allCards: CardDTO[] = [
    ...(sharedPool.hand || []),
    ...(sharedPool.deck || []),
    ...(sharedPool.discard || []),
    ...(sharedPool.exhaust || []),
  ];
  const totalPerOwner: Record<string, number> = {};
  for (const c of allCards) {
    const owner = c.owner || "未知";
    totalPerOwner[owner] = (totalPerOwner[owner] || 0) + 1;
  }

  // Get player unit names
  const playerUnits = units.filter((u) => u.team === "player" && u.is_alive);
  const ownerNames = Object.keys(totalPerOwner);

  const grandTotal = allCards.length;

  return (
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
            卡组查看
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

          {/* Character summary */}
          <div className="border border-combat-border rounded-xl overflow-hidden">
            <div className="bg-surface-dark/80 px-4 py-2.5 border-b border-combat-border">
              <span className="text-xs font-bold text-gray-200 font-display tracking-wider">
                角色卡牌统计
              </span>
            </div>
            <div className="p-3">
              <div className="flex flex-wrap gap-3">
                {ownerNames.map((owner) => {
                  const unit = playerUnits.find((u) => u.name === owner);
                  return (
                    <div key={owner} className="flex items-center gap-1.5 bg-surface-dark/40 px-2.5 py-1 rounded-lg border border-surface-border/50">
                      <span className="text-xs text-gray-200">{owner}</span>
                      {unit && (
                        <span className="text-[9px] text-gray-500">{unit.char_class}</span>
                      )}
                      <span className="text-[11px] text-combat-gold font-mono ml-1">
                        {totalPerOwner[owner]} 张
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Pool sections */}
          {SECTION_ORDER.map((section) => {
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
                            <CardMini key={`${card.card_id}-${i}`} card={card} />
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
  );
}
