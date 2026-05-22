import { useState, useEffect, useCallback } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";

interface Memory {
  id: string;
  title: string;
  summary: string;
  round_start: number;
  round_end: number;
  created_at: number;
}

export default function MemoryPanel() {
  const { activeSessionId, chatMode, memoryRefreshKey, triggerMemoryRefresh, triggerChatRefresh } =
    useAppStore();
  const api = useApi();

  const [memories, setMemories] = useState<Memory[]>([]);
  const [narrationCount, setNarrationCount] = useState(0);
  const [lastMemoryEnd, setLastMemoryEnd] = useState(0);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const loadMemories = useCallback(async () => {
    if (!activeSessionId || chatMode !== "story") return;
    setLoading(true);
    try {
      const data = await api.getMemories(activeSessionId);
      setMemories(data.memories || []);
      setNarrationCount(data.narration_count || 0);
      setLastMemoryEnd(data.last_memory_end || 0);
      if (data.memories?.length) {
        setExpanded(new Set([data.memories[data.memories.length - 1].id]));
      }
    } catch {
      // 静默处理
    } finally {
      setLoading(false);
    }
  }, [activeSessionId, chatMode, api]);

  useEffect(() => {
    loadMemories();
  }, [loadMemories]);

  useEffect(() => {
    if (memoryRefreshKey > 0) loadMemories();
  }, [memoryRefreshKey]);

  const handleRegenerate = async () => {
    if (!activeSessionId) return;
    if (narrationCount === 0) {
      alert("暂无任何叙述记录，无法生成回忆");
      return;
    }
    if (!confirm("将清除已有回忆，按当前设置重新从完整历史生成。确定？")) return;
    setRegenerating(true);
    try {
      const data = await api.regenerateMemories(activeSessionId);
      setMemories(data.memories || []);
      setNarrationCount(data.narration_count || 0);
      setLastMemoryEnd(data.memories?.length
        ? data.memories[data.memories.length - 1].round_end
        : 0);
      if (data.memories?.length) {
        setExpanded(new Set([data.memories[data.memories.length - 1].id]));
      } else {
        alert("叙述轮次不足一组，积累更多对话后重试");
      }
      triggerMemoryRefresh();
    } catch (err: any) {
      alert("重新生成失败: " + (err.message || "未知错误"));
    } finally {
      setRegenerating(false);
    }
  };

  const handleRollbackToMemory = async (roundEnd: number) => {
    if (!activeSessionId) return;
    if (!confirm(`回退到第 ${roundEnd} 轮？\n之后的对话记录和回忆将被删除。`)) return;
    try {
      await api.rollbackSession(activeSessionId, roundEnd);
      triggerMemoryRefresh();
      triggerChatRefresh();
    } catch (err: any) {
      alert("回退失败: " + (err.message || "未知错误"));
    }
  };

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (chatMode !== "story" || !activeSessionId) return null;

  const unsummarized = narrationCount - lastMemoryEnd;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h2 className="panel-title mb-0">回忆</h2>
        <button
          onClick={handleRegenerate}
          disabled={regenerating}
          className="text-xs text-gray-500 hover:text-gray-300 disabled:opacity-50"
          title="按当前间隔重新生成全部回忆"
        >
          {regenerating ? "生成中..." : "重新生成"}
        </button>
      </div>

      {loading ? (
        <p className="text-gray-500 text-sm text-center py-2">加载中...</p>
      ) : memories.length === 0 ? (
        <p className="text-gray-500 text-sm text-center py-2">
          {narrationCount > 0
            ? `已进行 ${narrationCount} 轮，${unsummarized} 轮未总结`
            : "暂无回忆"}
        </p>
      ) : (
        <>
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {memories.map((m, i) => {
              const isOpen = expanded.has(m.id);
              return (
                <div key={m.id} className="rounded-lg bg-gray-700/30 overflow-hidden">
                  <button
                    onClick={() => toggleExpand(m.id)}
                    className="w-full text-left px-3 py-2 flex items-center justify-between hover:bg-gray-700/50 transition-colors"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium truncate">
                        {isOpen ? "▾" : "▸"} 第{i + 1}章 · {m.title}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        第 {m.round_start}-{m.round_end} 轮
                      </div>
                    </div>
                  </button>
                  {isOpen && (
                    <div className="px-3 pb-2">
                      <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">
                        {m.summary}
                      </p>
                      <button
                        onClick={() => handleRollbackToMemory(m.round_end)}
                        className="mt-2 text-xs text-gray-500 hover:text-red-400 transition-colors"
                      >
                        ↩ 回退到此
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {unsummarized > 0 && (
            <p className="text-xs text-gray-600 mt-2 text-center">
              {unsummarized} 轮未总结
            </p>
          )}
        </>
      )}
    </div>
  );
}
