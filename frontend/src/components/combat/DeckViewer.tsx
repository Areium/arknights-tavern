import type { CombatUnitDTO, PlayerPoolDTO } from "../../types";

interface Props {
  units: CombatUnitDTO[];
  playerPools: Record<string, PlayerPoolDTO>;
  onClose: () => void;
}

const SECTION_LABELS: Record<string, string> = {
  hand: "手牌",
  deck: "抽牌堆",
  discard: "弃牌堆",
  exhaust: "消耗",
};

const SECTION_ORDER = ["hand", "deck", "discard", "exhaust"] as const;

function sortCards<T extends { tier: string }>(cards: T[]): T[] {
  return [...cards].sort((a, b) => {
    const tierOrder = (t: string) => (t === "elite" ? 2 : t === "basic" ? 1 : 0);
    return tierOrder(a.tier) - tierOrder(b.tier);
  });
}

function CardMini({ card }: { card: { name: string; cost: number; damage_type: string; tier: string; range: number; target: string } }) {
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
      <span className="text-[10px] text-gray-500">{tgtLabel}</span>
      <span className="text-[10px] text-gray-600 font-mono">
        {card.range < 0 ? "∞" : card.range}
      </span>
      {card.tier === "elite" && <span className="text-yellow-400 text-[10px]">★</span>}
    </div>
  );
}

export default function DeckViewer({ units, playerPools, onClose }: Props) {
  const playerUnitIds = Object.keys(playerPools);

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
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300 text-lg leading-none px-1"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {playerUnitIds.length === 0 && (
            <p className="text-gray-500 text-sm text-center py-8">没有角色数据</p>
          )}

          {playerUnitIds.map((uid) => {
            const pool = playerPools[uid];
            const unit = units.find((u) => u.unit_id === uid);
            const unitName = unit?.name || uid;
            const charClass = unit?.char_class || "";

            return (
              <div key={uid} className="border border-combat-border rounded-xl overflow-hidden">
                {/* Character header */}
                <div className="bg-surface-dark/80 px-4 py-2.5 flex items-center gap-2 border-b border-combat-border">
                  <span className="text-sm font-bold text-gray-100">{unitName}</span>
                  {charClass && (
                    <span className="text-[10px] text-gray-500 bg-surface-card px-1.5 py-0.5 rounded">
                      {charClass}
                    </span>
                  )}
                  <span className="text-[10px] text-gray-600 ml-auto">
                    {pool.hand.length + pool.deck.length + pool.discard.length + pool.exhaust.length} 张
                  </span>
                </div>

                {/* Card sections */}
                <div className="p-3 space-y-2.5">
                  {SECTION_ORDER.map((section) => {
                    const cards = pool[section];
                    if (!cards || cards.length === 0) return null;
                    const sorted = sortCards(cards);

                    return (
                      <div key={section}>
                        <div className="text-[10px] text-gray-500 font-display tracking-wider mb-1.5">
                          {SECTION_LABELS[section]}
                          <span className="text-gray-600 ml-1">({sorted.length})</span>
                        </div>
                        <div className="space-y-1">
                          {sorted.map((card, i) => (
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
