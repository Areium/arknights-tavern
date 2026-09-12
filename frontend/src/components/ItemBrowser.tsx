import { useState, useEffect, useRef } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";
import { useDialogMinimize } from "../hooks/useDialogMinimize";
import ItemDetailCard from "./ItemDetailCard";

interface AvailableItem {
  id: string;
  name: string;
}

export default function ItemBrowser({
  open,
  onClose,
  onAdded,
}: {
  open: boolean;
  onClose: () => void;
  onAdded?: () => void;
}) {
  const { activeSessionId } = useAppStore();
  const api = useApi();
  const [items, setItems] = useState<AvailableItem[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [addingId, setAddingId] = useState<string | null>(null);

  const [hoveredItem, setHoveredItem] = useState<string | null>(null);
  const [hoverAnchor, setHoverAnchor] = useState<DOMRect | null>(null);
  const [pinnedItem, setPinnedItem] = useState<string | null>(null);
  const [pinnedAnchor, setPinnedAnchor] = useState<DOMRect | null>(null);
  // 最小化：与关闭独立，最小化后 DOM 保留（搜索词/滚动位置不丢）
  const dialog = useDialogMinimize("item-browser", "浏览物品", open);
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

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    api
      .getItems()
      .then((data) => {
        if (!cancelled) setItems(data);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, api]);

  const handleAdd = async (itemId: string) => {
    if (!activeSessionId) return;
    setAddingId(itemId);
    try {
      await api.addSceneItem(activeSessionId, itemId);
      onAdded?.();
    } catch (err: any) {
      alert("添加失败: " + err.message);
    } finally {
      setAddingId(null);
    }
  };

  const filtered = search.trim()
    ? items.filter((i) =>
        i.name.toLowerCase().includes(search.toLowerCase())
      )
    : items;

  if (!open) return null;

  return (
    <div className={`fixed inset-0 z-50 flex items-center justify-center bg-black/60 ${dialog.minimizedClass}`}>
      <div
        ref={dialog.containerRef}
        tabIndex={-1}
        className="bg-gray-800 border border-gray-700 rounded-xl w-[480px] max-h-[600px] flex flex-col shadow-2xl outline-none"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700">
          <h2 className="text-base font-semibold">浏览物品</h2>
          <div className="flex items-center gap-1">
            <button
              onClick={dialog.minimize}
              className="text-gray-500 hover:text-gray-300 text-lg leading-none px-1"
              title="最小化（保留搜索词与滚动位置）"
              aria-label="最小化对话框"
            >
              —
            </button>
            <button
              onClick={onClose}
              className="text-gray-500 hover:text-gray-300 text-lg leading-none px-1"
              title="关闭"
              aria-label="关闭对话框"
            >
              ✕
            </button>
          </div>
        </div>

        <div className="px-5 pt-3 pb-2">
          <input
            className="input text-sm"
            placeholder="搜索物品..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
          />
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-2">
          {loading && (
            <p className="text-gray-500 text-sm text-center py-8">加载中...</p>
          )}
          {!loading && filtered.length === 0 && (
            <p className="text-gray-500 text-sm text-center py-8">
              {search.trim() ? "未找到匹配物品" : "暂无可用物品"}
            </p>
          )}
          {!loading &&
            filtered.map((item) => (
              <div
                key={item.id}
                onMouseEnter={(e) => handleMouseEnter(item.id, e.currentTarget)}
                onMouseLeave={handleMouseLeave}
                className="flex items-center justify-between px-3 py-2.5 rounded-lg hover:bg-gray-700/50 transition-colors"
              >
                <div>
                  <span className="text-sm font-medium">{item.name}</span>
                  <span className="text-xs text-gray-500 ml-2">{item.id}</span>
                </div>
                <div className="flex items-center gap-1">
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
                  <button
                    onClick={() => handleAdd(item.id)}
                    disabled={addingId === item.id}
                    className="text-xs px-3 py-1.5 rounded bg-green-700/30 text-green-300
                      hover:bg-green-700/50 disabled:opacity-50"
                  >
                    {addingId === item.id ? "添加中..." : "加入场景"}
                  </button>
                </div>
              </div>
            ))}
        </div>

        <div className="px-5 py-3 border-t border-gray-700 text-xs text-gray-500">
          共 {items.length} 个物品
          {search.trim() && `，筛选后 ${filtered.length} 个`}
        </div>
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
