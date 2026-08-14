/**
 * 出牌飞行动画 — 卡牌从手牌区沿弧线飞向目标格子，落点淡出。
 * 由 CombatView 在发起 play_card 时触发，与既有手牌 card-playing 缩回动画叠加。
 */
import { useEffect, useRef } from "react";
import type { CardDTO } from "../../types";
import { DMG_LABELS } from "./combatConfig";

export interface CardFlight {
  card: CardDTO;
  /** 起始矩形（手牌中卡牌的 viewport 坐标） */
  from: DOMRect;
  /** 目标点（目标格子中心的 viewport 坐标） */
  to: { x: number; y: number };
  /** 卡面皮肤图（可选） */
  skinUrl?: string;
}

const CLASS_BORDER: Record<string, string> = {
  "先锋": "#d4a574", "近卫": "#c44b3c", "重装": "#4a6b8a", "狙击": "#3c8c4a",
  "术师": "#8b5ca8", "医疗": "#5c9a8b", "辅助": "#c4a83c", "特种": "#6b5c8a",
};

const DMG_TEXT: Record<string, string> = {
  physical: "#ff6b4a", arts: "#b44af0", healing: "#4aff8b", mixed: "#f0c060",
};

export default function CardFlyOverlay({ flight, onDone }: { flight: CardFlight | null; onDone: () => void }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!flight || !ref.current) return;
    const el = ref.current;
    const fromCx = flight.from.left + flight.from.width / 2;
    const fromCy = flight.from.top + flight.from.height / 2;
    const dx = flight.to.x - fromCx;
    const dy = flight.to.y - fromCy;
    // 上抛弧线：横向越远弧线越高
    const arc = -Math.max(50, Math.min(140, Math.abs(dx) * 0.18 + Math.abs(dy) * 0.12));
    const anim = el.animate(
      [
        { transform: "translate(-50%, -50%) translate(0px, 0px) rotate(0deg) scale(0.5)", opacity: 0.85, offset: 0 },
        { transform: "translate(-50%, -50%) translate(" + dx * 0.5 + "px, " + (dy * 0.5 + arc) + "px) rotate(6deg) scale(1.04)", opacity: 1, offset: 0.55 },
        { transform: "translate(-50%, -50%) translate(" + dx + "px, " + dy + "px) rotate(0deg) scale(0.82)", opacity: 0, offset: 1 },
      ],
      { duration: 460, easing: "cubic-bezier(0.22, 0.9, 0.3, 1)", fill: "forwards" }
    );
    anim.onfinish = onDone;
    return () => anim.cancel();
  }, [flight, onDone]);

  if (!flight) return null;

  const { card } = flight;
  const border = CLASS_BORDER[card.class_required] || "#6b7280";
  const dmgColor = DMG_TEXT[card.damage_type] || "#e5e7eb";

  return (
    <div
      ref={ref}
      className="card-fly-clone"
      style={{
        left: flight.from.left + flight.from.width / 2,
        top: flight.from.top + flight.from.height / 2,
        borderColor: border,
        boxShadow: "0 0 24px " + border + "66, 0 12px 32px rgba(0,0,0,0.6)",
      }}
    >
      {flight.skinUrl && (
        <div className="card-fly-art" style={{ backgroundImage: "url(" + flight.skinUrl + ")" }} />
      )}
      <div className="card-fly-body">
        <div className="card-fly-name">{card.name}</div>
        <div className="card-fly-meta">
          <span style={{ color: dmgColor }}>{DMG_LABELS[card.damage_type] || ""}</span>
          <span className="card-fly-cost">{card.cost} AP</span>
        </div>
      </div>
    </div>
  );
}
