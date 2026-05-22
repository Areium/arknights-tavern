import { useState, useEffect, useMemo } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";

export default function SessionList() {
  const { sessions, activeSessionId, chatMode, setSessions, setActiveSession } =
    useAppStore();
  const api = useApi();
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");

  // 按当前模式过滤会话
  const filteredSessions = useMemo(
    () => sessions.filter((s) => s.mode === chatMode),
    [sessions, chatMode]
  );

  // 模式切换时自动切换到该模式下的第一个会话
  useEffect(() => {
    if (filteredSessions.length === 0) {
      setActiveSession(null);
      return;
    }
    const activeInMode = filteredSessions.find((s) => s.id === activeSessionId);
    if (!activeInMode) {
      setActiveSession(filteredSessions[0].id);
    }
  }, [chatMode, filteredSessions, activeSessionId, setActiveSession]);

  const handleCreate = async () => {
    setCreating(true);
    try {
      const session = await api.createSession(chatMode);
      setSessions([...sessions, session]);
      setActiveSession(session.id);
    } catch (err: any) {
      alert("创建会话失败: " + err.message);
    } finally {
      setCreating(false);
    }
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
        <h2 className="panel-title mb-0">
          {chatMode === "story" ? "剧情会话" : "自由会话"}
        </h2>
        <button
          onClick={handleCreate}
          disabled={creating}
          className="btn-primary text-xs px-3 py-1"
        >
          {creating ? "创建中..." : "+ 新建"}
        </button>
      </div>

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
              <div className="text-xs text-gray-500">
                {s.mode === "story" ? "剧情" : "自由"} ·{" "}
                {new Date(s.created_at * 1000).toLocaleString("zh-CN")}
              </div>
            </div>
            <button
              onClick={(e) => handleDelete(s.id, e)}
              className="text-gray-600 hover:text-red-400 ml-2 shrink-0"
              title="删除"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
