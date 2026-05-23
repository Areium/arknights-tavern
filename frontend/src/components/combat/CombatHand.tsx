import type { CardDTO } from "../../types";
import CombatCard from "./CombatCard";

interface Props {
  cards: CardDTO[];
  activeAp: number;
  selectedIndex: number | null;
  disabled?: boolean;
  onCardClick: (index: number) => void;
  onCardDragStart?: (index: number) => void;
  onCardDragEnd?: () => void;
}

export default function CombatHand({ cards, activeAp, selectedIndex, disabled, onCardClick, onCardDragStart, onCardDragEnd }: Props) {
  const fanAngle = 3.5; // degrees per card offset
  const fanY = 8;       // px vertical offset per card from center

  return (
    <div className="combat-hand-fan">
      {cards.length === 0 && (
        <span className="text-gray-600 text-sm italic px-4 self-center">手牌为空</span>
      )}
      {cards.map((card, i) => {
        const offset = i - (cards.length - 1) / 2;
        const rotation = offset * fanAngle;
        const translateY = Math.abs(offset) * fanY;

        return (
          <div
            key={`${card.card_id}-${i}`}
            className="hand-card-wrapper"
            style={{
              transform: `rotate(${rotation}deg) translateY(${translateY}px)`,
              zIndex: i,
            }}
          >
            <CombatCard
              card={card}
              index={i}
              affordable={!disabled && card.cost <= activeAp}
              selected={selectedIndex === i}
              onClick={() => onCardClick(i)}
              onDragStart={() => onCardDragStart?.(i)}
              onDragEnd={onCardDragEnd}
            />
          </div>
        );
      })}
    </div>
  );
}
