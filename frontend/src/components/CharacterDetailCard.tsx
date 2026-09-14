import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";

interface CharacterDetail {
  metadata: Record<string, any>;
  content: string;
}

interface Props {
  characterId: string;
  anchorRect: DOMRect;
  pinned: boolean;
  onTogglePin: () => void;
  onClose: () => void;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
}

const CARD_W = 420;
const CARD_MAX_H = 560;
const GAP = 8;

const ATTR_LABELS: Record<string, string> = {
  strength: "力量",
  intelligence: "智力",
  emotional_stability: "情绪",
  combat_skill: "战斗",
  originium_arts: "源石",
  charisma: "魅力",
  endurance: "耐力",
  agility: "敏捷",
};

export default function CharacterDetailCard({
  characterId,
  anchorRect,
  pinned,
  onTogglePin,
  onClose,
  onMouseEnter,
  onMouseLeave,
}: Props) {
  const { activeSessionId } = useAppStore();
  const api = useApi();
  const [data, setData] = useState<CharacterDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // 会话统一管理角色设定与数值：详情卡仅只读展示（等级/XP + 派生战斗数值
  // 为会话合并后的结果），不提供对话内编辑入口
  const [growth, setGrowth] = useState<{ level: number; xp: number } | null>(null);
  const [combatStats, setCombatStats] = useState<Record<string, number> | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    api
      .getCharacter(characterId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err: any) => {
        if (!cancelled) setError(err.message || "加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [characterId, api]);

  // 会话活跃时拉取合并数据：等级/XP + 派生战斗数值
  useEffect(() => {
    if (!activeSessionId) {
      setGrowth(null);
      setCombatStats(null);
      return;
    }
    let cancelled = false;
    api
      .getCharacterMerged(activeSessionId, characterId)
      .then((merged: any) => {
        if (cancelled) return;
        setGrowth(merged.progress || null);
        setCombatStats(merged.combat_stats || null);
      })
      .catch(() => {
        if (!cancelled) { setGrowth(null); setCombatStats(null); }
      });
    return () => { cancelled = true; };
  }, [activeSessionId, characterId, api]);

  const vw = window.innerWidth;
  const vh = window.innerHeight;
  let left = anchorRect.right + GAP;
  if (left + CARD_W > vw - GAP) {
    left = anchorRect.left - CARD_W - GAP;
    if (left < GAP) left = GAP;
  }
  const cardH = Math.min(CARD_MAX_H, vh - GAP * 2);
  let top = anchorRect.top;
  if (top + cardH > vh - GAP) {
    top = vh - cardH - GAP;
  }
  if (top < GAP) top = GAP;

  const meta = data?.metadata;
  const attrs: Record<string, number> = meta?.attributes ?? {};
  const rels: Record<string, string> = meta?.relationships ?? {};
  const tags: string[] = meta?.tags ?? [];

  return createPortal(
    <div
      className="fixed z-[60] bg-gray-850 border border-gray-600 rounded-xl shadow-2xl flex flex-col"
      style={{ left, top, width: CARD_W, maxHeight: cardH }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <h3 className="text-base font-semibold truncate">
            {meta?.name || characterId}
          </h3>
        </div>
        <div className="flex items-center gap-1 shrink-0 ml-2">
          <button
            onClick={onTogglePin}
            className={`text-sm px-1.5 py-0.5 rounded transition-colors ${
              pinned
                ? "bg-amber-600/30 text-amber-300"
                : "text-gray-500 hover:text-gray-300"
            }`}
            title={pinned ? "取消固定" : "固定弹窗"}
          >
            📌
          </button>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300 text-lg leading-none px-1"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 text-sm">
        {loading && (
          <p className="text-gray-500 text-center py-8">加载中...</p>
        )}
        {error && <p className="text-red-400">{error}</p>}

        {data && (
          <>
            <div className="flex flex-wrap gap-1.5">
              {meta?.class && (
                <span className="px-2 py-0.5 rounded bg-blue-700/50 text-blue-200 text-xs">
                  {meta.class}
                </span>
              )}
              {meta?.race && (
                <span className="px-2 py-0.5 rounded bg-purple-700/50 text-purple-200 text-xs">
                  {meta.race}
                </span>
              )}
              {meta?.faction && (
                <span className="px-2 py-0.5 rounded bg-green-700/50 text-green-200 text-xs">
                  {meta.faction}
                </span>
              )}
            </div>

            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {tags.map((t: string) => (
                  <span
                    key={t}
                    className="px-1.5 py-0.5 rounded bg-gray-700/50 text-gray-300 text-xs"
                  >
                    {t}
                  </span>
                ))}
              </div>
            )}

            {Object.keys(attrs).length > 0 && (
              <div>
                <h4 className="text-xs text-gray-500 mb-1.5 font-medium">属性</h4>
                <div className="grid grid-cols-4 gap-1.5">
                  {Object.entries(attrs).map(([key, val]) => (
                    <div
                      key={key}
                      className="flex flex-col items-center px-1.5 py-1 rounded bg-gray-700/40 text-xs"
                    >
                      <span className="text-gray-300 text-[10px]">
                        {ATTR_LABELS[key] || key}
                      </span>
                      <span className="text-gray-200 font-mono">{val}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {growth && (
              <div>
                <h4 className="text-xs text-gray-500 mb-1.5 font-medium">成长</h4>
                <div className="px-2.5 py-2 rounded bg-gray-700/40">
                  <div className="flex justify-between items-center mb-1.5">
                    <span className="text-amber-300 font-bold text-sm">Lv.{growth.level}</span>
                    <span className="text-[10px] text-gray-500 font-mono">XP {growth.xp} / {growth.level * 100}</span>
                  </div>
                  <div className="h-1.5 bg-gray-600 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-amber-400 transition-all"
                      style={{ width: Math.min(100, (growth.xp / (growth.level * 100)) * 100) + "%" }}
                    />
                  </div>
                </div>
              </div>
            )}

            {combatStats && (
              <div>
                <h4 className="text-xs text-gray-500 mb-1.5 font-medium">战斗数值</h4>
                <div className="grid grid-cols-5 gap-1.5">
                  {[
                    ["生命", combatStats.hp],
                    ["物攻", combatStats.patk],
                    ["法攻", combatStats.matk],
                    ["治疗", combatStats.heal],
                    ["物防", combatStats.def],
                    ["法抗", combatStats.res],
                    ["速度", combatStats.spd],
                    ["命中", combatStats.hit],
                    ["闪避", combatStats.eva],
                    ["AP", combatStats.max_ap],
                  ].map(([label, val]) => (
                    <div key={label as string} className="flex flex-col items-center px-1 py-1 rounded bg-gray-700/40">
                      <span className="text-gray-400 text-[9px]">{label}</span>
                      <span className="text-gray-100 font-mono text-xs">{val}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {Object.keys(rels).length > 0 && (
              <div>
                <h4 className="text-xs text-gray-500 mb-1.5 font-medium">关系</h4>
                <div className="space-y-1">
                  {Object.entries(rels).map(([who, desc]) => (
                    <div key={who} className="px-2 py-1 rounded bg-gray-700/40 text-xs">
                      <span className="text-amber-300 font-medium">{who}</span>
                      <span className="text-gray-400"> — {desc as string}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {data.content && (
              <div>
                <h4 className="text-xs text-gray-500 mb-1.5 font-medium">背景</h4>
                <div className="text-xs text-gray-300 leading-relaxed whitespace-pre-wrap">
                  {data.content}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>,
    document.body
  );
}
