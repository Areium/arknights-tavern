import { useState } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";

export default function SessionList() {
  const { sessions, activeSessionId, setSessions, setActiveSession } =
    useAppStore();
  const api = useApi();
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    setCreating(true);
    try {
      const { chatMode } = useAppStore.getState();
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
    } catch (err: any) {
      alert("删除失败: " + err.message);
    }
  };

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h2 className="panel-title mb-0">会话列表</h2>
        <button
          onClick={handleCreate}
          disabled={creating}
          className="btn-primary text-xs px-3 py-1"
        >
          {creating ? "创建中..." : "+ 新建"}
        </button>
      </div>

      <div className="space-y-1 max-h-60 overflow-y-auto">
        {sessions.length === 0 && (
          <p className="text-gray-500 text-sm text-center py-4">暂无会话</p>
        )}
        {sessions.map((s) => (
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
              <div className="truncate font-medium">
                {s.name || "未命名会话"}
              </div>
              <div className="text-xs text-gray-500">
                {s.mode === "story" ? "剧情" : "自由"} ·{" "}
                {new Date(s.created_at).toLocaleString("zh-CN")}
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
