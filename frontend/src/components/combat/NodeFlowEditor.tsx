/**
 * 节点流编辑器 — 关联世界书 + 横向可展开节点图（剧情节点 + 战斗节点）。
 *
 * 交互流程：先选择世界书（可随时切换）→ 图中按剧情分支横向排布：
 *   剧情节点 = data/plots/<plot_id>/index.md 的章节/节拍（story 节点）
 *   战斗节点 = data/combat/nodes/<node_id>.json（经 [COMBAT:<id>] 引用连线）
 * 点击任意节点在右侧抽屉编辑（战斗节点走 BattleNodeForm，剧情节拍走
 * StoryBeatEditor），支持增删节点。节点数据归属所选世界书（worldbook_id）。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useApi } from "../../hooks/useApi";
import { useAppStore } from "../../stores/appStore";
import type {
  BattleNodeOverviewDTO, CombatNodeGraphDTO, PlotFlowBeatDTO,
  PlotFlowChapterDTO, PlotFlowDTO, WorldBookSummary,
} from "../../types";
import BattleNodeForm from "./BattleNodeForm";
import StoryBeatEditor from "./StoryBeatEditor";

const PROGRESS_BADGE: Record<string, { label: string; cls: string }> = {
  done: { label: "已完成", cls: "text-emerald-300 border-emerald-700/60" },
  current: { label: "进行中", cls: "text-amber-300 border-amber-600/60" },
  locked: { label: "未到达", cls: "text-gray-400 border-gray-600/60" },
};

type Drawer =
  | { kind: "battle"; nodeId: string }
  | { kind: "story"; plotId: string; beatId: string | null }
  | null;

interface Props {
  sessionId?: string | null;
}

export default function NodeFlowEditor({ sessionId }: Props) {
  const api = useApi();
  const { combatNodeJumpId, setCombatNodeJumpId } = useAppStore();

  const [books, setBooks] = useState<WorldBookSummary[]>([]);
  const [bookId, setBookId] = useState<string>("");
  const [graph, setGraph] = useState<CombatNodeGraphDTO | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<Drawer>(null);
  const [collapsedChapters, setCollapsedChapters] = useState<Set<string>>(new Set());
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  /** 战斗节点跳转：等图加载完后打开对应抽屉 */
  const [pendingNodeId, setPendingNodeId] = useState<string | null>(combatNodeJumpId);

  const bookName = (id: string) => books.find((b) => b.id === id)?.name || id;

  // ── 世界书列表 + 初始选择 ──
  useEffect(() => {
    (async () => {
      try {
        const res = await api.listWorldbooks();
        const list: WorldBookSummary[] = res.books || [];
        setBooks(list);
        if (list.length > 0) {
          setBookId((prev) => (prev && list.some((b) => b.id === prev) ? prev : list[0].id));
        }
      } catch (e: any) {
        setError(e.message || "世界书列表加载失败");
      }
    })();
  }, [api]);

  // ── 加载节点图 ──
  const loadGraph = useCallback(async (id: string) => {
    if (!id) {
      setGraph(null);
      return;
    }
    setLoading(true);
    try {
      const g = await api.getCombatNodeGraph(id, sessionId || undefined);
      setGraph(g);
      setError(null);
    } catch (e: any) {
      setError(e.message || "节点图加载失败");
      setGraph(null);
    } finally {
      setLoading(false);
    }
  }, [api, sessionId]);

  useEffect(() => { loadGraph(bookId); }, [bookId, loadGraph]);

  // ── 战斗节点跳转（战前卡片等入口）→ 定位书 + 打开抽屉 ──
  useEffect(() => {
    if (!pendingNodeId || !graph) return;
    const row = graph.nodes.find((n) => n.node_id === pendingNodeId);
    if (row) {
      setDrawer({ kind: "battle", nodeId: pendingNodeId });
      if (combatNodeJumpId) setCombatNodeJumpId(null);
      setPendingNodeId(null);
    }
  }, [graph, pendingNodeId, combatNodeJumpId, setCombatNodeJumpId]);

  // 跳转节点不在当前书 → 切到其归属书（总览接口按节点反查）
  useEffect(() => {
    if (!pendingNodeId || !graph) return;
    if (graph.nodes.some((n) => n.node_id === pendingNodeId)) return;
    let cancelled = false;
    api.listCombatNodes().then((res) => {
      if (cancelled) return;
      const row = (res.nodes || []).find((n) => n.node_id === pendingNodeId);
      if (row?.worldbook_id && row.worldbook_id !== bookId) {
        setBookId(row.worldbook_id);
      } else {
        setCombatNodeJumpId(null);
        setPendingNodeId(null);
      }
    }).catch(() => {
      setCombatNodeJumpId(null);
      setPendingNodeId(null);
    });
    return () => { cancelled = true; };
  }, [pendingNodeId, graph, bookId, api, setCombatNodeJumpId]);

  // ── 新建战斗节点（归属当前世界书）──
  const createNode = useCallback(async () => {
    if (!newId.trim() || !bookId) return;
    setBusy(true);
    try {
      await api.createCombatNode(newId.trim(), newName.trim() || newId.trim(), bookId);
      setNewId("");
      setNewName("");
      await loadGraph(bookId);
      setDrawer({ kind: "battle", nodeId: newId.trim() });
    } catch (e: any) {
      setError(e.message || "新建失败");
    } finally {
      setBusy(false);
    }
  }, [api, newId, newName, bookId, loadGraph]);

  const toggleChapter = (key: string) => {
    setCollapsedChapters((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // ── 节点索引：id → overview 行（渲染战斗节点卡片用） ──
  const nodeIndex = useMemo(() => {
    const map = new Map<string, BattleNodeOverviewDTO>();
    graph?.nodes.forEach((n) => map.set(n.node_id, n));
    return map;
  }, [graph]);

  // 已上图（被剧情引用）的战斗节点 id 集合；其余进「未绑定」区
  const attachedIds = useMemo(() => {
    const ids = new Set<string>();
    graph?.plots.forEach((p) => {
      p.combat_nodes.forEach((id) => ids.add(id));
      p.chapters.forEach((c) => {
        c.combat_nodes.forEach((id) => ids.add(id));
        c.beats.forEach((b) => b.combat_nodes.forEach((id) => ids.add(id)));
      });
    });
    return ids;
  }, [graph]);

  const unboundNodes = useMemo(
    () => (graph?.nodes || []).filter((n) => !attachedIds.has(n.node_id)),
    [graph, attachedIds],
  );

  // ── 渲染小件 ──

  const renderConnector = () => (
    <span className="self-start mt-7 text-gray-600 shrink-0 select-none px-0.5">→</span>
  );

  const renderBattleCard = (nodeId: string, key?: string) => {
    const row = nodeIndex.get(nodeId);
    if (!row) {
      // 剧情引用了但不在当前书（其它世界书或未创建）
      return (
        <div
          key={key || nodeId}
          className="w-40 shrink-0 rounded-lg border border-dashed border-gray-700 bg-gray-900/40 p-2"
          title="该节点属于其他世界书或尚未创建"
        >
          <p className="text-[10px] text-gray-500">⚠ 外部引用</p>
          <p className="text-xs text-gray-400 truncate font-mono">{nodeId}</p>
        </div>
      );
    }
    const badge = row.progress ? PROGRESS_BADGE[row.progress.state] : null;
    return (
      <button
        key={key || nodeId}
        onClick={() => setDrawer({ kind: "battle", nodeId })}
        className={
          "w-40 shrink-0 text-left rounded-lg border p-2 transition-colors " +
          (row.missing
            ? "border-amber-700/60 bg-amber-950/30 hover:border-amber-500"
            : "border-gray-700 bg-gray-900 hover:border-amber-500/60 hover:bg-gray-800")
        }
        title={`${row.summary || row.name}\n${row.node_id}`}
      >
        <div className="flex items-center gap-1">
          <span className="text-[11px] text-amber-400 shrink-0">⚔</span>
          <span className={"text-[11px] truncate " + (row.missing ? "text-amber-300" : "text-gray-200")}>
            {row.name}
          </span>
        </div>
        <div className="text-[9px] text-gray-500 truncate font-mono">{row.node_id}</div>
        <div className="text-[9px] text-gray-500 flex items-center gap-1 flex-wrap">
          {row.rows ? <span>{row.rows}×{row.cols}</span> : null}
          {row.unit_total ? <span>{row.unit_total} 敌</span> : null}
        </div>
        <div className="flex items-center gap-1 mt-0.5">
          {row.missing && <span className="text-[9px] text-amber-400">待创建</span>}
          {badge && (
            <span className={"text-[9px] border rounded px-1 " + badge.cls}>{badge.label}</span>
          )}
        </div>
      </button>
    );
  };

  /** 节拍单元格：剧情卡在上，其引用的战斗节点竖向连线挂在下 */
  const renderBeatCell = (plot: PlotFlowDTO, beat: PlotFlowBeatDTO, isLast: boolean) => {
    const refs = beat.combat_nodes;
    return (
      <div key={beat.id} className="flex items-start shrink-0">
        <div className="flex flex-col items-center gap-0.5">
          <button
            onClick={() => setDrawer({ kind: "story", plotId: plot.plot_id, beatId: beat.id })}
            className="w-40 text-left rounded-lg border border-gray-700 bg-gray-900/80 hover:border-sky-500/60 hover:bg-gray-800 p-2 transition-colors"
            title={`${beat.summary || beat.id}\n点击编辑剧情节拍`}
          >
            <div className="flex items-center gap-1">
              <span className="text-[11px] text-sky-400 shrink-0">▸</span>
              <span className="text-[11px] text-gray-200 truncate">{beat.id}</span>
            </div>
            {beat.summary && (
              <p className="text-[9px] text-gray-500 mt-0.5 leading-snug line-clamp-2">{beat.summary}</p>
            )}
            <div className="text-[9px] text-gray-600 mt-0.5">
              {beat.keep_on_deviate ? "偏离保留" : "偏离重置"}
            </div>
          </button>
          {refs.length > 0 && <span className="text-gray-600 text-[10px] leading-none select-none">↓</span>}
          {refs.map((nid) => renderBattleCard(nid, `${beat.id}-${nid}`))}
        </div>
        {!isLast && renderConnector()}
      </div>
    );
  };

  const renderChapterGroup = (plot: PlotFlowDTO, chapter: PlotFlowChapterDTO, isLast: boolean) => {
    const key = `${plot.plot_id}/${chapter.idx}`;
    const collapsed = collapsedChapters.has(key);
    return (
      <div key={key} className="flex items-start shrink-0">
        <div className="flex flex-col items-center gap-1">
          <button
            onClick={() => toggleChapter(key)}
            className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-gray-200 px-2 py-1 rounded border border-gray-800 bg-gray-900/60 transition-colors"
            title="点击展开/收起章节"
          >
            <span>{collapsed ? "▶" : "▼"}</span>
            <span>章节 {chapter.idx}：{chapter.title}</span>
            <span className="text-gray-600">({chapter.beats.length})</span>
          </button>
          {!collapsed ? (
            <div className="flex items-start">
              {chapter.beats.map((beat, bi) => (
                <div key={beat.id} className="flex items-start">
                  {renderBeatCell(plot, beat, bi === chapter.beats.length - 1 && chapter.combat_nodes.length === 0)}
                </div>
              ))}
              {chapter.combat_nodes.map((nid) => (
                <div key={nid} className="flex flex-col items-center gap-0.5">
                  <span className="text-gray-600 text-[10px] leading-none select-none">↓</span>
                  {renderBattleCard(nid)}
                </div>
              ))}
              {chapter.beats.length === 0 && chapter.combat_nodes.length === 0 && (
                <span className="text-[10px] text-gray-600 italic px-2">(空章节)</span>
              )}
            </div>
          ) : (
            chapter.combat_nodes.length > 0 && (
              <div className="flex items-start pt-1">
                {chapter.combat_nodes.map((nid) => renderBattleCard(nid))}
              </div>
            )
          )}
        </div>
        {!isLast && renderConnector()}
      </div>
    );
  };

  const renderPlotStrip = (plot: PlotFlowDTO) => {
    const crossBook = plot.worldbook_id && plot.worldbook_id !== bookId;
    const noChapters = plot.chapters.length === 0;
    return (
      <div key={plot.plot_id} className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-xs font-medium text-sky-300">📜 {plot.name}</span>
          <span className="text-[10px] text-gray-500 font-mono">{plot.plot_id}</span>
          {crossBook && (
            <span className="text-[9px] px-1 rounded border border-gray-700 text-gray-500"
              title={`该剧情归属：${bookName(plot.worldbook_id)}`}>
              跨书引用
            </span>
          )}
          <div className="flex-1" />
        </div>
        <div className="flex items-start overflow-x-auto pb-2">
          {/* 剧情入口节点 */}
          <button
            onClick={() => setDrawer({ kind: "story", plotId: plot.plot_id, beatId: null })}
            className="w-40 shrink-0 text-left rounded-lg border border-sky-800/60 bg-sky-950/30 hover:border-sky-500 p-2 transition-colors"
            title={`${plot.summary || plot.name}\n点击打开剧情编辑`}
          >
            <div className="flex items-center gap-1">
              <span className="text-[11px] text-sky-400">📜</span>
              <span className="text-[11px] text-gray-200 truncate">{plot.name}</span>
            </div>
            <p className="text-[9px] text-gray-500 mt-0.5 leading-snug line-clamp-2">
              {plot.summary || plot.plot_id}
            </p>
            <div className="text-[9px] text-gray-600 mt-0.5">剧情流程 · {plot.chapters.length} 章</div>
          </button>
          {renderConnector()}
          {plot.chapters.map((ch, ci) => (
            <div key={ch.idx} className="flex items-start">
              {renderChapterGroup(plot, ch, ci === plot.chapters.length - 1 && plot.combat_nodes.length === 0)}
            </div>
          ))}
          {/* 无章节结构的剧情：战斗引用直接挂剧情节点（如 combat-test） */}
          {noChapters && plot.combat_nodes.map((nid) => (
            <div key={nid} className="flex flex-col items-center gap-0.5">
              <span className="text-gray-600 text-[10px] leading-none select-none">↓</span>
              {renderBattleCard(nid)}
            </div>
          ))}
        </div>
      </div>
    );
  };

  // ── 渲染 ──

  return (
    <div className="relative flex flex-col h-full min-h-0 bg-gray-950 text-gray-200">
      {/* ── 顶栏：世界书选择器 + 新建节点 ── */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-800 shrink-0 flex-wrap">
        <span className="text-sm">📖</span>
        <select
          className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs outline-none focus:border-amber-500/50 max-w-[18rem]"
          value={bookId}
          onChange={(e) => { setBookId(e.target.value); setDrawer(null); }}
          title="选择要编辑的世界书（节点数据归属该书，可随时切换）"
        >
          {books.length === 0 && <option value="">（无世界书）</option>}
          {books.map((b) => (
            <option key={b.id} value={b.id}>{b.name}（{b.entry_count} 条）</option>
          ))}
        </select>
        {graph && (
          <span className="text-[10px] text-gray-500">
            {graph.meta.plot_count} 条剧情 · {graph.meta.node_count} 个战斗节点
          </span>
        )}
        <div className="flex-1" />
        <input
          className="w-28 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-[11px] outline-none"
          placeholder="node_id"
          value={newId}
          onChange={(e) => setNewId(e.target.value)}
        />
        <input
          className="w-36 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-[11px] outline-none"
          placeholder="名称（可选）"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <button
          className="text-[11px] px-2 py-1 rounded bg-amber-700/30 border border-amber-600/50 hover:bg-amber-700/50 disabled:opacity-40"
          onClick={createNode}
          disabled={!newId.trim() || !bookId || busy}
          title="在当前世界书下新建战斗节点"
        >＋ 战斗节点</button>
        <button
          className="text-xs px-2 py-1 rounded border border-gray-700 hover:border-amber-500/60"
          onClick={() => loadGraph(bookId)}
          title="刷新"
        >⟳</button>
      </div>

      {/* ── 节点图 ── */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {error && (
          <div className="mb-3 px-3 py-2 rounded border border-red-800/60 bg-red-950/40 text-xs text-red-200">
            {error}
          </div>
        )}
        {!bookId && books.length === 0 && (
          <div className="flex items-center justify-center h-full text-sm text-gray-500">
            请先在「世界书」页创建或导入一本世界书
          </div>
        )}
        {loading && !graph && (
          <div className="flex items-center justify-center h-full text-sm text-gray-500">加载中…</div>
        )}
        {graph && graph.plots.length === 0 && graph.nodes.length === 0 && (
          <div className="flex items-center justify-center h-full text-sm text-gray-500">
            「{bookName(bookId)}」暂无剧情与战斗节点——用上方「＋ 战斗节点」创建，或在剧情文档中用
            <code className="mx-1 text-amber-400">[COMBAT:node_id]</code>引用。
          </div>
        )}
        {graph && graph.plots.map(renderPlotStrip)}
        {graph && unboundNodes.length > 0 && (
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium text-gray-400">📦 未绑定剧情的战斗节点</span>
              <span className="text-[10px] text-gray-600">({unboundNodes.length})</span>
              <div className="flex-1" />
            </div>
            <div className="flex items-start flex-wrap gap-2">
              {unboundNodes.map((n) => renderBattleCard(n.node_id, `unbound-${n.node_id}`))}
            </div>
          </div>
        )}
        {graph && (
          <div className="flex items-center gap-4 text-[10px] text-gray-600 pt-1">
            <span>📜 蓝框 = 剧情流程节点（点击编辑章节/节拍）</span>
            <span>▸ 天蓝卡 = 剧情节拍</span>
            <span>⚔ 卡片 = 战斗节点（↓ 表示由上方节拍触发）</span>
            <span>⚠ 虚线 = 引用了但不在本书的节点</span>
          </div>
        )}
      </div>

      {/* ── 编辑抽屉 ── */}
      {drawer && (
        <div className="absolute inset-y-0 right-0 w-[46rem] max-w-[75%] bg-gray-950 border-l border-gray-700 shadow-2xl z-40 flex flex-col min-h-0">
          {drawer.kind === "battle" ? (
            <BattleNodeForm
              key={`battle-${drawer.nodeId}`}
              nodeId={drawer.nodeId}
              onSaved={() => loadGraph(bookId)}
              onDeleted={() => { setDrawer(null); loadGraph(bookId); }}
              onClose={() => setDrawer(null)}
            />
          ) : (
            <StoryBeatEditor
              key={`story-${drawer.plotId}`}
              plotId={drawer.plotId}
              beatId={drawer.beatId}
              onChanged={() => loadGraph(bookId)}
              onClose={() => setDrawer(null)}
            />
          )}
        </div>
      )}
    </div>
  );
}
