import { useState, useEffect } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";

interface AvailableCharacter {
  id: string;
  name: string;
}

export default function CharacterBrowser({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { activeSessionId } = useAppStore();
  const api = useApi();
  const [characters, setCharacters] = useState<AvailableCharacter[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingName, setLoadingName] = useState<string | null>(null);

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

  const handleAdd = async (name: string) => {
    if (!activeSessionId) return;
    setLoadingName(name);
    try {
      await api.loadCharacter(activeSessionId, name);
    } catch (err: any) {
      alert("加载失败: " + err.message);
    } finally {
      setLoadingName(null);
    }
  };

  const filtered = search.trim()
    ? characters.filter((c) =>
        c.name.toLowerCase().includes(search.toLowerCase())
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
                className="flex items-center justify-between px-3 py-2.5 rounded-lg hover:bg-gray-700/50 transition-colors"
              >
                <div>
                  <span className="text-sm font-medium">{c.name}</span>
                  <span className="text-xs text-gray-500 ml-2">{c.id}</span>
                </div>
                <button
                  onClick={() => handleAdd(c.name)}
                  disabled={loadingName === c.name}
                  className="text-xs px-3 py-1.5 rounded bg-green-700/30 text-green-300
                    hover:bg-green-700/50 disabled:opacity-50"
                >
                  {loadingName === c.name ? "加载中..." : "加入场景"}
                </button>
              </div>
            ))}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-gray-700 text-xs text-gray-500">
          共 {characters.length} 个角色
          {search.trim() && `，筛选后 ${filtered.length} 个`}
        </div>
      </div>
    </div>
  );
}
