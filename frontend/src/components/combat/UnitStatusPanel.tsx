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

const CLASS_COLORS: Record<string, string> = {
  "先锋": "#d4a574", "近卫": "#c44b3c", "重装": "#4a6b8a",
  "狙击": "#3c8c4a", "术师": "#8b5ca8", "医疗": "#5c9a8b",
  "辅助": "#c4a83c", "特种": "#6b5c8a",
};

function AvatarPlaceholder({ name, charClass }: { name: string; charClass: string }) {
  const bg = CLASS_COLORS[charClass] || "#555";
  const initial = name.charAt(0);
  return (
    <div
      className="w-10 h-10 rounded-lg flex items-center justify-center text-sm font-bold text-white/90 flex-shrink-0"
      style={{ backgroundColor: bg, boxShadow: `0 0 8px ${bg}40` }}
    >
      {initial}
    </div>
  );
}

function HPBar({ current, max }: { current: number; max: number }) {
  const pct = Math.max(0, Math.min(1, current / max));
  const level = pct > 0.5 ? "high" : pct > 0.25 ? "medium" : "low";
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex-1 combat-hp-bar">
        <div
          className={`combat-hp-fill ${level}`}
          style={{ width: `${pct * 100}%` }}
        />
      </div>
      <span className="text-[10px] text-gray-500 font-mono w-12 text-right">
        {current}/{max}
      </span>
    </div>
  );
}

function APDots({ current, max, color }: { current: number; max: number; color?: string }) {
  return (
    <div className="flex gap-0.5">
      {Array.from({ length: max }, (_, i) => (
        <div
          key={i}
          className={`combat-ap-dot ${i < current ? "filled" : "bg-gray-800"}`}
          style={i < current ? { backgroundColor: color || "#00d4ff" } : {}}
        />
      ))}
    </div>
  );
}

export default function UnitStatusPanel({
  units, activeUnitId, selectedUnitId, team, sharedAp, sharedApMax, onUnitClick,
}: Props) {
  const filtered = team ? units.filter((u) => u.team === team) : units;
  const isPlayer = team === "player";
  const label = isPlayer ? "我方" : "敌方";
  const labelColor = isPlayer ? "text-combat-player" : "text-combat-enemy";

  return (
    <div className="flex flex-col gap-2">
      {/* Header */}
      <div className="text-[11px] font-bold text-gray-400 uppercase tracking-widest border-b border-combat-divider pb-1.5 font-display">
        {label}
      </div>

      {/* Shared AP (player only) */}
      {isPlayer && sharedAp !== undefined && sharedApMax !== undefined && (
        <div className="flex items-center gap-2 px-1">
          <span className="text-[9px] text-gray-500 w-10">共用</span>
          <APDots current={sharedAp} max={sharedApMax} color="#ffffff" />
        </div>
      )}

      {/* Units */}
      {filtered.map((u) => {
        const isActive = u.unit_id === activeUnitId;
        const isSelected = u.unit_id === selectedUnitId;
        const dead = !u.is_alive;

        let borderClass = "border-combat-border bg-surface-card/60";
        if (dead) borderClass = "border-gray-800 bg-gray-900/20 opacity-45";
        else if (isActive)
          borderClass = isPlayer
            ? "border-combat-player bg-cyan-950/30 shadow-[0_0_8px_rgba(0,180,216,0.2)]"
            : "border-combat-enemy bg-red-950/30 shadow-[0_0_8px_rgba(231,76,60,0.2)]";
        else if (isSelected)
          borderClass = isPlayer
            ? "ring-1 ring-combat-player border-combat-player bg-surface-hover"
            : "ring-1 ring-combat-enemy border-combat-enemy bg-surface-hover";

        return (
          <div
            key={u.unit_id}
            onClick={() => onUnitClick?.(u.unit_id)}
            className={`p-2 rounded-lg border transition-all cursor-pointer hover:brightness-110 ${borderClass}`}
          >
            <div className="flex items-center gap-2">
              <AvatarPlaceholder name={u.name} charClass={u.char_class} />
              <div className="flex-1 min-w-0">
                <div className="flex justify-between items-center">
                  <span className={`text-xs font-bold truncate ${dead ? "text-gray-600" : "text-gray-200"}`}>
                    {u.name}
                  </span>
                  <span className="text-[9px] text-gray-600 ml-1 flex-shrink-0">{u.char_class}</span>
                </div>
                <div className="mt-1">
                  <HPBar current={u.hp} max={u.max_hp} />
                </div>
                {u.is_alive && (
                  <div className="mt-1 flex justify-between items-center">
                    <APDots current={u.personal_ap} max={u.max_personal_ap} />
                    <span className="text-[9px] text-gray-600">{u.mobility}速</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
