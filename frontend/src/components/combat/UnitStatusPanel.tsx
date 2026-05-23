import type { CombatUnitDTO } from "../../types";

interface Props {
  units: CombatUnitDTO[];
  activeUnitId: string | null;
  selectedUnitId?: string | null;
  team?: "player" | "enemy";
  sharedAp?: number;
  sharedApMax?: number;
  onUnitClick?: (unitId: string) => void;
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

function APBar({ current, max, color }: { current: number; max: number; color?: string }) {
  const fill = color || "bg-cyan-500";
  return (
    <div className="flex gap-0.5">
      {Array.from({ length: max }, (_, i) => (
        <div
          key={i}
          className={`w-2.5 h-2.5 rounded-sm ${i < current ? fill : "bg-gray-700"}`}
        />
      ))}
    </div>
  );
}

export default function UnitStatusPanel({ units, activeUnitId, selectedUnitId, team, sharedAp, sharedApMax, onUnitClick }: Props) {
  const filtered = team ? units.filter((u) => u.team === team) : units;
  const isPlayer = team === "player";
  const labelColor = isPlayer ? "text-cyan-200" : "text-red-200";
  const activeBorder = isPlayer ? "border-cyan-400 bg-cyan-900/30" : "border-red-400 bg-red-900/30";

  return (
    <div className="flex flex-col gap-2">
      {/* Header */}
      <div className="text-xs font-bold text-gray-300 uppercase tracking-wider border-b border-gray-700 pb-1">
        {isPlayer ? "PLAYER" : "ENEMY"}
      </div>

      {/* Shared AP (player only) */}
      {isPlayer && sharedAp !== undefined && sharedApMax !== undefined && (
        <div className="flex items-center gap-1.5">
          <span className="text-[9px] text-gray-500 w-10">共用AP</span>
          <APBar current={sharedAp} max={sharedApMax} color="bg-white" />
        </div>
      )}

      {/* Units */}
      {filtered.map((u) => (
        <div
          key={u.unit_id}
          onClick={() => onUnitClick?.(u.unit_id)}
          className={`p-1.5 rounded border transition-colors cursor-pointer hover:brightness-110 ${
            u.unit_id === activeUnitId
              ? activeBorder
              : !u.is_alive
              ? "border-gray-700 bg-gray-900/20 opacity-50"
              : u.unit_id === selectedUnitId
              ? `${isPlayer ? "ring-2 ring-cyan-400" : "ring-2 ring-red-400"} bg-gray-800/60`
              : "border-gray-700 bg-gray-900/40"
          }`}
        >
          <div className="flex justify-between items-center">
            <span className={`text-xs font-bold ${u.is_alive ? labelColor : "text-gray-500"}`}>
              {u.name}
            </span>
            <span className="text-[9px] text-gray-500">{u.char_class}</span>
          </div>
          <div className="mt-1">
            <HPBar current={u.hp} max={u.max_hp} />
          </div>
          {u.is_alive && (
            <div className="mt-0.5 flex justify-between items-center">
              <div className="flex items-center gap-1">
                <span className="text-[8px] text-gray-600">AP</span>
                <APBar current={u.personal_ap} max={u.max_personal_ap} />
              </div>
              <span className="text-[9px] text-gray-600">{u.mobility}速</span>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
