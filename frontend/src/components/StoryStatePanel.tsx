/**
 * 剧情进度面板 — 状态显示 + 关键节点回档。
 *
 * - 状态显示：玩家当前处于节点结构（章节/节拍）中的什么位置，路线图各节点状态。
 * - 回档：列出玩家经历过的关键节点（含轮次区间），可回档并恢复到该节点时的状态。
 *
 * 仅在剧情模式且有剧情绑定时显示。
 */
import { useState, useEffect, useCallback } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";
import type { StoryStateDTO, StoryBeatNode } from "../types";

const NODE_STYLE: Record<StoryBeatNode["state"], { dot: string; text: string }> = {
  done: { dot: "bg-emerald-500", text: "text-gray-400" },
  current: { dot: "bg-amber-400 animate-pulse", text: "text-amber-200 font-medium" },
  locked: { dot: "bg-gray-600/70", text: "text-gray-600" },
};

export default function StoryStatePanel() {
  const { activeSessionId, chatMode, chatRefreshKey } = useAppStore();
  const narrationCount = useAppStore(
    (s) => s.sessionNarrationCount[activeSessionId || ""] ?? 0
  );
  const api = useApi();

  const [state, setState] = useState<StoryStateDTO | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rollingBack, setRollingBack] = useState<string | null>(null);
  const [showRoadmap, setShowRoadmap] = useState(false);
  const [showStates, setShowStates] = useState(false);

  const load = useCallback(async () => {
    if (!activeSessionId || chatMode !== "story") {
      setState(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setState(await api.getStoryState(activeSessionId));
    } catch (e: any) {
      setError(e.message || "加载失败");
    } finally {
      setLoading(false);
    }
  }, [activeSessionId, chatMode, api]);

  useEffect(() => {
    load();
  }, [load, narrationCount, chatRefreshKey]);

  const handleRollback = useCallback(
    async (nodeId: string, roundEnd: number, label: string) => {
      if (!activeSessionId) return;
      if (
        !confirm(
          `回档到「${label}」？\n将恢复到该节点时的全部状态（第 ${roundEnd} 轮），之后的进度会被清除。`
        )
      )
        return;
      setRollingBack(nodeId);
      try {
        const res = await api.rollbackNode(activeSessionId, nodeId);
        const store = useAppStore.getState();
        store.setSessionMessages(activeSessionId, (prev) =>
          prev.filter((m) => !m.round || m.round <= res.target_round)
        );
        store.setSessionNarrationCount(activeSessionId, res.target_round);
        store.triggerMemoryRefresh();
        store.triggerEnvRefresh();
        setState(res.story_state);
      } catch (e: any) {
        alert("回档失败: " + (e.message || "未知错误"));
      } finally {
        setRollingBack(null);
      }
    },
    [activeSessionId, api]
  );

  if (chatMode !== "story") return null;

  if (loading && !state) {
    return (
      <div className="space-y-2">
        <h3 className="panel-title">剧情进度</h3>
        <div className="text-xs text-gray-500 text-center py-3">加载中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-2">
        <h3 className="panel-title">剧情进度</h3>
        <div className="text-xs text-red-400 bg-red-500/10 rounded px-2 py-1">{error}</div>
      </div>
    );
  }

  if (!state?.has_plot) {
    return (
      <div className="space-y-2">
        <h3 className="panel-title">剧情进度</h3>
        <div className="text-xs text-gray-500 text-center py-3">当前会话未绑定剧情节点结构</div>
      </div>
    );
  }

  const chapter = state.chapter;
  const beat = state.beat;
  const roads = state.roads || [];
  const currentChapterIdx = chapter?.idx ?? 0;
  // 当前章节内的节拍进度
  const curBeats = roads[currentChapterIdx]?.beats || [];
  const doneInChapter = curBeats.filter((b) => b.state === "done").length;
  const chapterProgress = curBeats.length ? (doneInChapter / curBeats.length) * 100 : 0;

  // node_id → 节拍摘要（供回档点显示可读名称）
  const beatLabel: Record<string, string> = {};
  for (const r of roads) {
    for (const b of r.beats) beatLabel[b.id] = b.summary || b.id;
  }

  const history = state.node_history || [];
  const charStates = state.character_states || {};
  const charNames = Object.keys(charStates).filter(
    (n) => (charStates[n]?.conditions || []).length > 0
  );

  return (
    <div className="space-y-3">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <h3 className="panel-title">剧情进度</h3>
        <button
          onClick={load}
          className="text-[10px] text-gray-500 hover:text-gray-300 transition-colors"
          title="刷新"
        >
          ⟳
        </button>
      </div>

      {/* ── 当前位置 ── */}
      <div className="rounded-lg border border-amber-600/30 bg-amber-500/5 px-3 py-2 space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-600/30 text-amber-300 shrink-0">
            第 {currentChapterIdx + 1} 章
          </span>
          <span className="text-xs text-gray-300 truncate">{chapter?.title || "—"}</span>
          <span className="ml-auto text-[10px] text-gray-500 shrink-0">
            {chapter ? `${currentChapterIdx + 1}/${chapter.total}` : ""}
          </span>
        </div>
        <div className="text-[11px] text-amber-200/90">
          当前节点：{beat ? `${beat.idx + 1}/${beat.total} · ${beat.summary || beat.id}` : "—"}
        </div>
        {/* 章节内进度条 */}
        <div className="h-1 rounded-full bg-gray-700/50 overflow-hidden">
          <div
            className="h-full bg-amber-500/70 transition-all"
            style={{ width: `${chapterProgress}%` }}
          />
        </div>
        {beat && beat.narrations_on_beat > 0 && (
          <div className="text-[10px] text-gray-500">
            本节点已进行 {beat.narrations_on_beat} 轮叙述
          </div>
        )}
      </div>

      {/* ── 关键节点回档 ── */}
      <div className="space-y-1">
        <button
          onClick={() => setShowRoadmap((v) => !v)}
          className="w-full flex items-center justify-between text-[10px] text-gray-500 hover:text-gray-300 transition-colors px-1"
        >
          <span>关键节点回档（{history.length}）</span>
          <span>{showRoadmap ? "▲" : "▼"}</span>
        </button>
        {history.length === 0 && (
          <div className="text-[11px] text-gray-600 px-1">尚无已记录节点</div>
        )}
        {history.map((n) => (
          <div
            key={`${n.node_id}-${n.round_end}`}
            className="flex items-center gap-2 rounded-md border border-gray-700/40 px-2 py-1.5"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500/70 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-[11px] text-gray-300 truncate">
                {beatLabel[n.node_id] || n.node_id}
              </div>
              <div className="text-[10px] text-gray-600">
                第 {n.round_start}–{n.round_end} 轮
              </div>
            </div>
            <button
              onClick={() =>
                handleRollback(n.node_id, n.round_end, beatLabel[n.node_id] || n.node_id)
              }
              disabled={rollingBack !== null}
              className="text-[10px] px-2 py-1 rounded bg-blue-600/20 text-blue-300
                         hover:bg-blue-600/40 transition-colors disabled:opacity-40 shrink-0"
            >
              {rollingBack === n.node_id ? "回档中..." : "回档"}
            </button>
          </div>
        ))}
      </div>

      {/* ── 路线图 ── */}
      {showRoadmap && (
        <div className="space-y-2 border-t border-gray-700/40 pt-2">
          {roads.map((r) => {
            const isCurrent = r.state === "current";
            const isLocked = r.state === "locked";
            return (
              <div key={r.chapter_idx} className="space-y-1">
                <div className="flex items-center gap-1.5 px-1">
                  <span
                    className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                      r.state === "done"
                        ? "bg-emerald-500"
                        : isCurrent
                        ? "bg-amber-400"
                        : "bg-gray-600/70"
                    }`}
                  />
                  <span
                    className={`text-[11px] truncate ${
                      isCurrent ? "text-amber-200" : isLocked ? "text-gray-600" : "text-gray-400"
                    }`}
                  >
                    第 {r.chapter_idx + 1} 章 · {r.title}
                  </span>
                </div>
                {!isLocked && (
                  <div className="pl-4 space-y-0.5">
                    {r.beats.map((b) => {
                      const st = NODE_STYLE[b.state] || NODE_STYLE.locked;
                      return (
                        <div key={b.id} className="flex items-start gap-1.5">
                          <span className={`w-1 h-1 rounded-full mt-1.5 shrink-0 ${st.dot}`} />
                          <span className={`text-[10px] leading-tight ${st.text}`}>
                            {b.summary || b.id}
                            {b.has_combat && <span className="ml-1 text-red-400/80">⚔</span>}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── 角色状态记录 ── */}
      {charNames.length > 0 && (
        <div className="space-y-1 border-t border-gray-700/40 pt-2">
          <button
            onClick={() => setShowStates((v) => !v)}
            className="w-full flex items-center justify-between text-[10px] text-gray-500 hover:text-gray-300 transition-colors px-1"
          >
            <span>角色状态（{charNames.length}）</span>
            <span>{showStates ? "▲" : "▼"}</span>
          </button>
          {showStates &&
            charNames.map((name) => (
              <div key={name} className="text-[10px] text-gray-400 px-1">
                <span className="text-gray-300">{name}</span>
                <span className="text-gray-500">
                  ：{(charStates[name].conditions || []).map((c: any) => c.name).join("、")}
                </span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
