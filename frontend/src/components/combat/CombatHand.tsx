import type { CardDTO, SkinCrop } from "../../types";
import CombatCard from "./CombatCard";

interface Props {
  cards: CardDTO[];
  getCardAp: (card: CardDTO) => number;
  selectedIndex: number | null;
  disabled?: boolean;
  highlightOwner?: string | null;
  ownerSkins?: Record<string, { url: string; crop: SkinCrop | null }>;
  onCardClick: (index: number) => void;
  onCardDragStart?: (index: number) => void;
  onCardDragEnd?: () => void;
  playingIndex?: number | null;
  cardWidth?: number;
  cardHeight?: number;
  fanMarginTop?: number;
  compact?: boolean;
}

export default function CombatHand({ cards, getCardAp, selectedIndex, disabled, highlightOwner, ownerSkins, playingIndex, onCardClick, onCardDragStart, onCardDragEnd, cardWidth, cardHeight, fanMarginTop, compact }: Props) {
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
            key={`${card.card_id}-${card.owner || 'none'}`}
            className="hand-card-wrapper"
            data-hand-index={i}
            style={{
              transform: `rotate(${rotation}deg) translateY(${translateY}px)`,
              zIndex: i,
            }}
          >
            <CombatCard
              card={card}
              index={i}
              affordable={!disabled && card.cost <= getCardAp(card)}
              selected={selectedIndex === i}
              highlighted={!!highlightOwner && card.owner === highlightOwner}
              skinUrl={card.owner ? ownerSkins?.[card.owner]?.url : undefined}
              skinCrop={card.owner ? ownerSkins?.[card.owner]?.crop ?? undefined : undefined}
              playing={playingIndex === i}
              compact={compact}
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
