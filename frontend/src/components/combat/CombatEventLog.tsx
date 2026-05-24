import { useEffect, useRef, useState } from "react";

interface CombatEvent {
  type: string;
  data: Record<string, any>;
}

interface Props {
  events: CombatEvent[];
}

const ICON_MAP: Record<string, string> = {
  round_start: "◎",
  turn_start: "▸",
  damage: "⚔",
  heal: "✦",
  death: "☠",
  battle_end: "◈",
  move: "↗",
  error: "⚠",
  block_attempt: "🛡",
  block_success: "✓",
  block_fail: "✗",
  intercept_prompt: "⚡",
  battle_start: "▶",
  card_played: "◆",
  turn_end: "◁",
};

function formatEvent(ev: CombatEvent): { icon: string; text: string } {
  const icon = ICON_MAP[ev.type] || "·";
  switch (ev.type) {
    case "battle_start":
      return { icon, text: `战斗开始 — ${ev.data.encounter || ""}` };
    case "round_start":
      return { icon, text: `第 ${ev.data.round || "?"} 回合` };
    case "turn_start": {
      const team = ev.data.team === "player" ? "Player" : "Enemy";
      return { icon, text: `${ev.data.name || "?"}（${team}）行动` };
    }
    case "damage": {
      const card = ev.data.card ? `「${ev.data.card}」` : "";
      return { icon, text: `${ev.data.caster || "?"} ${card} → ${ev.data.target || "?"}  -${ev.data.damage || 0} [${ev.data.hit_result || ""}]` };
    }
    case "heal":
      return { icon, text: `${ev.data.caster || "?"} 治疗 ${ev.data.target || "?"} +${ev.data.amount || 0}` };
    case "death":
      return { icon, text: `${ev.data.name || "?"} 被击倒` };
    case "move":
      return { icon, text: `${ev.data.name || "?"} 移动到 (${ev.data.to?.[0] || "?"},${ev.data.to?.[1] || "?"})` };
    case "block_attempt":
      return { icon, text: `${ev.data.name || "?"} 尝试挡刀...` };
    case "block_success":
      return { icon, text: `${ev.data.name || "?"} 成功挡刀！伤害重定向` };
    case "block_fail":
      return { icon, text: `${ev.data.name || "?"} 挡刀失败` };
    case "battle_end":
      return { icon, text: ev.data.winner === "player" ? "战斗胜利！" : "战斗失败..." };
    case "card_played": {
      const results = ev.data.results as number[] | undefined;
      const total = results?.reduce((a: number, b: number) => a + b, 0) ?? 0;
      return { icon, text: `${ev.data.caster || "?"} 使用「${ev.data.card || "?"}」→ (${ev.data.target?.join(",") || "?"}) 造成 ${total} 点伤害` };
    }
    case "turn_end":
      return { icon, text: `第 ${ev.data.round || "?"} 回合结束` };
    case "error":
      return { icon, text: `错误: ${ev.data.msg || "?"}` };
    default:
      return { icon, text: JSON.stringify(ev.data) };
  }
}

function eventStyle(type: string): string {
  switch (type) {
    case "damage":          return "text-dmg-physical";
    case "heal":            return "text-dmg-healing";
    case "death":           return "text-purple-400";
    case "turn_start":      return "text-gray-300";
    case "round_start":     return "text-combat-gold font-bold";
    case "battle_start":
    case "battle_end":      return "text-combat-gold font-bold";
    case "card_played":     return "text-combat-player";
    case "turn_end":        return "text-gray-500";
    case "block_success":   return "text-combat-player";
    case "block_fail":
    case "error":           return "text-combat-enemy";
    default:                return "text-gray-500";
  }
}

export default function CombatEventLog({ events }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useState(true);

  useEffect(() => {
    if (!collapsed) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [events.length, collapsed]);

  return (
    <div className="border border-combat-border rounded-lg bg-surface-dark/90 overflow-hidden">
      {/* Header — sticky, clickable toggle */}
      <button
        className="w-full flex items-center justify-between px-2 py-1.5 bg-surface-dark hover:bg-surface-hover transition-colors sticky top-0 z-10"
        onClick={() => setCollapsed((c) => !c)}
      >
        <span className="text-[10px] text-gray-600 uppercase tracking-widest font-display">
          Combat Log
        </span>
        <span className="text-[10px] text-gray-500">
          {collapsed ? `▶ ${events.length} events` : "▼"}
        </span>
      </button>

      {!collapsed && (
        <div className="h-32 overflow-y-auto p-2">
          {events.length === 0 && (
            <div className="text-[11px] text-gray-700 italic">等待战斗事件...</div>
          )}
          {events.slice(-80).map((ev, i) => {
            const { icon, text } = formatEvent(ev);
            return (
              <div key={i} className={`combat-log-entry text-[11px] font-mono leading-relaxed ${eventStyle(ev.type)}`}>
                <span className="log-icon text-[10px]">{icon}</span>
                <span>{text}</span>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}
