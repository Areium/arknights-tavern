import { useState, useEffect, useCallback, useRef } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";
import CharacterDetailCard from "./CharacterDetailCard";

interface CharacterInfo {
  id: string;
  name: string;
  title: string;
  loaded: boolean;
  active: boolean;
}

export default function CharacterPanel({
  onAddClick,
  refreshKey,
}: {
  onAddClick?: () => void;
  refreshKey?: number;
}) {
  const { activeSessionId, chatMode } = useAppStore();
  const api = useApi();
  const [characters, setCharacters] = useState<CharacterInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Hover/pin preview
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
    // Delay close to give user time to reach the popup or pin button
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

  const loadCharacters = useCallback(async () => {
    if (!activeSessionId) {
      setCharacters([]);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await api.getSceneCharacters(activeSessionId);
      const rawList: any[] = data.characters || data;
      const list: CharacterInfo[] = rawList.map((c: any) => {
        const name = typeof c === "string" ? c : c.name || c.id || "";
        return {
          id: name,
          name,
          title: typeof c === "string" ? "" : c.title || "",
          loaded: typeof c === "string" ? true : c.loaded ?? true,
          active:
            typeof c === "string"
              ? data.active === name
              : c.active ?? (data.active === name),
        };
      });
      setCharacters(list);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [activeSessionId, api]);

  useEffect(() => {
    loadCharacters();
    // Clear preview state on session switch
    setHoveredChar(null);
    setHoverAnchor(null);
    setPinnedChar(null);
    setPinnedAnchor(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSessionId, refreshKey]);

  const handleLoad = async (name: string) => {
    if (!activeSessionId) return;
    try {
      await api.loadCharacter(activeSessionId, name);
      await loadCharacters();
    } catch (err: any) {
      alert("加载角色失败: " + err.message);
    }
  };

  const handleUnload = async (name: string) => {
    if (!activeSessionId) return;
    try {
      await api.unloadCharacter(activeSessionId, name);
      await loadCharacters();
    } catch (err: any) {
      alert("卸载角色失败: " + err.message);
    }
  };

  const handleSwitch = async (name: string) => {
    if (!activeSessionId) return;
    try {
      await api.switchCharacter(activeSessionId, name);
      await loadCharacters();
    } catch (err: any) {
      alert("切换角色失败: " + err.message);
    }
  };

  if (!activeSessionId) {
    return (
      <div className="card">
        <h2 className="panel-title">场景角色</h2>
        <p className="text-gray-500 text-sm text-center py-4">
          请先选择或创建会话
        </p>
      </div>
    );
  }

  const loadedCount = characters.filter((c) => c.loaded).length;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h2 className="panel-title mb-0">
          场景角色
          {loadedCount > 0 && (
            <span className="ml-1.5 text-xs text-gray-500 font-normal">
              ({loadedCount})
            </span>
          )}
        </h2>
        <div className="flex gap-1">
          {chatMode !== "story" && (
            <button
              onClick={onAddClick}
              className="text-xs px-2 py-1 rounded bg-green-700/30 text-green-300 hover:bg-green-700/50"
              title="浏览全部角色"
            >
              + 添加
            </button>
          )}
          <button
            onClick={loadCharacters}
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

      <div className="space-y-1.5 max-h-48 overflow-y-auto">
        {!loading && characters.length === 0 && (
          <p className="text-gray-500 text-sm text-center py-4">
            {chatMode === "story"
              ? "场景尚未加载角色"
              : '暂无角色 — 点击“+ 添加”浏览'}
          </p>
        )}
        {characters.map((c) => (
          <div
            key={c.id}
            onMouseEnter={(e) => handleMouseEnter(c.name, e.currentTarget)}
            onMouseLeave={handleMouseLeave}
            className={`flex items-center justify-between px-3 py-2 rounded-lg text-sm cursor-default ${
              c.active
                ? "bg-amber-600/20 border border-amber-600/30"
                : c.loaded
                  ? "bg-gray-700/50"
                  : "bg-gray-800/50"
            }`}
          >
            <div className="min-w-0 flex-1">
              <span className="font-medium truncate block">{c.name}</span>
              {c.title && (
                <span className="text-xs text-gray-500">{c.title}</span>
              )}
              {c.active && (
                <span className="text-xs text-amber-400 ml-2">[对话中]</span>
              )}
            </div>
            <div className="flex gap-1 shrink-0 ml-2">
              {/* Pin button on list item */}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handlePinFromList(c.name, e.currentTarget.parentElement!);
                }}
                className={`text-xs px-1 rounded transition-colors ${
                  pinnedChar === c.name
                    ? "bg-amber-600/30 text-amber-300"
                    : "text-gray-600 hover:text-gray-300"
                }`}
                title={pinnedChar === c.name ? "取消固定" : "固定查看详情"}
              >
                📌
              </button>
              {c.loaded ? (
                <>
                  {!c.active && (
                    <button
                      onClick={() => handleSwitch(c.name)}
                      className="text-xs px-2 py-1 rounded bg-blue-600/30 text-blue-300 hover:bg-blue-600/50"
                    >
                      对话
                    </button>
                  )}
                  {chatMode !== "story" && (
                    <button
                      onClick={() => handleUnload(c.name)}
                      className="text-xs px-2 py-1 rounded bg-gray-700 text-gray-400 hover:text-red-400"
                    >
                      移除
                    </button>
                  )}
                </>
              ) : (
                chatMode !== "story" && (
                  <button
                    onClick={() => handleLoad(c.name)}
                    className="text-xs px-2 py-1 rounded bg-green-700/30 text-green-300 hover:bg-green-700/50"
                  >
                    加入
                  </button>
                )
              )}
            </div>
          </div>
        ))}
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
