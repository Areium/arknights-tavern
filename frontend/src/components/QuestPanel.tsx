import { useState, useEffect, useCallback } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";
import type { Quest, QuestsResponse } from "../types";

const STATUS_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  active: { label: "进行中", color: "text-amber-400", bg: "bg-amber-500/20" },
  completed: { label: "已完成", color: "text-emerald-400", bg: "bg-emerald-500/20" },
  failed: { label: "已失败", color: "text-red-400", bg: "bg-red-500/20" },
  visible: { label: "待触发", color: "text-blue-400", bg: "bg-blue-500/20" },
  locked: { label: "未解锁", color: "text-gray-500", bg: "bg-gray-600/20" },
};

const TYPE_LABELS: Record<string, string> = {
  main: "主线",
  side: "支线",
  deep: "深层",
};

function QuestItem({
  quest,
  onToggle,
  onComplete,
}: {
  quest: Quest;
  onToggle: (id: string, status: string) => void;
  onComplete: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const st = STATUS_CONFIG[quest.status] || STATUS_CONFIG.locked;
  const isLocked = quest.status === "locked";
  const isVisible = quest.status === "visible";

  return (
    <div
      className={`rounded-lg border transition-colors ${
        isLocked
          ? "border-gray-700/50 opacity-40"
          : isVisible
          ? "border-blue-600/20 bg-blue-500/3"
          : quest.status === "active"
          ? "border-amber-600/40 bg-amber-500/5"
          : "border-gray-700/30"
      }`}
    >
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        disabled={isLocked}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
      >
        {/* Type badge */}
        <span
          className={`text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 ${
            quest.type === "main"
              ? "bg-amber-600/30 text-amber-300"
              : quest.type === "deep"
              ? "bg-purple-600/30 text-purple-300"
              : "bg-blue-600/30 text-blue-300"
          }`}
        >
          {TYPE_LABELS[quest.type] || quest.type}
        </span>

        {/* Status dot */}
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${st.bg}`} />

        {/* Name */}
        <span className={`text-sm flex-1 truncate ${isLocked ? "text-gray-500" : "text-gray-200"}`}>
          {quest.name}
        </span>

        {/* Status label */}
        <span className={`text-[10px] shrink-0 ${st.color}`}>{st.label}</span>

        {/* Expand icon */}
        {!isLocked && (
          <svg
            className={`w-3 h-3 text-gray-500 transition-transform ${expanded ? "rotate-180" : ""}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        )}
      </button>

      {/* Expanded content */}
      {expanded && !isLocked && (
        <div className="px-3 pb-3 space-y-2 text-xs border-t border-gray-700/30 pt-2">
          {quest.objective && (
            <div>
              <span className="text-gray-500">目标：</span>
              <span className="text-gray-300">{quest.objective}</span>
            </div>
          )}
          {quest.reward && (
            <div>
              <span className="text-gray-500">奖励：</span>
              <span className="text-gray-300">{quest.reward}</span>
            </div>
          )}
          {quest.completion && (
            <div>
              <span className="text-gray-500">完成条件：</span>
              <span className="text-gray-300">{quest.completion}</span>
            </div>
          )}
          {quest.failure && (
            <div>
              <span className="text-gray-500">失败条件：</span>
              <span className="text-red-400">{quest.failure}</span>
            </div>
          )}
          {quest.trigger && (
            <div>
              <span className="text-gray-500">触发：</span>
              <span className="text-gray-400">{quest.trigger}</span>
            </div>
          )}

          {/* Actions */}
          {quest.status === "visible" && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onToggle(quest.id, "active");
              }}
              className="w-full mt-1 py-1.5 text-xs rounded-md bg-blue-600/20 text-blue-400
                         hover:bg-blue-600/40 transition-colors"
            >
              追踪任务
            </button>
          )}
          {quest.status === "active" && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onComplete(quest.id);
              }}
              className="w-full mt-1 py-1.5 text-xs rounded-md bg-emerald-600/20 text-emerald-400
                         hover:bg-emerald-600/40 transition-colors"
            >
              标记完成
            </button>
          )}
          {quest.status === "completed" && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onToggle(quest.id, "active");
              }}
              className="w-full mt-1 py-1.5 text-xs rounded-md bg-amber-600/20 text-amber-400
                         hover:bg-amber-600/40 transition-colors"
            >
              恢复进行中
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function QuestPanel() {
  const { activeSessionId, chatMode, envRefreshKey } = useAppStore();
  const api = useApi();
  const [plotId, setPlotId] = useState<string | null>(null);
  const [quests, setQuests] = useState<Quest[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadQuests = useCallback(async () => {
    if (!activeSessionId || chatMode !== "story") {
      setQuests([]);
      setPlotId(null);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const data: QuestsResponse = await api.getQuests(activeSessionId);
      setPlotId(data.plot_id);
      setQuests(data.quests || []);
    } catch (e: any) {
      setError(e.message || "加载失败");
    } finally {
      setLoading(false);
    }
  }, [activeSessionId, chatMode, envRefreshKey]);

  useEffect(() => {
    loadQuests();
  }, [loadQuests]);

  const handleLoadPlot = async () => {
    // 当前仅支持 near_light
    const pid = window.prompt("输入剧情 ID（如 near_light）：", "near_light");
    if (!pid?.trim()) return;
    if (!activeSessionId) return;

    setLoading(true);
    try {
      const data = await api.loadQuests(activeSessionId, pid.trim());
      setPlotId(data.plot_id);
      setQuests(data.quests || []);
    } catch (e: any) {
      setError(e.message || "加载失败");
    } finally {
      setLoading(false);
    }
  };

  const handleToggle = async (questId: string, status: string) => {
    if (!activeSessionId) return;
    try {
      await api.updateQuestState(activeSessionId, questId, status);
      setQuests((prev) =>
        prev.map((q) => (q.id === questId ? { ...q, status: status as Quest["status"] } : q))
      );
    } catch {}
  };

  const handleComplete = async (questId: string) => {
    if (!activeSessionId) return;
    try {
      await api.updateQuestState(activeSessionId, questId, "completed");
      setQuests((prev) =>
        prev.map((q) => (q.id === questId ? { ...q, status: "completed" } : q))
      );
    } catch {}
  };

  // 非剧情模式不显示
  if (chatMode !== "story") {
    return null;
  }

  const activeCount = quests.filter((q) => q.status === "active").length;
  const visibleCount = quests.filter((q) => q.status === "visible").length;
  const completedCount = quests.filter((q) => q.status === "completed").length;
  const mainQuests = quests.filter((q) => q.type === "main");
  const sideQuests = quests.filter((q) => q.type === "side");

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="panel-title">任务</h3>
        {!plotId ? (
          <button
            onClick={handleLoadPlot}
            className="text-[10px] px-2 py-1 rounded-md bg-blue-600/20 text-blue-400
                       hover:bg-blue-600/40 transition-colors"
          >
            加载剧情
          </button>
        ) : (
          <span className="text-[10px] text-gray-500">
            {activeCount > 0 && `${activeCount} 进行中 `}
            {visibleCount > 0 && `${visibleCount} 待触发 `}
            {activeCount === 0 && visibleCount === 0 && `${completedCount} 已完成`}
          </span>
        )}
      </div>

      {/* Loading */}
      {loading && (
        <div className="text-xs text-gray-500 text-center py-4">加载中...</div>
      )}

      {/* Error */}
      {error && (
        <div className="text-xs text-red-400 bg-red-500/10 rounded px-2 py-1">{error}</div>
      )}

      {/* Empty */}
      {!loading && !error && !plotId && (
        <div className="text-xs text-gray-500 text-center py-4">
          点击「加载剧情」绑定剧情任务
        </div>
      )}

      {/* Main quests */}
      {mainQuests.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] text-amber-500/70 font-medium px-1">主线任务</p>
          {mainQuests.map((q) => (
            <QuestItem
              key={q.id}
              quest={q}
              onToggle={handleToggle}
              onComplete={handleComplete}
            />
          ))}
        </div>
      )}

      {/* Side quests */}
      {sideQuests.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] text-blue-400/70 font-medium px-1">支线任务</p>
          {sideQuests.map((q) => (
            <QuestItem
              key={q.id}
              quest={q}
              onToggle={handleToggle}
              onComplete={handleComplete}
            />
          ))}
        </div>
      )}

      {/* Plot ID */}
      {plotId && (
        <button
          onClick={handleLoadPlot}
          className="w-full text-[10px] text-gray-600 hover:text-gray-400 transition-colors py-1"
        >
          切换剧情 ({plotId})
        </button>
      )}
    </div>
  );
}
