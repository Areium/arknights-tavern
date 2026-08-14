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

  // Edit mode
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [hasOverrides, setHasOverrides] = useState(false);
  const [editMeta, setEditMeta] = useState<Record<string, any>>({});
  const [editContent, setEditContent] = useState("");
  const [editTags, setEditTags] = useState("");
  const [editAttrs, setEditAttrs] = useState<Record<string, number>>({});
  const [editRels, setEditRels] = useState("");
  // 成长（等级/XP）+ 派生战斗数值（会话覆盖合并后）
  const [growth, setGrowth] = useState<{ level: number; xp: number } | null>(null);
  const [combatStats, setCombatStats] = useState<Record<string, number> | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setEditing(false);
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

  const handleStartEdit = async () => {
    if (!activeSessionId) return;
    setLoading(true);
    try {
      const merged = await api.getCharacterMerged(activeSessionId, characterId);
      const meta = merged.metadata || {};
      setEditMeta(meta);
      setEditContent(merged.content || "");
      setEditTags((meta.tags || []).join("、"));
      setEditAttrs(meta.attributes || {});
      setEditRels(
        Object.entries(meta.relationships || {})
          .map(([k, v]) => `${k}: ${v}`)
          .join("\n")
      );
      setHasOverrides(merged.has_overrides);
      setEditing(true);
    } catch (err: any) {
      alert("无法加载编辑数据: " + (err.message || "未知错误"));
    } finally {
      setLoading(false);
    }
  };

  const handleSaveEdit = async () => {
    if (!activeSessionId) return;
    setSaving(true);
    try {
      const overrides: Record<string, any> = { metadata: {} };

      // Tags
      const newTags = editTags
        .split(/[、,]/)
        .map((t) => t.trim())
        .filter(Boolean);
      if (JSON.stringify(newTags) !== JSON.stringify(data?.metadata?.tags)) {
        (overrides.metadata as any).tags = newTags;
      }

      // Attributes
      const origAttrs = data?.metadata?.attributes || {};
      const changedAttrs: Record<string, number> = {};
      for (const [k, v] of Object.entries(editAttrs)) {
        if (v !== origAttrs[k]) changedAttrs[k] = v;
      }
      if (Object.keys(changedAttrs).length > 0) {
        (overrides.metadata as any).attributes = changedAttrs;
      }

      // Relationships
      const newRels: Record<string, string> = {};
      editRels.split("\n").forEach((line) => {
        const idx = line.indexOf(":");
        if (idx > 0) {
          newRels[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
        }
      });
      if (
        JSON.stringify(newRels) !==
        JSON.stringify(data?.metadata?.relationships || {})
      ) {
        (overrides.metadata as any).relationships = newRels;
      }

      // Simple fields
      for (const field of ["class", "race", "faction"]) {
        const newVal = (editMeta as any)[field];
        if (newVal && newVal !== data?.metadata?.[field]) {
          (overrides.metadata as any)[field] = newVal;
        }
      }

      // Content
      if (editContent !== (data?.content || "")) {
        overrides.content = editContent;
      }

      // Remove empty metadata if no changes
      if (Object.keys(overrides.metadata as any).length === 0) {
        delete overrides.metadata;
      }

      if (!overrides.metadata && overrides.content === undefined) {
        // No changes — delete override if exists
        if (hasOverrides) {
          await api.deleteCharacterOverride(activeSessionId, characterId);
        }
      } else {
        await api.setCharacterOverride(activeSessionId, characterId, overrides);
      }

      setHasOverrides(!!overrides.metadata || overrides.content !== undefined);
      setEditing(false);
    } catch (err: any) {
      alert("保存失败: " + (err.message || "未知错误"));
    } finally {
      setSaving(false);
    }
  };

  const handleRevert = async () => {
    if (!activeSessionId || !hasOverrides) return;
    if (!confirm("确定还原为模板？所有修改将丢失。")) return;
    try {
      await api.deleteCharacterOverride(activeSessionId, characterId);
      setHasOverrides(false);
      setEditing(false);
      // Refresh from template
      const d = await api.getCharacter(characterId);
      setData(d);
    } catch (err: any) {
      alert("还原失败: " + (err.message || "未知错误"));
    }
  };

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
          {hasOverrides && (
            <span className="text-xs px-1.5 py-0.5 rounded bg-amber-600/30 text-amber-300 shrink-0">
              已修改
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0 ml-2">
          {activeSessionId && !editing && (
            <button
              onClick={handleStartEdit}
              className="text-xs px-2 py-0.5 rounded text-gray-400 hover:text-gray-200 hover:bg-gray-700 transition-colors"
            >
              编辑
            </button>
          )}
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

        {data && !editing && (
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

        {/* Edit form */}
        {editing && (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-2">
              <div>
                <label className="text-[10px] text-gray-500">职业</label>
                <input
                  className="input text-xs py-1"
                  value={editMeta.class || ""}
                  onChange={(e) => setEditMeta({ ...editMeta, class: e.target.value })}
                />
              </div>
              <div>
                <label className="text-[10px] text-gray-500">种族</label>
                <input
                  className="input text-xs py-1"
                  value={editMeta.race || ""}
                  onChange={(e) => setEditMeta({ ...editMeta, race: e.target.value })}
                />
              </div>
              <div>
                <label className="text-[10px] text-gray-500">势力</label>
                <input
                  className="input text-xs py-1"
                  value={editMeta.faction || ""}
                  onChange={(e) => setEditMeta({ ...editMeta, faction: e.target.value })}
                />
              </div>
            </div>

            <div>
              <label className="text-[10px] text-gray-500">标签（、分隔）</label>
              <input
                className="input text-xs py-1"
                value={editTags}
                onChange={(e) => setEditTags(e.target.value)}
              />
            </div>

            <div>
              <label className="text-[10px] text-gray-500 mb-1 block">属性</label>
              <div className="grid grid-cols-4 gap-1.5">
                {Object.entries(ATTR_LABELS).map(([key, label]) => (
                  <div key={key} className="flex flex-col items-center gap-0.5">
                    <span className="text-[10px] text-gray-500">{label}</span>
                    <input
                      className="input text-xs py-0.5 w-full text-center"
                      type="number"
                      min={1}
                      max={10}
                      value={editAttrs[key] ?? ""}
                      onChange={(e) =>
                        setEditAttrs({
                          ...editAttrs,
                          [key]: parseInt(e.target.value) || 0,
                        })
                      }
                    />
                  </div>
                ))}
              </div>
            </div>

            <div>
              <label className="text-[10px] text-gray-500">
                关系（每行一个：名字: 描述）
              </label>
              <textarea
                className="input text-xs py-1"
                rows={4}
                value={editRels}
                onChange={(e) => setEditRels(e.target.value)}
              />
            </div>

            <div>
              <label className="text-[10px] text-gray-500">角色背景</label>
              <textarea
                className="input text-xs py-1"
                rows={6}
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
              />
            </div>

            <div className="flex gap-2">
              <button
                onClick={handleSaveEdit}
                disabled={saving}
                className="btn-primary text-xs px-3 py-1.5"
              >
                {saving ? "保存中..." : "保存修改"}
              </button>
              <button
                onClick={() => setEditing(false)}
                className="text-xs px-3 py-1.5 rounded bg-gray-700 text-gray-300 hover:bg-gray-600"
              >
                取消
              </button>
              {hasOverrides && (
                <button
                  onClick={handleRevert}
                  className="text-xs px-3 py-1.5 rounded bg-red-800/30 text-red-300 hover:bg-red-800/50 ml-auto"
                >
                  还原为模板
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
