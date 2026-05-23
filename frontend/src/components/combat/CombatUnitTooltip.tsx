import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import type { CombatUnitDTO } from "../../types";

const TOOLTIP_W = 300;
const GAP = 8;

const ATTR_LABELS: Record<string, string> = {
  physical_strength: "物理强度",
  mobility: "战场机动",
  physiological_tolerance: "生理耐受",
  tactical_planning: "战术规划",
  combat_skill: "战斗技巧",
  originium_arts_assimilation: "源石技艺",
  emotional_stability: "情绪稳定",
  charisma: "魅力",
};

const ATTR_ORDER = [
  "physical_strength", "mobility", "physiological_tolerance", "tactical_planning",
  "combat_skill", "originium_arts_assimilation", "emotional_stability", "charisma",
];

function AttrBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value / 10));
  const color = value >= 8 ? "bg-yellow-500" : value >= 6 ? "bg-green-500" : value >= 4 ? "bg-blue-500" : "bg-gray-500";
  return (
    <div className="flex items-center gap-1">
      <div className="w-12 h-1.5 bg-gray-800 rounded overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${pct * 100}%` }} />
      </div>
      <span className="text-[10px] text-gray-300 w-3 text-right">{value}</span>
    </div>
  );
}

interface Props {
  unit: CombatUnitDTO;
  anchorRect: DOMRect;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
}

export default function CombatUnitTooltip({ unit, anchorRect, onMouseEnter, onMouseLeave }: Props) {
  const dismissRef = useRef<ReturnType<typeof setTimeout>>();

  const handleMouseEnter = () => {
    if (dismissRef.current) clearTimeout(dismissRef.current);
    onMouseEnter?.();
  };

  const handleMouseLeave = () => {
    dismissRef.current = setTimeout(() => onMouseLeave?.(), 100);
  };

  useEffect(() => {
    return () => {
      if (dismissRef.current) clearTimeout(dismissRef.current);
    };
  }, []);

  const vw = window.innerWidth;
  const vh = window.innerHeight;
  let left = anchorRect.right + GAP;
  if (left + TOOLTIP_W > vw - GAP) {
    left = anchorRect.left - TOOLTIP_W - GAP;
    if (left < GAP) left = GAP;
  }
  const maxH = Math.min(420, vh - GAP * 2);
  let top = anchorRect.top;
  if (top + maxH > vh - GAP) {
    top = vh - maxH - GAP;
  }
  if (top < GAP) top = GAP;

  const teamColor = unit.team === "player" ? "text-cyan-400" : "text-red-400";
  const hasAttrs = unit.attributes && Object.keys(unit.attributes).length > 0;

  return createPortal(
    <div
      className="fixed z-[70] bg-gray-850 border border-gray-600 rounded-lg shadow-2xl overflow-hidden flex flex-col"
      style={{ left, top, width: TOOLTIP_W, maxHeight: maxH }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700 shrink-0 bg-gray-800/50">
        <span className={`text-sm font-bold ${teamColor}`}>{unit.name}</span>
        <span className="text-[10px] text-gray-500 bg-gray-700 px-1.5 py-0.5 rounded">
          {unit.char_class}
        </span>
      </div>

      <div className="px-3 py-2 overflow-y-auto text-xs space-y-2">
        {/* Raw attributes */}
        {hasAttrs ? (
          <div>
            <div className="text-[10px] text-gray-500 mb-1 uppercase tracking-wider">属性</div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
              {ATTR_ORDER.map((key) => {
                const val = unit.attributes![key] ?? 0;
                const label = ATTR_LABELS[key] || key;
                return (
                  <div key={key} className="flex items-center justify-between gap-1">
                    <span className="text-[10px] text-gray-400 w-12 shrink-0">{label}</span>
                    <div className="flex-1 min-w-0">
                      <AttrBar value={val} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="text-[10px] text-gray-600 italic">无属性数据</div>
        )}

        {/* Derived combat stats */}
        <div>
          <div className="text-[10px] text-gray-500 mb-1 uppercase tracking-wider">战斗数值</div>
          <div className="grid grid-cols-3 gap-x-2 gap-y-0.5">
            {[
              ["HP", `${unit.hp}/${unit.max_hp}`],
              ["物理攻击", unit.patk],
              ["法术攻击", unit.matk],
              ["防御", unit.def],
              ["法术抗性", unit.res],
              ["速度", unit.spd],
              ["命中", unit.hit],
              ["闪避", unit.eva],
              ["AP", `${unit.personal_ap}/${unit.max_personal_ap}`],
            ].map(([label, val]) => (
              <div key={label} className="flex justify-between gap-1">
                <span className="text-[10px] text-gray-500">{label}</span>
                <span className="text-[10px] text-gray-300 font-mono">{val}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Items */}
        <div>
          <div className="text-[10px] text-gray-500 mb-1 uppercase tracking-wider">携带物品</div>
          <div className="text-[10px] text-gray-600 italic">暂未携带物品</div>
        </div>
      </div>
    </div>,
    document.body
  );
}
