import { useEffect, useRef, useState } from "react";

interface CombatEvent {
  type: string;
  data: Record<string, any>;
}

interface Props {
  events: CombatEvent[];
}

function formatEvent(ev: CombatEvent): string {
  switch (ev.type) {
    case "round_start":
      return `=== Round ${ev.data.round || "?"} ===`;
    case "turn_start": {
      const team = ev.data.team === "player" ? "我方" : "敌方";
      return `> ${ev.data.name || "?"} (${team}) 的回合`;
    }
    case "damage":
      return `${ev.data.caster || "?"} 使用 [${ev.data.card || "?"}] -> ${ev.data.target || "?"}: -${ev.data.damage || 0} [${ev.data.hit_result || ""}]`;
    case "heal":
      return `${ev.data.caster || "?"} 治疗 ${ev.data.target || "?"}: +${ev.data.amount || 0}`;
    case "death":
      return `DEAD  ${ev.data.name || "?"} 已阵亡`;
    case "battle_end":
      return `=== ${ev.data.winner === "player" ? "胜利" : "失败"}! ===`;
    case "error":
      return `ERR: ${ev.data.msg || "?"}`;
    default:
      return `${ev.type}: ${JSON.stringify(ev.data)}`;
  }
}

function eventColor(type: string): string {
  switch (type) {
    case "damage": return "text-red-400";
    case "heal": return "text-green-400";
    case "death": return "text-purple-400";
    case "turn_start": return "text-gray-300";
    case "round_start": return "text-yellow-400 font-bold";
    case "battle_end": return "text-yellow-300 font-bold";
    case "error": return "text-yellow-500";
    default: return "text-gray-500";
  }
}

export default function CombatEventLog({ events }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  return (
    <div className="h-32 overflow-y-auto border border-gray-700 rounded bg-gray-950/80 p-2">
      <div className="text-[10px] text-gray-500 uppercase mb-1">Combat Log</div>
      {events.map((ev, i) => (
        <div key={i} className={`text-[11px] font-mono leading-relaxed ${eventColor(ev.type)}`}>
          {formatEvent(ev)}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
