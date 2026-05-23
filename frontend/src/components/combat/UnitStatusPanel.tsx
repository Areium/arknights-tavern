import type { CombatUnitDTO } from "../../types";

interface Props {
  units: CombatUnitDTO[];
  activeUnitId: string | null;
}

function HPBar({ current, max }: { current: number; max: number }) {
  const pct = Math.max(0, Math.min(1, current / max));
  const color = pct > 0.5 ? "bg-green-600" : pct > 0.25 ? "bg-yellow-600" : "bg-red-600";
  return (
    <div className="flex items-center gap-1">
      <div className="w-16 h-2 bg-gray-800 rounded overflow-hidden">
        <div className={`h-full ${color} transition-all`} style={{ width: `${pct * 100}%` }} />
      </div>
      <span className="text-[10px] text-gray-400 font-mono">{current}/{max}</span>
    </div>
  );
}

function APBar({ current, max }: { current: number; max: number }) {
  return (
    <div className="flex gap-0.5">
      {Array.from({ length: max }, (_, i) => (
        <div
          key={i}
          className={`w-2.5 h-2.5 rounded-sm ${i < current ? "bg-cyan-500" : "bg-gray-700"}`}
        />
      ))}
    </div>
  );
}

export default function UnitStatusPanel({ units, activeUnitId }: Props) {
  const players = units.filter((u) => u.team === "player");
  const enemies = units.filter((u) => u.team === "enemy");

  return (
    <div className="flex flex-col gap-2 p-2 w-56">
      <div className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-1">Player</div>
      {players.map((u) => (
        <div
          key={u.unit_id}
          className={`p-1.5 rounded border transition-colors ${
            u.unit_id === activeUnitId
              ? "border-cyan-400 bg-cyan-900/30"
              : !u.is_alive
              ? "border-gray-700 bg-gray-900/20 opacity-50"
              : "border-gray-700 bg-gray-900/40"
          }`}
        >
          <div className="flex justify-between items-center">
            <span className={`text-xs font-bold ${u.is_alive ? "text-cyan-200" : "text-gray-500"}`}>
              {u.name}
            </span>
            <span className="text-[9px] text-gray-500">{u.char_class}</span>
          </div>
          <div className="mt-1">
            <HPBar current={u.hp} max={u.max_hp} />
          </div>
          {u.is_alive && (
            <div className="mt-0.5 flex justify-between items-center">
              <APBar current={u.personal_ap} max={u.max_personal_ap} />
              <span className="text-[9px] text-gray-600">{u.mobility}速</span>
            </div>
          )}
        </div>
      ))}

      <div className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-1 mt-2">Enemy</div>
      {enemies.map((u) => (
        <div
          key={u.unit_id}
          className={`p-1.5 rounded border transition-colors ${
            u.unit_id === activeUnitId
              ? "border-red-400 bg-red-900/30"
              : !u.is_alive
              ? "border-gray-700 bg-gray-900/20 opacity-50"
              : "border-gray-700 bg-gray-900/40"
          }`}
        >
          <div className="flex justify-between items-center">
            <span className={`text-xs font-bold ${u.is_alive ? "text-red-200" : "text-gray-500"}`}>
              {u.name}
            </span>
            <span className="text-[9px] text-gray-500">{u.char_class}</span>
          </div>
          <div className="mt-1">
            <HPBar current={u.hp} max={u.max_hp} />
          </div>
          {u.is_alive && (
            <div className="mt-0.5">
              <APBar current={u.personal_ap} max={u.max_personal_ap} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
