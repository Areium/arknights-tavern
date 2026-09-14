import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
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

/**
 * 物品详情浮卡 —— 仅只读展示。
 * 会话统一管理物品数据：对话内不提供编辑入口，物品增减由剧情/LLM 驱动。
 */
export default function ItemDetailCard({
  itemId,
  anchorRect,
  pinned,
  onTogglePin,
  onClose,
  onMouseEnter,
  onMouseLeave,
}: Props) {
  const api = useApi();
  const [data, setData] = useState<ItemDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
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

      {/* Body（只读） */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 text-sm">
        {loading && (
          <p className="text-gray-500 text-center py-8">加载中...</p>
        )}
        {error && <p className="text-red-400">{error}</p>}

        {data && (
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
      </div>
    </div>,
    document.body
  );
}
