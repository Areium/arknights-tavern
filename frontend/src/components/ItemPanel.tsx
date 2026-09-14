import { useState, useEffect, useCallback, useRef } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";
import ItemDetailCard from "./ItemDetailCard";

interface SceneItem {
  id: string;
  name: string;
  owner?: string;
  category?: string;
  rarity?: string;
}

export default function ItemPanel({ refreshKey }: { refreshKey?: number }) {
  const { activeSessionId } = useAppStore();
  const api = useApi();
  const [items, setItems] = useState<SceneItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [hoveredItem, setHoveredItem] = useState<string | null>(null);
  const [hoverAnchor, setHoverAnchor] = useState<DOMRect | null>(null);
  const [pinnedItem, setPinnedItem] = useState<string | null>(null);
  const [pinnedAnchor, setPinnedAnchor] = useState<DOMRect | null>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const previewItem = hoveredItem || pinnedItem;
  const previewAnchor = hoveredItem ? hoverAnchor : pinnedAnchor;

  const clearCloseTimer = () => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  };

  const handleMouseEnter = (itemId: string, el: HTMLElement) => {
    clearCloseTimer();
    setHoveredItem(itemId);
    setHoverAnchor(el.getBoundingClientRect());
  };

  const handleMouseLeave = () => {
    closeTimerRef.current = setTimeout(() => {
      setHoveredItem(null);
      setHoverAnchor(null);
    }, 250);
  };

  const handlePopupEnter = () => {
    clearCloseTimer();
  };

  const handlePopupLeave = () => {
    if (!pinnedItem) {
      setHoveredItem(null);
      setHoverAnchor(null);
    }
  };

  const handleTogglePin = () => {
    if (pinnedItem) {
      setPinnedItem(null);
      setPinnedAnchor(null);
    } else if (hoveredItem) {
      setPinnedItem(hoveredItem);
      setPinnedAnchor(hoverAnchor);
    }
  };

  const handlePinFromList = (itemId: string, el: HTMLElement) => {
    clearCloseTimer();
    const rect = el.getBoundingClientRect();
    if (pinnedItem === itemId) {
      setPinnedItem(null);
      setPinnedAnchor(null);
    } else {
      setPinnedItem(itemId);
      setPinnedAnchor(rect);
      setHoveredItem(itemId);
      setHoverAnchor(rect);
    }
  };

  const handleClosePreview = () => {
    clearCloseTimer();
    setHoveredItem(null);
    setHoverAnchor(null);
    setPinnedItem(null);
    setPinnedAnchor(null);
  };

  const loadItems = useCallback(async () => {
    if (!activeSessionId) {
      setItems([]);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await api.getSceneItems(activeSessionId);
      const list: SceneItem[] = (data.items || []).map((i: any) => ({
        id: i.id || i.name,
        name: i.name || i.id,
        owner: i.owner,
        category: i.category,
        rarity: i.rarity,
      }));
      setItems(list);
    } catch {
      // Backend may not support items yet — show empty state
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [activeSessionId, api]);

  useEffect(() => {
    loadItems();
    // Clear preview state on session switch
    setHoveredItem(null);
    setHoverAnchor(null);
    setPinnedItem(null);
    setPinnedAnchor(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadItems, refreshKey]);

  if (!activeSessionId) {
    return (
      <div className="card">
        <h2 className="panel-title">场景物品</h2>
        <p className="text-gray-500 text-sm text-center py-4">
          请先选择或创建会话
        </p>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h2 className="panel-title mb-0">
          场景物品
          {items.length > 0 && (
            <span className="ml-1.5 text-xs text-gray-500 font-normal">
              ({items.length})
            </span>
          )}
        </h2>
        <div className="flex gap-1">
          <button
            onClick={loadItems}
            className="text-xs text-gray-500 hover:text-gray-300"
            disabled={loading}
          >
            {loading ? "..." : "刷新"}
          </button>
        </div>
      </div>

      {error && (
        <p className="text-red-400 text-xs mb-2">加载失败: {error}</p>
      )}

      <div className="space-y-1.5 max-h-40 overflow-y-auto">
        {!loading && items.length === 0 && (
          <p className="text-gray-500 text-sm text-center py-4">
            场景暂无物品
            <br />
            <span className="text-xs text-gray-600">物品由剧情发展自动增减</span>
          </p>
        )}
        {items.map((item) => (
          <div
            key={item.id}
            onMouseEnter={(e) => handleMouseEnter(item.id, e.currentTarget)}
            onMouseLeave={handleMouseLeave}
            className="flex items-center justify-between px-3 py-2 rounded-lg text-sm bg-gray-700/50 cursor-default"
          >
            <div className="min-w-0 flex-1">
              <span className="font-medium truncate block">{item.name}</span>
              {item.owner && (
                <span className="text-xs text-amber-400/70">
                  {item.owner}
                </span>
              )}
              {item.rarity && (
                <span className="text-xs text-gray-500 ml-1.5">
                  {item.rarity}
                </span>
              )}
            </div>
            <div className="flex gap-1 shrink-0 ml-2">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handlePinFromList(item.id, e.currentTarget.parentElement!);
                }}
                className={`text-xs px-1 rounded transition-colors ${
                  pinnedItem === item.id
                    ? "bg-amber-600/30 text-amber-300"
                    : "text-gray-600 hover:text-gray-300"
                }`}
                title={pinnedItem === item.id ? "取消固定" : "固定查看详情"}
              >
                📌
              </button>
            </div>
          </div>
        ))}
      </div>

      {previewItem && previewAnchor && (
        <ItemDetailCard
          itemId={previewItem}
          anchorRect={previewAnchor}
          pinned={!!pinnedItem}
          onTogglePin={handleTogglePin}
          onClose={handleClosePreview}
          onMouseEnter={handlePopupEnter}
          onMouseLeave={handlePopupLeave}
        />
      )}
    </div>
  );
}
