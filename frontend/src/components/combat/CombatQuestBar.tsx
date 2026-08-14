/**
 * 战斗任务状态栏 — 会话战斗（剧情模式）时悬浮于战场顶部，
 * 折叠为胶囊显示主任务，点击展开全部进行中任务与目标。
 * 数据随 envRefreshKey 刷新（SSE scene_event 触发）。
 */
import { useCallback, useEffect, useState } from "react";
import { useAppStore } from "../../stores/appStore";
import { useApi } from "../../hooks/useApi";
import type { Quest, QuestsResponse } from "../../types";

const TYPE_BADGE: Record<string, { label: string; cls: string }> = {
  main: { label: "主线", cls: "bg-amber-600/40 text-amber-200 border-amber-500/50" },
  side: { label: "支线", cls: "bg-blue-600/40 text-blue-200 border-blue-500/50" },
  deep: { label: "深层", cls: "bg-purple-600/40 text-purple-200 border-purple-500/50" },
};

const STATUS_DOT: Record<string, string> = {
  active: "bg-amber-400",
  visible: "bg-blue-400",
};

export default function CombatQuestBar({ sessionId }: { sessionId: string | null }) {
  const envRefreshKey = useAppStore((s) => s.envRefreshKey);
  const api = useApi();
  const [quests, setQuests] = useState<Quest[]>([]);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    if (!sessionId) { setQuests([]); return; }
    try {
      const data: QuestsResponse = await api.getQuests(sessionId);
      setQuests(
        (data.quests || []).filter((q) => q.status === "active" || q.status === "visible")
      );
    } catch {
      setQuests([]);
    }
  }, [sessionId, api]);

  useEffect(() => {
    void load();
  }, [load, envRefreshKey]);

  if (!sessionId || quests.length === 0) return null;

  const activeCount = quests.filter((q) => q.status === "active").length;
  const primary = quests.find((q) => q.type === "main" && q.status === "active") || quests[0];
  const primaryBadge = TYPE_BADGE[primary.type] || TYPE_BADGE.side;

  return (
    <div className="absolute top-1.5 left-1/2 -translate-x-1/2 z-30 select-none">
      {/* 折叠胶囊 */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-3 py-1 rounded-full border border-amber-500/30 bg-gray-950/70 backdrop-blur-sm text-[11px] text-gray-200 hover:border-amber-400/50 hover:bg-gray-900/80 transition-colors shadow-lg"
        title="任务状态（点击展开）"
      >
        <span className={"w-1.5 h-1.5 rounded-full " + (STATUS_DOT[primary.status] || "bg-gray-500")} />
        <span className={"px-1 py-px rounded border text-[9px] font-medium " + primaryBadge.cls}>
          {primaryBadge.label}
        </span>
        <span className="max-w-48 truncate">{primary.name}</span>
        {quests.length > 1 && <span className="text-gray-500">+{quests.length - 1}</span>}
        <span className={"text-gray-500 text-[9px] transition-transform " + (open ? "rotate-180" : "")}>▼</span>
      </button>

      {/* 展开列表 */}
      {open && (
        <div className="absolute left-1/2 -translate-x-1/2 top-full mt-1.5 w-72 rounded-xl border border-gray-700/80 bg-gray-950/95 backdrop-blur shadow-2xl p-2 space-y-1.5">
          <div className="px-1.5 pb-1 text-[10px] text-gray-500 border-b border-gray-800">
            进行中任务 {activeCount} · 待触发 {quests.length - activeCount}
          </div>
          {quests.map((q) => {
            const badge = TYPE_BADGE[q.type] || TYPE_BADGE.side;
            return (
              <div key={q.id} className="px-1.5 py-1">
                <div className="flex items-center gap-1.5">
                  <span className={"px-1 py-px rounded border text-[9px] font-medium shrink-0 " + badge.cls}>
                    {badge.label}
                  </span>
                  <span className="text-xs text-gray-200 truncate">{q.name}</span>
                  <span className={"ml-auto w-1.5 h-1.5 rounded-full shrink-0 " + (STATUS_DOT[q.status] || "bg-gray-600")} />
                </div>
                {q.objective && (
                  <div className="mt-1 pl-1 text-[10px] text-gray-500 leading-relaxed">
                    目标：{q.objective}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
