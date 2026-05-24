import type { CardDTO } from "../../types";
import CombatCard from "./CombatCard";

interface Props {
  cards: CardDTO[];
  activeAp: number;
  selectedIndex: number | null;
  disabled?: boolean;
  highlightOwner?: string | null;
  onCardClick: (index: number) => void;
  onCardDragStart?: (index: number) => void;
  onCardDragEnd?: () => void;
  cardWidth?: number;
  cardHeight?: number;
  fanMarginTop?: number;
}

export default function CombatHand({ cards, activeAp, selectedIndex, disabled, highlightOwner, onCardClick, onCardDragStart, onCardDragEnd, cardWidth, cardHeight, fanMarginTop }: Props) {
  const fanAngle = 3.5;
  const fanY = 8;

  return (
    <div
      className="combat-hand-fan"
      style={{
        ...(cardWidth ? { "--card-width": `${cardWidth}px` } : {}),
        ...(cardHeight ? { "--card-height": `${cardHeight}px` } : {}),
        ...(fanMarginTop !== undefined ? { marginTop: fanMarginTop } : {}),
      } as React.CSSProperties}
    >
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
              highlighted={!!highlightOwner && card.owner === highlightOwner}
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
