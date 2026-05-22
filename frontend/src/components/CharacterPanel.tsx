import { useState, useEffect, useCallback } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";

interface CharacterInfo {
  id: string;
  name: string;
  title: string;
  loaded: boolean;
  active: boolean;
}

export default function CharacterPanel() {
  const { activeSessionId } = useAppStore();
  const api = useApi();
  const [characters, setCharacters] = useState<CharacterInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadCharacters = useCallback(async () => {
    if (!activeSessionId) return;
    setLoading(true);
    setError("");
    try {
      const data = await api.getSceneCharacters(activeSessionId);
      setCharacters(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [activeSessionId, api]);

  useEffect(() => {
    loadCharacters();
  }, [loadCharacters]);

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

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h2 className="panel-title mb-0">场景角色</h2>
        <button
          onClick={loadCharacters}
          className="text-xs text-gray-500 hover:text-gray-300"
          disabled={loading}
        >
          {loading ? "刷新中..." : "刷新"}
        </button>
      </div>

      {error && (
        <p className="text-red-400 text-xs mb-2">加载失败: {error}</p>
      )}

      <div className="space-y-1.5 max-h-48 overflow-y-auto">
        {characters.length === 0 && (
          <p className="text-gray-500 text-sm text-center py-4">
            暂无角色，点击下方加载
          </p>
        )}
        {characters.map((c) => (
          <div
            key={c.id}
            className={`flex items-center justify-between px-3 py-2 rounded-lg text-sm ${
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
                  <button
                    onClick={() => handleUnload(c.name)}
                    className="text-xs px-2 py-1 rounded bg-gray-700 text-gray-400 hover:text-red-400"
                  >
                    移除
                  </button>
                </>
              ) : (
                <button
                  onClick={() => handleLoad(c.name)}
                  className="text-xs px-2 py-1 rounded bg-green-700/30 text-green-300 hover:bg-green-700/50"
                >
                  加入
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
