import { useState, useEffect, useMemo, useCallback } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";
import type { PlotInfo } from "../types";

export default function SessionList() {
  const { sessions, activeSessionId, chatMode, backend, setSessions, setActiveSession, setCurrentView, setIndexSessionId } =
    useAppStore();
  const api = useApi();
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);

  // 剧情选择相关
  const [plots, setPlots] = useState<PlotInfo[]>([]);
  const [plotsLoading, setPlotsLoading] = useState(false);
  const [plotsError, setPlotsError] = useState(false);
  const [showPlotPicker, setShowPlotPicker] = useState(false);
  const [combatMode, setCombatMode] = useState<"narrative" | "tactical">("narrative");

  // 加载可用剧情列表（仅在剧情模式时，后端就绪后重试）
  useEffect(() => {
    if (chatMode !== "story") {
      setPlots([]);
      setPlotsLoading(false);
      setPlotsError(false);
      return;
    }
    if (backend.status !== "connected") return;
    let cancelled = false;
    setPlotsLoading(true);
    api.listPlots()
      .then((data) => {
        if (!cancelled) {
          setPlots(data);
          setPlotsError(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          console.error("加载剧情列表失败:", err);
          setPlotsError(true);
        }
      })
      .finally(() => {
        if (!cancelled) setPlotsLoading(false);
      });
    return () => { cancelled = true; };
  }, [chatMode, backend.status, api]);

  // 按当前模式过滤会话
  const filteredSessions = useMemo(
    () => sessions.filter((s) => s.mode === chatMode),
    [sessions, chatMode]
  );

  // 模式切换时自动切换到该模式下的第一个会话
  useEffect(() => {
    setSelectedIds(new Set());
    if (filteredSessions.length === 0) {
      setActiveSession(null);
      return;
    }
    const activeInMode = filteredSessions.find((s) => s.id === activeSessionId);
    if (!activeInMode) {
      setActiveSession(filteredSessions[0].id);
    }
  }, [chatMode, filteredSessions, activeSessionId, setActiveSession]);

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelectedIds((prev) => {
      if (prev.size === filteredSessions.length) return new Set();
      return new Set(filteredSessions.map((s) => s.id));
    });
  }, [filteredSessions]);

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!confirm(`确定删除选中的 ${selectedIds.size} 个会话？此操作不可恢复。`)) return;
    setBatchDeleting(true);
    try {
      for (const id of selectedIds) {
        await api.deleteSession(id);
      }
      const keepIds = new Set(
        sessions.filter((s) => !selectedIds.has(s.id)).map((s) => s.id)
      );
      setSessions(sessions.filter((s) => keepIds.has(s.id)));
      if (activeSessionId && selectedIds.has(activeSessionId)) {
        setActiveSession(null);
      }
      for (const id of selectedIds) {
        try { localStorage.removeItem(`ark_chat_${chatMode}_${id}`); } catch {}
      }
      setSelectedIds(new Set());
    } catch (err: any) {
      alert("批量删除失败: " + err.message);
    } finally {
      setBatchDeleting(false);
    }
  };

  const handleCreate = async (plotId: string, combatMode: "narrative" | "tactical" = "narrative") => {
    setShowPlotPicker(false);
    setCreating(true);
    try {
      const session = await api.createSession(chatMode, "", plotId, combatMode);
      setSessions([...sessions, session]);
      setActiveSession(session.id);
    } catch (err: any) {
      alert("创建会话失败: " + err.message);
    } finally {
      setCreating(false);
    }
  };

  const handleNewClick = () => {
    if (chatMode === "story") {
      if (plotsLoading) return;
      if (plots.length > 0) {
        setShowPlotPicker(true);
        return;
      }
      if (plotsError) {
        setPlotsError(false);
        api.listPlots().then(setPlots).catch((err) => {
          console.error("加载剧情列表失败:", err);
          setPlotsError(true);
        });
        return;
      }
    }
    handleCreate("");
  };

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("确定删除此会话？")) return;
    try {
      await api.deleteSession(id);
      setSessions(sessions.filter((s) => s.id !== id));
      if (activeSessionId === id) setActiveSession(null);
      const mode = sessions.find((s) => s.id === id)?.mode || "free";
      try { localStorage.removeItem(`ark_chat_${mode}_${id}`); } catch {}
    } catch (err: any) {
      alert("删除失败: " + err.message);
    }
  };

  const startRename = (id: string, currentName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(id);
    setEditName(currentName);
  };

  const commitRename = async () => {
    const id = editingId;
    const name = editName.trim();
    setEditingId(null);
    if (!id || !name) return;
    try {
      await api.renameSession(id, name);
      setSessions(
        sessions.map((s) => (s.id === id ? { ...s, name } : s))
      );
    } catch (err: any) {
      alert("重命名失败: " + err.message);
    }
  };

  const cancelRename = () => {
    setEditingId(null);
  };

  const handleRenameKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commitRename();
    } else if (e.key === "Escape") {
      cancelRename();
    }
  };

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={filteredSessions.length > 0 && selectedIds.size === filteredSessions.length}
            onChange={toggleSelectAll}
            className="checkbox"
            title="全选"
          />
          <h2 className="panel-title mb-0">
            {chatMode === "story" ? "剧情会话" : "自由会话"}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          {selectedIds.size > 0 && (
            <button
              onClick={handleBatchDelete}
              disabled={batchDeleting}
              className="btn-danger text-xs px-2 py-1"
            >
              {batchDeleting ? "删除中..." : `删除选中 (${selectedIds.size})`}
            </button>
          )}
          <button
            onClick={handleNewClick}
            disabled={creating || (chatMode === "story" && plotsLoading)}
            className="btn-primary text-xs px-3 py-1"
          >
            {creating ? "创建中..." : chatMode === "story" && plotsLoading ? "加载中..." : chatMode === "story" && plotsError ? "重试加载剧情" : "+ 新建"}
          </button>
        </div>
      </div>

      {/* Plot picker dialog */}
      {showPlotPicker && (
        <div className="mb-3 p-2 rounded-lg bg-gray-800 border border-gray-700">
          <p className="text-xs text-gray-400 mb-2">选择战斗模式：</p>
          <div className="flex gap-2 mb-3">
            <button
              onClick={() => setCombatMode("narrative")}
              className={`flex-1 px-3 py-1.5 rounded text-xs transition-colors ${
                combatMode === "narrative"
                  ? "bg-blue-600/30 text-blue-300 border border-blue-500/50"
                  : "bg-gray-700/50 text-gray-400 hover:bg-gray-700 border border-transparent"
              }`}
            >
              纯剧情模式
            </button>
            <button
              onClick={() => setCombatMode("tactical")}
              className={`flex-1 px-3 py-1.5 rounded text-xs transition-colors ${
                combatMode === "tactical"
                  ? "bg-orange-600/30 text-orange-300 border border-orange-500/50"
                  : "bg-gray-700/50 text-gray-400 hover:bg-gray-700 border border-transparent"
              }`}
            >
              战术模式
            </button>
          </div>
          <p className="text-[10px] text-gray-500 mb-2">
            {combatMode === "tactical"
              ? "对话中触发战斗时将进入战术回合制，创建后不可更改"
              : "纯剧情叙述，不包含战斗玩法，创建后不可更改"}
          </p>
          <p className="text-xs text-gray-400 mb-2">选择绑定的剧情：</p>
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {/* No binding option */}
            <button
              onClick={() => handleCreate("", combatMode)}
              className="w-full text-left px-3 py-2 rounded-md text-sm text-gray-400
                         hover:bg-gray-700/50 transition-colors flex items-center gap-2"
            >
              <span className="text-gray-600 text-[10px] w-12 shrink-0">不绑定</span>
              <span>自由探索</span>
            </button>
            {plots.map((p) => (
              <button
                key={p.id}
                onClick={() => handleCreate(p.id, combatMode)}
                className="w-full text-left px-3 py-2 rounded-md text-sm hover:bg-gray-700/50
                           transition-colors flex items-center gap-2"
              >
                <span
                  className={`text-[10px] px-1 py-0.5 rounded shrink-0 w-12 text-center ${
                    p.category === "main"
                      ? "bg-amber-600/20 text-amber-400"
                      : "bg-blue-600/20 text-blue-400"
                  }`}
                >
                  {p.category === "main" ? "主线" : p.category}
                </span>
                <span className="text-gray-200 flex-1 truncate">{p.name}</span>
                <span className="text-[10px] text-gray-600">{p.id}</span>
              </button>
            ))}
          </div>
          <button
            onClick={() => setShowPlotPicker(false)}
            className="w-full mt-2 text-xs text-gray-600 hover:text-gray-400 py-1"
          >
            取消
          </button>
        </div>
      )}

      <div className="space-y-1 max-h-60 overflow-y-auto">
        {filteredSessions.length === 0 && (
          <p className="text-gray-500 text-sm text-center py-4">
            {chatMode === "story" ? "暂无剧情会话" : "暂无自由会话"}
          </p>
        )}
        {filteredSessions.map((s) => (
          <div
            key={s.id}
            onClick={() => setActiveSession(s.id)}
            className={`flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer text-sm transition-colors ${
              s.id === activeSessionId
                ? "bg-blue-600/20 text-blue-300"
                : "hover:bg-gray-700/50 text-gray-400"
            }`}
          >
            <div className="min-w-0 flex-1 flex items-center gap-2">
              <input
                type="checkbox"
                checked={selectedIds.has(s.id)}
                onChange={() => toggleSelect(s.id)}
                onClick={(e) => e.stopPropagation()}
                className="checkbox"
              />
              <div className="min-w-0 flex-1">
                {editingId === s.id ? (
                  <input
                    className="input text-sm py-0.5 px-1 w-full"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    onBlur={commitRename}
                    onKeyDown={handleRenameKeyDown}
                    onClick={(e) => e.stopPropagation()}
                    autoFocus
                  />
                ) : (
                  <div
                    className="truncate font-medium"
                    onDoubleClick={(e) => startRename(s.id, s.name || "", e)}
                    title="双击重命名"
                  >
                    {s.name || "未命名会话"}
                  </div>
                )}
                <div className="text-[10px] text-gray-600">
                  {new Date(s.created_at * 1000).toLocaleString("zh-CN")}
                </div>
              </div>
            </div>
            {selectedIds.size === 0 && (
              <div className="flex items-center gap-1">
                {s.mode === "story" && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setIndexSessionId(s.id);
                      setCurrentView("index");
                    }}
                    className="px-1.5 py-1 text-gray-500 hover:text-amber-400 hover:bg-amber-600/10 rounded shrink-0 text-sm transition-colors"
                    title="索引配置"
                  >
                    ⚙
                  </button>
                )}
                <button
                  onClick={(e) => startRename(s.id, s.name || "", e)}
                  className="px-1.5 py-1 text-gray-500 hover:text-blue-400 hover:bg-blue-600/10 rounded shrink-0 text-sm transition-colors"
                  title="重命名"
                >
                  ✎
                </button>
                <button
                  onClick={(e) => handleDelete(s.id, e)}
                  className="px-1.5 py-1 text-gray-500 hover:text-red-400 hover:bg-red-600/10 rounded shrink-0 text-sm transition-colors"
                  title="删除"
                >
                  ✕
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
