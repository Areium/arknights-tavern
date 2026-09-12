/**
 * 剧情节点图页 — 世界书（设定集）→ 剧情二级菜单 → 整页编辑一张剧情图。
 *
 * 信息架构：
 *   第一级 = 世界书选择（设定集，顶栏下拉，记住上次选择）；
 *   第二级 = 剧情 Tab 条（该书下的多个剧情，如 风雪过境 / 长夜临光 / …）；
 *   一个页面只编辑一个剧情：画布独占内容区，缩放/偏移视图状态按剧情
 *   各自持久化（localStorage），互不干扰。
 *
 * 数据：图文档（布局层）整图存世界书条目（plot_graph_<plot_id>，见
 * src/plot_graphs.py）；剧情/战斗内容仍在 data/plots 与 data/combat/nodes，
 * 图节点用 ref 引用，点开走既有抽屉编辑器（StoryBeatEditor / BattleNodeForm）。
 * 编辑走快照撤销栈（Ctrl+Z / Ctrl+Shift+Z），保存 Ctrl+S，切剧情时自动落盘。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useApi } from "../../hooks/useApi";
import { useAppStore } from "../../stores/appStore";
import type {
  BattleNodeOverviewDTO, CombatNodeGraphDTO,
  PlotGraphDocDTO, PlotGraphNodeDTO, WorldBookSummary,
} from "../../types";
import BattleNodeForm from "./BattleNodeForm";
import StoryBeatEditor from "./StoryBeatEditor";
import GraphCanvas, { type AvailableBeat, type AvailableCombat, type GraphCanvasApi, type GraphNodeDisplay } from "./GraphCanvas";
import {
  emptyGraphDoc, importLayoutFromFlow, lastPlotKey, LAST_BOOK_KEY,
  GraphHistory, loadViewState, removeNodes, saveViewState, withNode,
  type ViewState,
} from "./graphModel";

interface Props { sessionId?: string | null }

type Drawer =
  | { kind: "battle"; nodeId: string }
  | { kind: "story"; plotId: string; beatId: string | null }
  | null;

type Selection = { kind: "node" | "edge"; id: string } | null;

/** 每剧情的会话内缓存：未保存的图 + 撤销栈，切走再切回不丢 */
interface PlotCache {
  doc: PlotGraphDocDTO;
  dirty: boolean;
  hist: GraphHistory;
}

export default function PlotGraphPage({ sessionId }: Props) {
  const api = useApi();
  const { combatNodeJumpId, setCombatNodeJumpId } = useAppStore();

  const [books, setBooks] = useState<WorldBookSummary[]>([]);
  const [bookId, setBookId] = useState("");
  const [overview, setOverview] = useState<CombatNodeGraphDTO | null>(null);
  const [savedGraphs, setSavedGraphs] = useState<Set<string>>(new Set());
  const [plotId, setPlotId] = useState("");
  const [doc, setDoc] = useState<PlotGraphDocDTO | null>(null);
  const [view, setView] = useState<ViewState>({ x: 0, y: 0, zoom: 1 });
  const [selected, setSelected] = useState<Selection>(null);
  const [drawer, setDrawer] = useState<Drawer>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [combatModal, setCombatModal] = useState<{ wx: number; wy: number; id: string; name: string; error: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<{ status: "idle" | "saving" | "saved" | "error"; text: string }>({ status: "idle", text: "" });
  const [version, setVersion] = useState(0); // 缓存可变对象 → 用版本号驱动重渲染

  const caches = useRef(new Map<string, PlotCache>());
  const canvasApi = useRef<GraphCanvasApi | null>(null);
  const viewPersist = useRef<number | undefined>(undefined);
  const dirty = useMemo(() => {
    void version;
    return plotId ? (caches.current.get(plotId)?.dirty ?? false) : false;
  }, [plotId, version, doc]);

  const bookName = (id: string) => books.find((b) => b.id === id)?.name || id;
  const currentPlot = useMemo(
    () => overview?.plots.find((p) => p.plot_id === plotId) ?? null,
    [overview, plotId],
  );

  // ── 世界书列表 + 记住上次选择 ──
  useEffect(() => {
    (async () => {
      try {
        const res = await api.listWorldbooks();
        const list: WorldBookSummary[] = res.books || [];
        setBooks(list);
        if (list.length > 0) {
          const last = (() => { try { return localStorage.getItem(LAST_BOOK_KEY) || ""; } catch { return ""; } })();
          setBookId((prev) => prev || (last && list.some((b) => b.id === last) ? last : list[0].id));
        }
      } catch (e: any) {
        setError(e.message || "世界书列表加载失败");
      }
    })();
  }, [api]);

  // ── 换书：加载剧情总览 + 已存图列表 ──
  const loadOverview = useCallback(async (id: string) => {
    if (!id) { setOverview(null); return; }
    setLoading(true);
    try {
      const [g, graphs] = await Promise.all([
        api.getCombatNodeGraph(id, sessionId || undefined),
        api.listPlotGraphs(id).catch(() => ({ graphs: [] as string[] })),
      ]);
      setOverview(g);
      setSavedGraphs(new Set(graphs.graphs || []));
      setError(null);
    } catch (e: any) {
      setError(e.message || "剧情总览加载失败");
      setOverview(null);
    } finally {
      setLoading(false);
    }
  }, [api, sessionId]);

  useEffect(() => { loadOverview(bookId); }, [bookId, loadOverview]);
  useEffect(() => {
    try { if (bookId) localStorage.setItem(LAST_BOOK_KEY, bookId); } catch { /* ignore */ }
  }, [bookId]);

  // 总览就绪后恢复上次选中剧情（记住上次选中的剧情），否则选第一个
  useEffect(() => {
    if (!overview || overview.plots.length === 0) return;
    if (overview.plots.some((p) => p.plot_id === plotId)) return;
    let last = "";
    try { last = localStorage.getItem(lastPlotKey(bookId)) || ""; } catch { /* ignore */ }
    const next = last && overview.plots.some((p) => p.plot_id === last) ? last : overview.plots[0].plot_id;
    setPlotId(next);
  }, [overview, plotId, bookId]);

  // ── 换剧情：视图落盘 → 取缓存/拉取图文档 ──
  const switchPlot = useCallback((next: string) => {
    if (next === plotId) return;
    saveViewState(plotId, view);           // 旧剧情视图立即落盘
    setSelected(null);
    setDrawer(null);
    setConfirmDelete(null);
    setPlotId(next);
    try { localStorage.setItem(lastPlotKey(bookId), next); } catch { /* ignore */ }
  }, [plotId, view, bookId]);

  useEffect(() => {
    if (!plotId || !bookId) { setDoc(null); return; }
    // 有未保存缓存 → 直接用（切走再切回不丢编辑）
    const cached = caches.current.get(plotId);
    if (cached) { setDoc(cached.doc); setVersion((v) => v + 1); return; }
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const res = await api.getPlotGraph(plotId, bookId);
        if (cancelled) return;
        const name = overview?.plots.find((p) => p.plot_id === plotId)?.name || plotId;
        const next = res.graph || emptyGraphDoc(plotId, name, bookId);
        caches.current.set(plotId, { doc: next, dirty: false, hist: new GraphHistory() });
        setDoc(next);
        setError(null);
      } catch (e: any) {
        if (cancelled) return;
        setError(e.message || "节点图加载失败");
        setDoc(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plotId, bookId]);

  // 初始视图：有存档用存档；没有则等首帧后 fit view
  useEffect(() => {
    if (!plotId) return;
    const saved = loadViewState(plotId);
    if (saved) setView(saved);
    else {
      setView({ x: 0, y: 0, zoom: 1 });
      const t = window.setTimeout(() => canvasApi.current?.fit(), 60);
      return () => window.clearTimeout(t);
    }
  }, [plotId]);

  // ── 编辑提交（入撤销栈 + 脏标记） ──
  const commit = useCallback((next: PlotGraphDocDTO) => {
    if (!plotId) return;
    const cache = caches.current.get(plotId);
    if (!cache) return;
    cache.doc = cache.hist.commit(cache.doc, next);
    cache.dirty = true;
    setDoc(next);
    setVersion((v) => v + 1);
  }, [plotId]);

  const undo = useCallback(() => {
    const cache = plotId ? caches.current.get(plotId) : null;
    if (!cache) return;
    const prev = cache.hist.undo(cache.doc);
    if (prev) { cache.doc = prev; cache.dirty = true; setDoc(prev); setVersion((v) => v + 1); }
  }, [plotId]);

  const redo = useCallback(() => {
    const cache = plotId ? caches.current.get(plotId) : null;
    if (!cache) return;
    const next = cache.hist.redo(cache.doc);
    if (next) { cache.doc = next; cache.dirty = true; setDoc(next); setVersion((v) => v + 1); }
  }, [plotId]);

  // ── 保存到世界书 ──
  const save = useCallback(async (silent = false) => {
    if (!plotId || !bookId) return;
    const cache = caches.current.get(plotId);
    if (!cache) return;
    setSaveState({ status: "saving", text: "保存中…" });
    try {
      await api.savePlotGraph(plotId, bookId, cache.doc, currentPlot?.name || "");
      cache.dirty = false;
      setSavedGraphs((prev) => new Set(prev).add(plotId));
      const at = new Date().toLocaleTimeString("zh-CN", { hour12: false });
      setSaveState({ status: "saved", text: `✓ 已保存到「${bookName(bookId)}」 · ${at}` });
      setVersion((v) => v + 1);
    } catch (e: any) {
      setSaveState({ status: "error", text: e.message || "保存失败" });
      if (silent) console.warn("自动保存失败", e);
    }
  }, [plotId, bookId, api, currentPlot, bookName]);

  // ── 快捷键：撤销/重做/保存/删除 ──
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); save(); return; }
      if (typing) return;
      if (mod && !e.shiftKey && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); }
      else if (mod && (e.shiftKey && e.key.toLowerCase() === "z" || e.key.toLowerCase() === "y")) { e.preventDefault(); redo(); }
      else if (!mod && (e.key === "Delete" || e.key === "Backspace")) {
        if (selected?.kind === "node") { e.preventDefault(); setConfirmDelete(selected.id); }
        else if (selected?.kind === "edge" && doc) {
          e.preventDefault();
          commit({ ...doc, edges: doc.edges.filter((ed) => ed.id !== selected.id) });
          setSelected(null);
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save, undo, redo, selected, doc, commit]);

  // ── 视图持久化（防抖 300ms） ──
  const onViewChange = useCallback((v: ViewState) => {
    setView(v);
    window.clearTimeout(viewPersist.current);
    viewPersist.current = window.setTimeout(() => saveViewState(plotId, v), 300);
  }, [plotId]);

  // ── 节点显示解析（引用 → 底层数据元信息） ──
  const displays = useMemo(() => {
    const m = new Map<string, GraphNodeDisplay>();
    if (!doc) return m;
    const nodeIdx = new Map<string, BattleNodeOverviewDTO>();
    overview?.nodes.forEach((n) => nodeIdx.set(n.node_id, n));
    for (const node of doc.nodes) {
      const ref = node.ref;
      if (node.type === "combat" && ref?.node_id) {
        const row = nodeIdx.get(ref.node_id);
        m.set(node.id, {
          title: row?.name || node.title || ref.node_id,
          subtitle: ref.node_id,
          body: row?.summary || node.content || "",
          missing: !row,
          progress: row?.progress && row.progress.state !== "locked" ? row.progress.state : undefined,
        });
      } else if (node.type === "beat" && ref?.beat_id) {
        const beat = currentPlot?.chapters
          .find((c) => c.idx === (ref.chapter_idx ?? -1))?.beats
          .find((b) => b.id === ref.beat_id);
        m.set(node.id, {
          title: ref.beat_id,
          subtitle: ref.chapter_idx ? `章节 ${ref.chapter_idx}` : undefined,
          body: beat?.summary || node.content || "",
          missing: !beat,
        });
      } else if (node.type === "chapter" && ref?.chapter_idx != null) {
        const ch = currentPlot?.chapters.find((c) => c.idx === ref.chapter_idx);
        m.set(node.id, {
          title: node.title || `章节 ${ref.chapter_idx}`,
          subtitle: ch ? `${ch.beats.length} 节拍` : undefined,
          body: node.content || "",
          missing: !ch,
        });
      } else if (node.type === "plot") {
        m.set(node.id, {
          title: currentPlot?.name || node.title || "剧情入口",
          subtitle: currentPlot?.plot_id,
          body: currentPlot?.summary || node.content || "",
        });
      } else {
        m.set(node.id, { title: node.title, body: node.content || "" });
      }
    }
    return m;
  }, [doc, overview, currentPlot]);

  // 未上图资源（右键菜单 / 空态补充入口用）
  const availableBeats = useMemo<AvailableBeat[]>(() => {
    if (!currentPlot || !doc) return [];
    const onGraph = new Set(doc.nodes.map((n) => n.ref?.beat_id).filter(Boolean));
    const out: AvailableBeat[] = [];
    for (const ch of currentPlot.chapters) {
      for (const b of ch.beats) {
        if (!onGraph.has(b.id)) out.push({ chapterIdx: ch.idx, beatId: b.id, label: `${b.id}（章节 ${ch.idx}）` });
      }
    }
    return out;
  }, [currentPlot, doc]);

  const availableCombats = useMemo<AvailableCombat[]>(() => {
    if (!overview || !doc) return [];
    const onGraph = new Set(doc.nodes.map((n) => n.ref?.node_id).filter(Boolean));
    return overview.nodes
      .filter((n) => !onGraph.has(n.node_id))
      .map((n) => ({ nodeId: n.node_id, label: n.name }));
  }, [overview, doc]);

  // ── 节点动作 ──
  const addBeatNode = useCallback((beat: AvailableBeat, wx: number, wy: number) => {
    if (!doc) return;
    commit(withNode(doc, {
      id: `n_${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36).padStart(2, "0")}`,
      type: "beat", title: beat.beatId, content: "",
      x: Math.round(wx - 96), y: Math.round(wy - 32),
      ref: { chapter_idx: beat.chapterIdx, beat_id: beat.beatId },
    }));
  }, [doc, commit]);

  const addCombatGraphNode = useCallback((item: AvailableCombat, wx: number, wy: number) => {
    if (!doc) return;
    const row = overview?.nodes.find((n) => n.node_id === item.nodeId);
    commit(withNode(doc, {
      id: `n_${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36).padStart(2, "0")}`,
      type: "combat", title: row?.name || item.nodeId, content: "",
      x: Math.round(wx - 96), y: Math.round(wy - 32),
      ref: { node_id: item.nodeId },
    }));
  }, [doc, commit, overview]);

  const createCombatNode = useCallback(async () => {
    if (!combatModal || !doc || !bookId) return;
    const id = combatModal.id.trim();
    if (!id) return;
    try {
      await api.createCombatNode(id, combatModal.name.trim() || id, bookId);
      commit(withNode(doc, {
        id: `n_${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36).padStart(2, "0")}`,
        type: "combat", title: combatModal.name.trim() || id, content: "",
        x: Math.round(combatModal.wx - 96), y: Math.round(combatModal.wy - 32),
        ref: { node_id: id },
      }));
      setCombatModal(null);
      setDrawer({ kind: "battle", nodeId: id }); // 立即完善敌人编成等配置
      loadOverview(bookId);
    } catch (e: any) {
      setCombatModal((m) => (m ? { ...m, error: e.message || "创建失败" } : m));
    }
  }, [combatModal, doc, bookId, api, commit, loadOverview]);

  const importLayout = useCallback(() => {
    if (!doc || !currentPlot) return;
    const names = new Map(overview?.nodes.map((n) => [n.node_id, { name: n.name, missing: n.missing }]));
    commit(importLayoutFromFlow(currentPlot, names));
    window.setTimeout(() => canvasApi.current?.fit(), 60);
  }, [doc, currentPlot, overview, commit]);

  const openNode = useCallback((node: PlotGraphNodeDTO) => {
    if (node.type === "combat" && node.ref?.node_id) setDrawer({ kind: "battle", nodeId: node.ref.node_id });
    else if (plotId) setDrawer({ kind: "story", plotId, beatId: node.ref?.beat_id ?? null });
  }, [plotId]);

  const deleteConfirmed = useCallback(() => {
    if (!confirmDelete || !doc) return;
    commit(removeNodes(doc, [confirmDelete]));
    if (selected?.id === confirmDelete) setSelected(null);
    setConfirmDelete(null);
  }, [confirmDelete, doc, commit, selected]);

  // ── 战斗节点跳转（战前卡片等入口）→ 定位书/剧情 + 打开抽屉 ──
  useEffect(() => {
    if (!combatNodeJumpId || !overview || !doc) return;
    const row = overview.nodes.find((n) => n.node_id === combatNodeJumpId);
    if (!row) { setCombatNodeJumpId(null); return; }
    const hostPlot = overview.plots.find((p) =>
      p.combat_nodes.includes(combatNodeJumpId) ||
      p.chapters.some((c) => c.combat_nodes.includes(combatNodeJumpId) || c.beats.some((b) => b.combat_nodes.includes(combatNodeJumpId))));
    if (hostPlot && hostPlot.plot_id !== plotId) switchPlot(hostPlot.plot_id);
    setDrawer({ kind: "battle", nodeId: combatNodeJumpId });
    setCombatNodeJumpId(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [combatNodeJumpId, overview, doc]);

  // ── 渲染 ──
  const plots = overview?.plots || [];

  return (
    <div className="relative flex flex-col h-full min-h-0 bg-gray-950 text-gray-200">
      {/* ── 顶栏：设定集（世界书）+ 编辑工具 + 保存 ── */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-800 shrink-0 flex-wrap">
        <span className="text-sm shrink-0" title="设定集：节点图数据归属的世界书">📖</span>
        <select
          className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs outline-none focus:border-amber-500/50 max-w-[16rem]"
          value={bookId}
          onChange={(e) => { setBookId(e.target.value); setPlotId(""); setDoc(null); setDrawer(null); }}
          title="选择设定集（世界书）——图文档保存到该书"
        >
          {books.length === 0 && <option value="">（无世界书）</option>}
          {books.map((b) => (
            <option key={b.id} value={b.id}>{b.name}</option>
          ))}
        </select>
        {doc && (
          <span className="text-[10px] text-gray-500 shrink-0">
            {doc.nodes.length} 节点 · {doc.edges.length} 连线
          </span>
        )}
        <div className="flex-1" />
        <button
          className="text-xs px-2 py-1 rounded border border-gray-700 hover:border-amber-500/60 disabled:opacity-30"
          onClick={undo} disabled={!dirty}
          title="撤销（Ctrl+Z）"
        >↩ 撤销</button>
        <button
          className="text-xs px-2 py-1 rounded border border-gray-700 hover:border-amber-500/60 disabled:opacity-30"
          onClick={redo}
          title="重做（Ctrl+Shift+Z）"
        >↪ 重做</button>
        <span className="w-px h-4 bg-gray-700" />
        <button
          className="text-[11px] px-2 py-1 rounded border border-gray-700 hover:border-amber-500/60 disabled:opacity-30"
          disabled={!doc}
          onClick={() => { const c = canvasApi.current?.centerWorld(); if (c && doc) {
            commit(withNode(doc, {
              id: `n_${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36).padStart(2, "0")}`,
              type: "note", title: "新节点", content: "", x: Math.round(c.x), y: Math.round(c.y), ref: null,
            }));
          } }}
          title="在视口中心新建自由节点"
        >✎ 自由节点</button>
        <button
          className="text-[11px] px-2 py-1 rounded bg-amber-700/30 border border-amber-600/50 hover:bg-amber-700/50 disabled:opacity-40"
          disabled={!doc}
          onClick={() => { const c = canvasApi.current?.centerWorld(); if (c) setCombatModal({ wx: c.x, wy: c.y, id: "", name: "", error: "" }); }}
          title="新建战斗节点（写入 data/combat/nodes 并上图）"
        >＋ 战斗节点</button>
        <span className="w-px h-4 bg-gray-700" />
        <span className={
          "text-[11px] shrink-0 " +
          (saveState.status === "error" ? "text-red-300"
            : dirty ? "text-amber-400"
            : saveState.status === "saved" ? "text-emerald-300" : "text-gray-500")
        }>
          {saveState.status === "saving" ? "保存中…"
            : dirty ? "● 未保存（Ctrl+S 保存到世界书）"
            : saveState.text || "已同步"}
        </span>
        <button
          className="text-[11px] px-3 py-1 rounded bg-emerald-800/40 border border-emerald-600/50 hover:bg-emerald-800/70 disabled:opacity-40"
          onClick={() => save()} disabled={!plotId || saveState.status === "saving"}
          title="把当前剧情的节点图保存到世界书（Ctrl+S）"
        >💾 保存</button>
      </div>

      {/* ── 二级菜单：剧情切换（一页一剧情） ── */}
      <div className="flex items-center gap-1 px-3 py-1.5 border-b border-gray-800/80 bg-gray-900/40 shrink-0 overflow-x-auto">
        <span className="text-[10px] text-gray-500 mr-1 shrink-0">剧情</span>
        {loading && !overview && <span className="text-xs text-gray-500 px-2">加载中…</span>}
        {plots.map((p) => {
          const active = p.plot_id === plotId;
          const isDirty = caches.current.get(p.plot_id)?.dirty;
          const saved = savedGraphs.has(p.plot_id);
          return (
            <button
              key={p.plot_id}
              onClick={() => switchPlot(p.plot_id)}
              title={`${p.plot_id}${saved ? " · 已存图" : " · 未生成图"}`}
              className={
                "flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs whitespace-nowrap transition-colors " +
                (active
                  ? "bg-sky-700/25 text-sky-200 font-medium border border-sky-500/40"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/40 border border-transparent")
              }
            >
              📜 {p.name}
              {(isDirty || saved) && (
                <i className={"w-1.5 h-1.5 rounded-full " + (isDirty ? "bg-amber-400" : "bg-emerald-500/70")} />
              )}
            </button>
          );
        })}
        {overview && plots.length === 0 && (
          <span className="text-xs text-gray-500 px-2">这本书暂无剧情（data/plots/ 下未标注归属该书）</span>
        )}
        <div className="flex-1" />
        <button
          className="text-xs px-2 py-1 rounded border border-gray-700 hover:border-amber-500/60 shrink-0"
          onClick={() => loadOverview(bookId)}
          title="刷新剧情与节点总览"
        >⟳</button>
      </div>

      {error && (
        <div className="mx-4 mt-2 px-3 py-2 rounded border border-red-800/60 bg-red-950/40 text-xs text-red-200 shrink-0">
          {error}
        </div>
      )}

      {/* ── 画布（一页一剧情，独占内容区） ── */}
      <div className="flex-1 min-h-0 relative">
        {!bookId && books.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-gray-500">
            请先在「世界书」页创建或导入一本世界书
          </div>
        )}
        {bookId && overview && plots.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-gray-500">
            该书暂无剧情可编辑
          </div>
        )}
        {loading && !doc && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-gray-500">加载中…</div>
        )}
        {plotId && doc && (
          <GraphCanvas
            key={plotId}
            doc={doc}
            view={view}
            onViewChange={onViewChange}
            selected={selected}
            onSelect={setSelected}
            onDocChange={commit}
            displays={displays}
            onOpenNode={openNode}
            onRequestDeleteNode={setConfirmDelete}
            onCreateCombat={(wx, wy) => setCombatModal({ wx, wy, id: "", name: "", error: "" })}
            onAddBeat={addBeatNode}
            onAddCombatNode={addCombatGraphNode}
            availableBeats={availableBeats}
            availableCombats={availableCombats}
            onImportLayout={importLayout}
            canvasApiRef={canvasApi}
          />
        )}
      </div>

      {/* ── 编辑抽屉（复用既有编辑器） ── */}
      {drawer && (
        <div className="absolute inset-y-0 right-0 w-[46rem] max-w-[75%] bg-gray-950 border-l border-gray-700 shadow-2xl z-40 flex flex-col min-h-0">
          {drawer.kind === "battle" ? (
            <BattleNodeForm
              key={`battle-${drawer.nodeId}`}
              nodeId={drawer.nodeId}
              onSaved={() => loadOverview(bookId)}
              onDeleted={() => {
                // 底层战斗节点已删 → 同步移除图上引用节点（可撤销）
                if (doc) {
                  const gn = doc.nodes.find((n) => n.type === "combat" && n.ref?.node_id === drawer.nodeId);
                  if (gn) commit(removeNodes(doc, [gn.id]));
                }
                setDrawer(null);
                loadOverview(bookId);
              }}
              onClose={() => setDrawer(null)}
            />
          ) : (
            <StoryBeatEditor
              key={`story-${drawer.plotId}`}
              plotId={drawer.plotId}
              beatId={drawer.beatId}
              onChanged={() => loadOverview(bookId)}
              onClose={() => setDrawer(null)}
            />
          )}
        </div>
      )}

      {/* ── 删除节点二次确认 ── */}
      {confirmDelete && (() => {
        const node = doc?.nodes.find((n) => n.id === confirmDelete);
        const linked = node && (node.type === "beat" || node.type === "combat" || node.type === "chapter");
        return (
          <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/50" onPointerDown={(e) => e.stopPropagation()}>
            <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 w-96 shadow-2xl">
              <p className="text-sm text-gray-100 mb-1">从图中移除「{node?.title || "节点"}」？</p>
              <p className="text-[11px] text-gray-400 mb-3">
                {linked
                  ? "仅移除图上的引用节点，底层剧情/战斗数据不受影响；可用 Ctrl+Z 撤销。"
                  : "该节点的标题与备注只存在于图文档中；可用 Ctrl+Z 撤销。"}
              </p>
              <div className="flex justify-end gap-2">
                <button className="text-xs px-3 py-1.5 rounded border border-gray-700 hover:bg-gray-800"
                  onClick={() => setConfirmDelete(null)}>取消</button>
                <button className="text-xs px-3 py-1.5 rounded bg-red-800 hover:bg-red-700 text-white"
                  onClick={deleteConfirmed}>移除</button>
              </div>
            </div>
          </div>
        );
      })()}

      {/* ── 新建战斗节点弹窗 ── */}
      {combatModal && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/50" onPointerDown={(e) => e.stopPropagation()}>
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 w-96 shadow-2xl">
            <p className="text-sm text-gray-100 mb-3">新建战斗节点（归属「{bookName(bookId)}」）</p>
            <div className="space-y-2 mb-3">
              <input autoFocus className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-xs"
                placeholder="node_id（如 enc_snow_ambush）"
                value={combatModal.id}
                onChange={(e) => setCombatModal({ ...combatModal, id: e.target.value, error: "" })} />
              <input className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-xs"
                placeholder="名称（可选）"
                value={combatModal.name}
                onChange={(e) => setCombatModal({ ...combatModal, name: e.target.value, error: "" })} />
              {combatModal.error && <p className="text-[11px] text-red-300">{combatModal.error}</p>}
            </div>
            <div className="flex justify-end gap-2">
              <button className="text-xs px-3 py-1.5 rounded border border-gray-700 hover:bg-gray-800"
                onClick={() => setCombatModal(null)}>取消</button>
              <button className="text-xs px-3 py-1.5 rounded bg-amber-700 hover:bg-amber-600 text-white disabled:opacity-40"
                disabled={!combatModal.id.trim()}
                onClick={createCombatNode}>创建并上图</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
