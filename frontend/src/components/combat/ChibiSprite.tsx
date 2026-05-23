import type { CombatUnitDTO } from "../../types";

/*
 * Detailed CSS pixel-art chibi placeholder.
 * Each class has a distinct silhouette created with box-shadows and gradients.
 * When real sprite assets are available, this component becomes a simple <img>.
 */

const CLASS_COLORS: Record<string, { primary: string; secondary: string; accent: string }> = {
  "先锋":   { primary: "#d4a574", secondary: "#b8875a", accent: "#f0d4b0" },
  "近卫":   { primary: "#c44b3c", secondary: "#9a2d28", accent: "#e8786a" },
  "重装":   { primary: "#4a6b8a", secondary: "#364f6b", accent: "#7ea4c4" },
  "狙击":   { primary: "#3c8c4a", secondary: "#2a6b35", accent: "#6ab878" },
  "术师":   { primary: "#8b5ca8", secondary: "#6b3f85", accent: "#b890d0" },
  "医疗":   { primary: "#5c9a8b", secondary: "#3d7065", accent: "#84bfb2" },
  "辅助":   { primary: "#c4a83c", secondary: "#9e8628", accent: "#e8d068" },
  "特种":   { primary: "#6b5c8a", secondary: "#4a3f6b", accent: "#9e90c0" },
};

const TEAM_BORDER: Record<string, string> = {
  player: "0 0 10px rgba(0, 180, 216, 0.4)",
  enemy: "0 0 10px rgba(231, 76, 60, 0.4)",
};

const TEAM_BASE_COLOR: Record<string, string> = {
  player: "#0d1830",
  enemy: "#180d0d",
};

// Class weapon shapes rendered as CSS triangles/rectangles
function ChibiWeapon({ charClass, direction }: { charClass: string; direction: number }) {
  switch (charClass) {
    case "近卫":
      return <div className="absolute -right-1 top-3 w-3 h-1 bg-gray-300 rounded-r" style={{ transform: `rotate(${direction * 90 - 45}deg)`, transformOrigin: "left center" }} />;
    case "狙击":
      return <div className="absolute -right-2 top-2 w-5 h-0.5 bg-gray-400 rounded" style={{ transform: `rotate(${direction * 90 - 30}deg)`, transformOrigin: "left center" }} />;
    case "重装":
      return <div className="absolute -left-1 top-3 w-4 h-4 border-2 border-gray-400 rounded-sm bg-transparent" />;
    case "术师":
      return <div className="absolute -right-1 top-2 w-2 h-3 bg-purple-300 rounded-full shadow-[0_0_4px_rgba(168,85,247,0.6)]" />;
    case "医疗":
      return <div className="absolute -right-1 top-3 w-2 h-2 bg-green-300 rounded-full shadow-[0_0_3px_rgba(74,222,128,0.6)]" />;
    case "先锋":
      return <div className="absolute -right-1 top-3 w-3 h-0.5 bg-amber-300 rounded" style={{ transform: `rotate(${direction * 90}deg)`, transformOrigin: "left center" }} />;
    case "辅助":
      return <div className="absolute -right-1 top-2 w-2 h-3 border border-amber-300 rounded-sm bg-transparent shadow-[0_0_3px_rgba(250,204,21,0.4)]" />;
    case "特种":
      return <div className="absolute -right-1 top-3 w-2.5 h-0.5 bg-gray-300 rounded" />;
    default:
      return null;
  }
}

interface Props {
  unit: CombatUnitDTO;
  direction?: number;
  animation?: "idle" | "attack" | "hit" | "death";
  onClick?: () => void;
}

export default function ChibiSprite({ unit, direction = 1, animation = "idle", onClick }: Props) {
  const colors = CLASS_COLORS[unit.char_class] || CLASS_COLORS["近卫"];
  const borderGlow = TEAM_BORDER[unit.team] || "";
  const baseColor = TEAM_BASE_COLOR[unit.team] || "#111";

  const animClass =
    animation === "hit" ? "unit-hit-shake" :
    animation === "death" ? "opacity-30 scale-90 transition-all duration-500" :
    animation === "attack" ? "scale-110 transition-transform duration-200" :
    "";

  return (
    <button
      className={`relative cursor-pointer transition-transform ${animClass}`}
      style={{
        width: 48, height: 60,
        transform: `scaleY(${animation === "death" ? 0.3 : 1})`,
        filter: animation === "death" ? "grayscale(0.8)" : "",
      }}
      onClick={onClick}
      title={`${unit.name} (${unit.char_class})`}
    >
      {/* Shadow on ground */}
      <div
        className="absolute bottom-0 left-1/2 -translate-x-1/2 rounded-full"
        style={{
          width: 36, height: 8,
          background: "rgba(0,0,0,0.4)",
          boxShadow: "0 0 6px rgba(0,0,0,0.5)",
        }}
      />

      {/* Body */}
      <div
        className="absolute left-1/2 -translate-x-1/2"
        style={{
          bottom: 10, width: 28, height: 30,
          borderRadius: "6px 6px 2px 2px",
          background: `linear-gradient(180deg, ${colors.primary} 0%, ${colors.secondary} 100%)`,
          boxShadow: borderGlow,
        }}
      >
        {/* Armor detail line */}
        <div className="absolute top-1 left-1 right-1 h-0.5 bg-white/15 rounded" />
        {/* Belt */}
        <div className="absolute bottom-6 left-0 right-0 h-1 bg-white/20" />
      </div>

      {/* Head */}
      <div
        className="absolute left-1/2 -translate-x-1/2"
        style={{
          bottom: 38, width: 22, height: 24,
          borderRadius: "50% 50% 30% 30%",
          background: `linear-gradient(180deg, ${colors.accent} 0%, ${colors.secondary} 100%)`,
          border: `2px solid ${baseColor}`,
        }}
      >
        {/* Eyes */}
        <div className="absolute top-2 left-1 w-1.5 h-1.5 bg-white rounded-full" />
        <div className="absolute top-2 right-1 w-1.5 h-1.5 bg-white rounded-full" />
        {/* Pupils - always facing direction */}
        <div
          className="absolute top-2.5 w-1 h-1 bg-gray-900 rounded-full"
          style={{ left: direction === 0 || direction === 3 ? 2 : direction === 2 ? 8 : 15 }}
        />
        <div
          className="absolute top-2.5 w-1 h-1 bg-gray-900 rounded-full"
          style={{ right: direction === 0 || direction === 1 ? 2 : direction === 2 ? 2 : 2 }}
        />
      </div>

      {/* HP bar above head */}
      {unit.hp < unit.max_hp && (
        <div className="absolute -top-1 left-1/2 -translate-x-1/2 w-12">
          <div className="combat-hp-bar">
            <div
              className={`combat-hp-fill ${unit.hp / unit.max_hp > 0.5 ? "high" : unit.hp / unit.max_hp > 0.25 ? "medium" : "low"}`}
              style={{ width: `${Math.max(0, (unit.hp / unit.max_hp) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Weapon */}
      <ChibiWeapon charClass={unit.char_class} direction={direction} />

      {/* Direction arrow (deploy indicator) */}
      {animation === "idle" && (
        <div
          className="deploy-arrow absolute -top-3 left-1/2 -translate-x-1/2"
          style={{ transform: `translateX(-50%) rotate(${direction * 90}deg)` }}
        />
      )}
    </button>
  );
}
