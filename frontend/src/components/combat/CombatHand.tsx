import type { CardDTO } from "../../types";
import CombatCard from "./CombatCard";

interface Props {
  cards: CardDTO[];
  activeAp: number;
  selectedIndex: number | null;
  disabled?: boolean;
  highlightOwner?: string | null;
  onCardClick: (index: number) => void;
}

export default function CombatHand({ cards, activeAp, selectedIndex, disabled, highlightOwner, onCardClick }: Props) {
  return (
    <div className="flex gap-1.5 overflow-x-auto py-2 px-1 min-h-[110px] items-center">
      {cards.length === 0 && (
        <span className="text-gray-500 text-sm italic px-4">手牌为空</span>
      )}
      {cards.map((card, i) => (
        <CombatCard
          key={`${card.card_id}-${i}`}
          card={card}
          index={i}
          affordable={!disabled && card.cost <= activeAp}
          selected={selectedIndex === i}
          highlighted={!!highlightOwner && card.owner === highlightOwner}
          onClick={() => onCardClick(i)}
        />
      ))}
    </div>
  );
}
