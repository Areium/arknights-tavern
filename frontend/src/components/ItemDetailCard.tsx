import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";

interface ItemDetail {
  metadata: Record<string, any>;
  content: string;
}

interface Props {
  itemId: string;
  anchorRect: DOMRect;
  pinned: boolean;
  onTogglePin: () => void;
  onClose: () => void;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
}

const CARD_W = 400;
const CARD_MAX_H = 520;
const GAP = 8;

const RARITY_MAP: Record<string, string> = {
  common: "普通",
  uncommon: "精良",
  rare: "稀有",
  epic: "史诗",
  legendary: "传说",
};

const RARITY_COLORS: Record<string, string> = {
  common: "bg-gray-600/50 text-gray-200",
  uncommon: "bg-green-700/50 text-green-200",
  rare: "bg-blue-700/50 text-blue-200",
  epic: "bg-purple-700/50 text-purple-200",
  legendary: "bg-amber-700/50 text-amber-200",
};

const CATEGORY_MAP: Record<string, string> = {
  equipment: "装备",
  consumable: "消耗品",
  key_item: "关键物品",
  accessory: "饰品",
  document: "文书",
  material: "材料",
};

export default function ItemDetailCard({
  itemId,
  anchorRect,
  pinned,
  onTogglePin,
  onClose,
  onMouseEnter,
  onMouseLeave,
}: Props) {
  const { activeSessionId } = useAppStore();
  const api = useApi();
  const [data, setData] = useState<ItemDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Edit mode
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [hasOverrides, setHasOverrides] = useState(false);
  const [editMeta, setEditMeta] = useState<Record<string, any>>({});
  const [editContent, setEditContent] = useState("");
  const [editEffects, setEditEffects] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setEditing(false);
    api
      .getItem(itemId)
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
  }, [itemId, api]);

  const handleStartEdit = async () => {
    if (!activeSessionId) return;
    setLoading(true);
    try {
      const merged = await api.getItemMerged(activeSessionId, itemId);
      const meta = merged.metadata || {};
      setEditMeta(meta);
      setEditContent(merged.content || "");
      setEditEffects((meta.effects || []).join("\n"));
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

      // Effects
      const newEffects = editEffects
        .split("\n")
        .map((t) => t.trim())
        .filter(Boolean);
      if (JSON.stringify(newEffects) !== JSON.stringify(data?.metadata?.effects)) {
        (overrides.metadata as any).effects = newEffects;
      }

      // Simple text fields
      for (const field of [
        "name",
        "alias",
        "category",
        "rarity",
        "owner",
        "location",
        "source",
        "condition",
        "usable",
      ]) {
        const newVal = (editMeta as any)[field];
        if (newVal !== undefined && newVal !== data?.metadata?.[field]) {
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
        if (hasOverrides) {
          await api.deleteItemOverride(activeSessionId, itemId);
        }
      } else {
        await api.setItemOverride(activeSessionId, itemId, overrides);
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
      await api.deleteItemOverride(activeSessionId, itemId);
      setHasOverrides(false);
      setEditing(false);
      const d = await api.getItem(itemId);
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
  const effects: string[] = meta?.effects ?? [];
  const rarity = meta?.rarity ?? "";
  const category = meta?.category ?? "";

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
            {meta?.name || itemId}
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
            {/* Badges: rarity + category + condition */}
            <div className="flex flex-wrap gap-1.5">
              {rarity && (
                <span
                  className={`px-2 py-0.5 rounded text-xs ${
                    RARITY_COLORS[rarity] || "bg-gray-700/50 text-gray-200"
                  }`}
                >
                  {RARITY_MAP[rarity] || rarity}
                </span>
              )}
              {category && (
                <span className="px-2 py-0.5 rounded bg-gray-700/50 text-gray-200 text-xs">
                  {CATEGORY_MAP[category] || category}
                </span>
              )}
              {meta?.usable && (
                <span className="px-2 py-0.5 rounded bg-green-700/30 text-green-300 text-xs">
                  可使用
                </span>
              )}
              {meta?.condition && (
                <span className="px-2 py-0.5 rounded bg-gray-700/30 text-gray-400 text-xs">
                  {meta.condition}
                </span>
              )}
            </div>

            {/* Owner & location */}
            {(meta?.owner || meta?.location || meta?.source) && (
              <div className="space-y-0.5 text-xs text-gray-400">
                {meta.owner && (
                  <div>
                    <span className="text-gray-500">持有者：</span>
                    <span className="text-amber-300">{meta.owner}</span>
                  </div>
                )}
                {meta.location && (
                  <div>
                    <span className="text-gray-500">位置：</span>
                    <span>{meta.location}</span>
                  </div>
                )}
                {meta.source && (
                  <div>
                    <span className="text-gray-500">来源：</span>
                    <span>{meta.source}</span>
                  </div>
                )}
              </div>
            )}

            {/* Effects */}
            {effects.length > 0 && (
              <div>
                <h4 className="text-xs text-gray-500 mb-1.5 font-medium">
                  效果
                </h4>
                <div className="space-y-1">
                  {effects.map((eff: string, i: number) => (
                    <div
                      key={i}
                      className="px-2 py-1 rounded bg-gray-700/40 text-xs text-gray-300"
                    >
                      {eff}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Content */}
            {data.content && (
              <div>
                <h4 className="text-xs text-gray-500 mb-1.5 font-medium">
                  详情
                </h4>
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
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] text-gray-500">名称</label>
                <input
                  className="input text-xs py-1"
                  value={editMeta.name || ""}
                  onChange={(e) => setEditMeta({ ...editMeta, name: e.target.value })}
                />
              </div>
              <div>
                <label className="text-[10px] text-gray-500">别名</label>
                <input
                  className="input text-xs py-1"
                  value={editMeta.alias || ""}
                  onChange={(e) => setEditMeta({ ...editMeta, alias: e.target.value })}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] text-gray-500">分类</label>
                <select
                  className="input text-xs py-1"
                  value={editMeta.category || ""}
                  onChange={(e) => setEditMeta({ ...editMeta, category: e.target.value })}
                >
                  <option value="">—</option>
                  {Object.entries(CATEGORY_MAP).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-gray-500">稀有度</label>
                <select
                  className="input text-xs py-1"
                  value={editMeta.rarity || ""}
                  onChange={(e) => setEditMeta({ ...editMeta, rarity: e.target.value })}
                >
                  <option value="">—</option>
                  {Object.entries(RARITY_MAP).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-2">
              <div>
                <label className="text-[10px] text-gray-500">持有者</label>
                <input
                  className="input text-xs py-1"
                  value={editMeta.owner || ""}
                  onChange={(e) => setEditMeta({ ...editMeta, owner: e.target.value })}
                />
              </div>
              <div>
                <label className="text-[10px] text-gray-500">位置</label>
                <input
                  className="input text-xs py-1"
                  value={editMeta.location || ""}
                  onChange={(e) => setEditMeta({ ...editMeta, location: e.target.value })}
                />
              </div>
              <div>
                <label className="text-[10px] text-gray-500">来源</label>
                <input
                  className="input text-xs py-1"
                  value={editMeta.source || ""}
                  onChange={(e) => setEditMeta({ ...editMeta, source: e.target.value })}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] text-gray-500">状态</label>
                <input
                  className="input text-xs py-1"
                  value={editMeta.condition || ""}
                  onChange={(e) => setEditMeta({ ...editMeta, condition: e.target.value })}
                />
              </div>
              <div className="flex items-end pb-1">
                <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={!!editMeta.usable}
                    onChange={(e) => setEditMeta({ ...editMeta, usable: e.target.checked })}
                    className="rounded"
                  />
                  可使用
                </label>
              </div>
            </div>

            <div>
              <label className="text-[10px] text-gray-500">效果（每行一个）</label>
              <textarea
                className="input text-xs py-1"
                rows={4}
                value={editEffects}
                onChange={(e) => setEditEffects(e.target.value)}
              />
            </div>

            <div>
              <label className="text-[10px] text-gray-500">物品详情</label>
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
