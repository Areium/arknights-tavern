import { useState, useEffect, useRef } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";
import CharacterDetailCard from "./CharacterDetailCard";

interface AvailableCharacter {
  id: string;
  name: string;
  title?: string;
}

export default function CharacterBrowser({
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
  const [characters, setCharacters] = useState<AvailableCharacter[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingName, setLoadingName] = useState<string | null>(null);

  const [hoveredChar, setHoveredChar] = useState<string | null>(null);
  const [hoverAnchor, setHoverAnchor] = useState<DOMRect | null>(null);
  const [pinnedChar, setPinnedChar] = useState<string | null>(null);
  const [pinnedAnchor, setPinnedAnchor] = useState<DOMRect | null>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const previewChar = hoveredChar || pinnedChar;
  const previewAnchor = hoveredChar ? hoverAnchor : pinnedAnchor;

  const clearCloseTimer = () => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  };

  const handleMouseEnter = (charId: string, el: HTMLElement) => {
    clearCloseTimer();
    setHoveredChar(charId);
    setHoverAnchor(el.getBoundingClientRect());
  };

  const handleMouseLeave = () => {
    closeTimerRef.current = setTimeout(() => {
      setHoveredChar(null);
      setHoverAnchor(null);
    }, 250);
  };

  const handlePopupEnter = () => {
    clearCloseTimer();
  };

  const handlePopupLeave = () => {
    if (!pinnedChar) {
      setHoveredChar(null);
      setHoverAnchor(null);
    }
  };

  const handleTogglePin = () => {
    if (pinnedChar) {
      setPinnedChar(null);
      setPinnedAnchor(null);
    } else if (hoveredChar) {
      setPinnedChar(hoveredChar);
      setPinnedAnchor(hoverAnchor);
    }
  };

  const handlePinFromList = (charId: string, el: HTMLElement) => {
    clearCloseTimer();
    const rect = el.getBoundingClientRect();
    if (pinnedChar === charId) {
      setPinnedChar(null);
      setPinnedAnchor(null);
    } else {
      setPinnedChar(charId);
      setPinnedAnchor(rect);
      setHoveredChar(charId);
      setHoverAnchor(rect);
    }
  };

  const handleClosePreview = () => {
    clearCloseTimer();
    setHoveredChar(null);
    setHoverAnchor(null);
    setPinnedChar(null);
    setPinnedAnchor(null);
  };

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    api
      .getCharacters()
      .then((data) => {
        if (!cancelled) setCharacters(data);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, api]);

  const handleAdd = async (key: string) => {
    if (!activeSessionId) return;
    setLoadingName(key);
    try {
      await api.loadCharacter(activeSessionId, key);
      onAdded?.();
    } catch (err: any) {
      alert("加载失败: " + err.message);
    } finally {
      setLoadingName(null);
    }
  };

  const filtered = search.trim()
    ? characters.filter((c) =>
        (c.name || c.title || c.id || "").toLowerCase().includes(search.toLowerCase())
      )
    : characters;

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-gray-800 border border-gray-700 rounded-xl w-[480px] max-h-[600px] flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700">
          <h2 className="text-base font-semibold">浏览角色</h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300 text-lg leading-none"
          >
            ✕
          </button>
        </div>

        {/* Search */}
        <div className="px-5 pt-3 pb-2">
          <input
            className="input text-sm"
            placeholder="搜索角色名..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
          />
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto px-5 py-2">
          {loading && (
            <p className="text-gray-500 text-sm text-center py-8">加载中...</p>
          )}

          {!loading && filtered.length === 0 && (
            <p className="text-gray-500 text-sm text-center py-8">
              {search.trim() ? "未找到匹配角色" : "暂无可用角色"}
            </p>
          )}

          {!loading &&
            filtered.map((c) => (
              <div
                key={c.id}
                onMouseEnter={(e) => handleMouseEnter(c.id, e.currentTarget)}
                onMouseLeave={handleMouseLeave}
                className="flex items-center justify-between px-3 py-2.5 rounded-lg hover:bg-gray-700/50 transition-colors"
              >
                <div>
                  <span className="text-sm font-medium">{c.name || c.title || c.id}</span>
                  <span className="text-xs text-gray-500 ml-2">{c.id}</span>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handlePinFromList(c.id, e.currentTarget.parentElement!);
                    }}
                    className={`text-xs px-1 rounded transition-colors ${
                      pinnedChar === c.id
                        ? "bg-amber-600/30 text-amber-300"
                        : "text-gray-600 hover:text-gray-300"
                    }`}
                    title={pinnedChar === c.id ? "取消固定" : "固定查看详情"}
                  >
                    📌
                  </button>
                  <button
                    onClick={() => handleAdd(c.id || c.name || c.title || "")}
                    disabled={loadingName === (c.id || c.name || c.title || "")}
                    className="text-xs px-3 py-1.5 rounded bg-green-700/30 text-green-300
                      hover:bg-green-700/50 disabled:opacity-50"
                  >
                    {loadingName === (c.id || c.name || c.title || "") ? "加载中..." : "加入场景"}
                  </button>
                </div>
              </div>
            ))}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-gray-700 text-xs text-gray-500">
          共 {characters.length} 个角色
          {search.trim() && `，筛选后 ${filtered.length} 个`}
        </div>
      </div>

      {/* Character detail popup */}
      {previewChar && previewAnchor && (
        <CharacterDetailCard
          characterId={previewChar}
          anchorRect={previewAnchor}
          pinned={!!pinnedChar}
          onTogglePin={handleTogglePin}
          onClose={handleClosePreview}
          onMouseEnter={handlePopupEnter}
          onMouseLeave={handlePopupLeave}
        />
      )}
    </div>
  );
}
