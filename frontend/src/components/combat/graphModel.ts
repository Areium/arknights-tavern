/**
 * 剧情节点图模型层 — 类型元数据、几何计算、撤销栈、初始布局生成、视图状态持久化。
 *
 * 坐标系：图内坐标（world）与屏幕坐标（screen）通过视图 {x, y, zoom} 换算：
 *   screen = world * zoom + {x, y}；world = (screen - {x, y}) / zoom。
 * 平移/缩放全部作用在 world 容器的 CSS transform 上（GPU 合成，60fps）。
 */
import type {
  PlotFlowDTO, PlotGraphDocDTO, PlotGraphEdgeDTO, PlotGraphNodeDTO,
  PlotGraphNodeType,
} from "../../types";

// ── 常量 ──

export const NODE_W = 192;          // 节点卡宽度（高度随内容自适应，实时测量）
export const MIN_ZOOM = 0.25;
export const MAX_ZOOM = 2;
export const ZOOM_STEP = 1.2;       // 工具栏 ± 每档倍率
export const WHEEL_ZOOM_SENS = 0.0016;

export const NODE_META: Record<PlotGraphNodeType, { label: string; icon: string }> = {
  plot: { label: "剧情入口", icon: "📜" },
  chapter: { label: "章节", icon: "🗂" },
  beat: { label: "剧情节拍", icon: "▸" },
  combat: { label: "战斗节点", icon: "⚔" },
  note: { label: "自由节点", icon: "✎" },
};
export const NODE_TYPE_ORDER: PlotGraphNodeType[] = ["plot", "chapter", "beat", "combat", "note"];

export const VIEW_KEY_PREFIX = "ark_nodeflow_view:";
export const LAST_BOOK_KEY = "ark_nodeflow_book";
export const EDITOR_W_KEY = "ark_nodeflow_editor_w";
/** 手动双击判定窗口（ms）：画布节点、抽屉拖拽把手共用同一阈值 */
export const DBLCLICK_MS = 320;
export const lastPlotKey = (bookId: string) => `ark_nodeflow_plot:${bookId}`;

export interface ViewState { x: number; y: number; zoom: number }

export const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));

/**
 * 坐标换算的唯一实现（拖拽/平移/缩放/落点全部走这里，避免各处各算一套）。
 * 约定：screen 为「相对视口左上角」的像素坐标（clientX - viewportRect.left）。
 *   screen = world * zoom + view.{x,y}；world = (screen - view.{x,y}) / zoom。
 */
export function screenToWorld(sx: number, sy: number, view: ViewState): { x: number; y: number } {
  return { x: (sx - view.x) / view.zoom, y: (sy - view.y) / view.zoom };
}

export function worldToScreen(wx: number, wy: number, view: ViewState): { x: number; y: number } {
  return { x: wx * view.zoom + view.x, y: wy * view.zoom + view.y };
}

/**
 * 节点拖拽的两个纯函数（唯一实现，供画布与回归脚本共用）：
 *  - dragGrabOffset：按下瞬间指针相对节点左上角的**屏幕**偏移，整个拖拽过程恒定；
 *  - dragWorldPos：由当前指针屏幕坐标 + 该恒定偏移反推节点图内坐标。
 * 这样位移只在屏幕空间取一次差，图内坐标不会逐帧累加，也不会受缩放/平移影响。
 */
export function dragGrabOffset(
  screenX: number, screenY: number, node: { x: number; y: number }, view: ViewState,
): { x: number; y: number } {
  const p = worldToScreen(node.x, node.y, view);
  return { x: screenX - p.x, y: screenY - p.y };
}

export function dragWorldPos(
  screenX: number, screenY: number, grab: { x: number; y: number }, view: ViewState,
): { x: number; y: number } {
  return screenToWorld(screenX - grab.x, screenY - grab.y, view);
}

// ── ID 生成（图内唯一：前缀 + base36 时间戳 + 随机尾） ──

export function genId(prefix: "n" | "e", doc: PlotGraphDocDTO): string {
  for (let i = 0; i < 99; i++) {
    const id = `${prefix}_${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36).padStart(2, "0")}`;
    const taken = prefix === "n"
      ? doc.nodes.some((n) => n.id === id)
      : doc.edges.some((e) => e.id === id);
    if (!taken) return id;
  }
  return `${prefix}_${Date.now().toString(36)}x`;
}

// ── 几何：节点矩形 / 贝塞尔连线 ──

export interface NodeRect { x: number; y: number; w: number; h: number }

/** 估算节点高度（未测量前的兜底；实测值经 ResizeObserver 更新 sizes 表） */
export function estimateNodeH(node: PlotGraphNodeDTO): number {
  const lines = Math.min(3, Math.ceil((node.content?.length || 0) / 22));
  return 58 + lines * 14;
}

/** 由相对位置挑选锚点侧并生成三次贝塞尔 path */
export function edgeGeometry(a: NodeRect, b: NodeRect): { d: string; sx: number; sy: number; tx: number; ty: number } {
  const acx = a.x + a.w / 2, acy = a.y + a.h / 2;
  const bcx = b.x + b.w / 2, bcy = b.y + b.h / 2;
  const dx = bcx - acx, dy = bcy - acy;
  let sx: number, sy: number, tx: number, ty: number, ox: number, oy: number;
  if (Math.abs(dx) * 1.2 >= Math.abs(dy)) {
    // 横向为主：右侧出 → 左侧入（b 在左则反向）
    const flip = dx < 0;
    sx = flip ? a.x : a.x + a.w; tx = flip ? b.x + b.w : b.x;
    sy = acy; ty = bcy;
    ox = Math.max(48, Math.abs(tx - sx) * 0.45); oy = 0;
  } else {
    // 纵向为主：底部出 → 顶部入
    const flip = dy < 0;
    sx = acx; tx = bcx;
    sy = flip ? a.y : a.y + a.h; ty = flip ? b.y + b.h : b.y;
    ox = 0; oy = Math.max(40, Math.abs(ty - sy) * 0.45);
  }
  return { d: `M ${sx} ${sy} C ${sx + ox} ${sy + oy}, ${tx - ox} ${ty - oy}, ${tx} ${ty}`, sx, sy, tx, ty };
}

// ── 撤销/重做（快照栈；每个变更动作入栈一次） ──

const HISTORY_CAP = 60;
const clone = <T,>(v: T): T =>
  typeof structuredClone === "function" ? structuredClone(v) : JSON.parse(JSON.stringify(v));

export class GraphHistory {
  past: PlotGraphDocDTO[] = [];
  future: PlotGraphDocDTO[] = [];

  commit(current: PlotGraphDocDTO, next: PlotGraphDocDTO): PlotGraphDocDTO {
    this.past.push(clone(current));
    if (this.past.length > HISTORY_CAP) this.past.shift();
    this.future = [];
    return next;
  }

  undo(current: PlotGraphDocDTO): PlotGraphDocDTO | null {
    const prev = this.past.pop();
    if (!prev) return null;
    this.future.unshift(clone(current));
    return prev;
  }

  redo(current: PlotGraphDocDTO): PlotGraphDocDTO | null {
    const next = this.future.shift();
    if (!next) return null;
    this.past.push(clone(current));
    return next;
  }
}

/** 不可变图编辑工具（返回新 doc；调用方负责入撤销栈） */

export function withNode(doc: PlotGraphDocDTO, node: PlotGraphNodeDTO): PlotGraphDocDTO {
  const exists = doc.nodes.some((n) => n.id === node.id);
  return {
    ...doc,
    nodes: exists ? doc.nodes.map((n) => (n.id === node.id ? node : n)) : [...doc.nodes, node],
  };
}

export function removeNodes(doc: PlotGraphDocDTO, ids: string[]): PlotGraphDocDTO {
  const drop = new Set(ids);
  return {
    ...doc,
    nodes: doc.nodes.filter((n) => !drop.has(n.id)),
    edges: doc.edges.filter((e) => !drop.has(e.from) && !drop.has(e.to)),
  };
}

export function withEdge(doc: PlotGraphDocDTO, from: string, to: string): { doc: PlotGraphDocDTO; edge: PlotGraphEdgeDTO } {
  const edge: PlotGraphEdgeDTO = { id: genId("e", doc), from, to };
  return { doc: { ...doc, edges: [...doc.edges, edge] }, edge };
}

export function removeEdge(doc: PlotGraphDocDTO, edgeId: string): PlotGraphDocDTO {
  return { ...doc, edges: doc.edges.filter((e) => e.id !== edgeId) };
}

export function rewireEdge(doc: PlotGraphDocDTO, edgeId: string, end: "from" | "to", nodeId: string): PlotGraphDocDTO {
  // 目标端点已存在同向连线 → 视为重复，直接移除旧连线（合并语义）
  const target = doc.edges.find((e) => e.id === edgeId);
  if (!target) return doc;
  const candidate = { from: end === "from" ? nodeId : target.from, to: end === "from" ? target.to : nodeId };
  if (candidate.from === candidate.to) return doc;
  const dup = doc.edges.some((e) => e.id !== edgeId && e.from === candidate.from && e.to === candidate.to);
  return {
    ...doc,
    edges: dup
      ? doc.edges.filter((e) => e.id !== edgeId)
      : doc.edges.map((e) => (e.id === edgeId ? { ...e, ...candidate } : e)),
  };
}

// ── 从剧情结构生成初始布局（图文档为空时的引导） ──

/** 默认布局的排布间距（初始布局与「重置节点位置」共用同一套基准） */
export const LAYOUT_H_GAP = 64;
export const LAYOUT_V_GAP = 36;

/**
 * 依 plot_flows 结构（剧情 → 章节 → 节拍 → 战斗引用）生成左→右主干、
 * 战斗节点下垂挂的初始布局。只做"一次导入"，之后画布完全自由编辑。
 */
export function importLayoutFromFlow(
  plot: PlotFlowDTO,
  combatNames: Map<string, { name: string; missing?: boolean }>,
): PlotGraphDocDTO {
  const nodes: PlotGraphNodeDTO[] = [];
  const edges: PlotGraphEdgeDTO[] = [];
  const H_GAP = LAYOUT_H_GAP, V_GAP = LAYOUT_V_GAP;
  let cursorX = 40;

  const add = (n: Omit<PlotGraphNodeDTO, "id">): PlotGraphNodeDTO => {
    const node: PlotGraphNodeDTO = { ...n, id: `n_${nodes.length}_${Date.now().toString(36).slice(-4)}` };
    nodes.push(node);
    return node;
  };
  const link = (from: PlotGraphNodeDTO, to: PlotGraphNodeDTO) =>
    edges.push({ id: `e_${edges.length}_${Date.now().toString(36).slice(-4)}`, from: from.id, to: to.id });

  const plotNode = add({
    type: "plot", title: plot.name || plot.plot_id,
    content: plot.summary || "", x: cursorX, y: 200, ref: null,
  });
  cursorX += NODE_W + H_GAP;

  /** 战斗引用节点（引用已存在则复用，支持同节点被多处引用） */
  const combatByRef = new Map<string, PlotGraphNodeDTO>();
  const addCombat = (nodeId: string, x: number, y: number): PlotGraphNodeDTO => {
    const found = combatByRef.get(nodeId);
    if (found) return found;
    const meta = combatNames.get(nodeId);
    const node = add({
      type: "combat", title: meta?.name || nodeId, content: "",
      x, y, ref: { node_id: nodeId },
    });
    combatByRef.set(nodeId, node);
    return node;
  };

  let prevEnd: PlotGraphNodeDTO = plotNode;
  if (plot.chapters.length === 0) {
    // 无章节结构（如 combat-test）：战斗引用直接挂剧情入口
    let y = 360;
    for (const nid of plot.combat_nodes) {
      const c = addCombat(nid, cursorX, y);
      link(plotNode, c);
      y += estimateNodeH(c) + V_GAP;
    }
  } else {
    for (const chapter of plot.chapters) {
      const chNode = add({
        type: "chapter", title: `章节 ${chapter.idx}：${chapter.title}`,
        content: "", x: cursorX, y: 200, ref: { chapter_idx: chapter.idx },
      });
      link(prevEnd, chNode);
      // 章节直属战斗引用下垂
      let y = 200 + 96 + V_GAP;
      for (const nid of chapter.combat_nodes) {
        const c = addCombat(nid, cursorX, y);
        link(chNode, c);
        y += estimateNodeH(c) + V_GAP;
      }
      prevEnd = chNode;
      // 章内节拍链
      let beatPrev: PlotGraphNodeDTO | null = null;
      for (const beat of chapter.beats) {
        cursorX += NODE_W + H_GAP;
        const bNode = add({
          type: "beat", title: beat.id, content: beat.summary || "",
          x: cursorX, y: 200, ref: { chapter_idx: chapter.idx, beat_id: beat.id },
        });
        link(beatPrev ?? chNode, bNode);
        // 节拍引用的战斗节点下垂
        let by = 200 + 96 + V_GAP;
        for (const nid of beat.combat_nodes) {
          const c = addCombat(nid, cursorX, by);
          link(bNode, c);
          by += estimateNodeH(c) + V_GAP;
        }
        beatPrev = bNode;
        prevEnd = bNode;
      }
      cursorX += NODE_W + H_GAP;
    }
  }

  return {
    schema_version: 1,
    plot_id: plot.plot_id,
    title: plot.name,
    worldbook_id: plot.worldbook_id,
    nodes,
    edges,
  };
}

/** 空白图文档 */
export function emptyGraphDoc(plotId: string, title: string, bookId: string): PlotGraphDocDTO {
  return { schema_version: 1, plot_id: plotId, title, worldbook_id: bookId, nodes: [], edges: [] };
}

// ── 重置节点位置（基准 = 剧情结构算出的默认布局） ──

/**
 * 节点身份键：引用型节点按「类型 + ref」对齐（图的 id 会随导入/重建变化，不能作为身份），
 * 自由节点没有底层引用，不参与默认布局对齐。
 */
export function nodeIdentity(node: PlotGraphNodeDTO): string {
  const r = node.ref ?? {};
  switch (node.type) {
    case "plot": return "plot";
    case "chapter": return `chapter:${r.chapter_idx ?? "?"}`;
    case "beat": return `beat:${r.chapter_idx ?? "?"}:${r.beat_id ?? "?"}`;
    case "combat": return `combat:${r.node_id ?? "?"}`;
    default: return `note:${node.id}`;
  }
}

export interface ResetPositionsResult {
  doc: PlotGraphDocDTO;
  /** 命中默认布局、位置被重置的节点数 */
  matched: number;
  /** 默认布局里没有对应项（自由节点 / 重复引用）而排到布局右侧空位的节点数 */
  placed: number;
  /** 默认布局里有、当前图上没有的节点数（只统计不新增，保持节点集合不变） */
  missing: number;
}

/**
 * 重置节点位置：用默认布局（importLayoutFromFlow 的产物）的坐标覆盖现有节点的 x/y。
 * 只改坐标——节点集合、节点内容与连线关系全部保留；自由节点/重复引用排到布局右侧一列。
 */
export function resetNodePositions(doc: PlotGraphDocDTO, layout: PlotGraphDocDTO): ResetPositionsResult {
  const pos = new Map<string, { x: number; y: number }>();
  for (const n of layout.nodes) {
    const key = nodeIdentity(n);
    if (!pos.has(key)) pos.set(key, { x: n.x, y: n.y });
  }

  // 落位区：默认布局包围盒右侧一列（既有的自由节点不至于压在主干上）
  let maxX = 40, minY = 0;
  for (const n of layout.nodes) {
    maxX = Math.max(maxX, n.x + NODE_W);
    minY = Math.min(minY, n.y);
  }
  const overflowX = Math.round(maxX + LAYOUT_H_GAP * 2);
  let overflowY = minY;

  const used = new Set<string>();
  let matched = 0, placed = 0;

  const nodes = doc.nodes.map((n) => {
    const key = nodeIdentity(n);
    const p = pos.get(key);
    if (p && !used.has(key)) {
      used.add(key);
      matched += 1;
      return { ...n, x: Math.round(p.x), y: Math.round(p.y) };
    }
    const y = overflowY;
    overflowY += estimateNodeH(n) + LAYOUT_V_GAP;
    placed += 1;
    return { ...n, x: overflowX, y: Math.round(y) };
  });

  const missing = [...pos.keys()].filter((k) => !used.has(k)).length;
  return { doc: { ...doc, nodes }, matched, placed, missing };
}

// ── 视图状态（每剧情独立，localStorage 持久化） ──

export function loadViewState(plotId: string): ViewState | null {
  try {
    const raw = localStorage.getItem(VIEW_KEY_PREFIX + plotId);
    if (!raw) return null;
    const v = JSON.parse(raw);
    if (typeof v?.x === "number" && typeof v?.y === "number" && typeof v?.zoom === "number") {
      return { x: v.x, y: v.y, zoom: clampZoom(v.zoom) };
    }
  } catch { /* ignore */ }
  return null;
}

export function saveViewState(plotId: string, view: ViewState) {
  try { localStorage.setItem(VIEW_KEY_PREFIX + plotId, JSON.stringify(view)); } catch { /* ignore */ }
}

// ── 编辑器抽屉宽度（全局一份，localStorage 持久化） ──

/** 抽屉最小宽度（px）；上限按画布容器宽度动态算（92%） */
export const EDITOR_W_MIN = 360;
/** 抽屉默认宽度 = 画布容器宽度的 50%（"半屏左右"）；用户拖拽后以 px 覆盖 */
export const EDITOR_W_RATIO = 0.5;

export function loadEditorWidth(): number | null {
  try {
    const raw = localStorage.getItem(EDITOR_W_KEY);
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch { return null; }
}

export function saveEditorWidth(w: number) {
  try { localStorage.setItem(EDITOR_W_KEY, String(Math.round(w))); } catch { /* ignore */ }
}

/** 清除自定义宽度 → 回到默认半屏 */
export function clearEditorWidth() {
  try { localStorage.removeItem(EDITOR_W_KEY); } catch { /* ignore */ }
}

/** 把期望宽度夹到 [EDITOR_W_MIN, 容器宽 92%] 区间 */
export function clampEditorWidth(w: number, containerW: number): number {
  const max = Math.max(EDITOR_W_MIN, containerW * 0.92);
  return Math.min(max, Math.max(EDITOR_W_MIN, w));
}

/** fit view：把所有节点纳入视口（含边距），返回新视图 */
export function fitView(nodes: PlotGraphNodeDTO[], sizes: Map<string, NodeRect>, vw: number, vh: number): ViewState {
  if (nodes.length === 0) return { x: 0, y: 0, zoom: 1 };
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const n of nodes) {
    const w = sizes.get(n.id)?.w ?? NODE_W;
    const h = sizes.get(n.id)?.h ?? estimateNodeH(n);
    minX = Math.min(minX, n.x); minY = Math.min(minY, n.y);
    maxX = Math.max(maxX, n.x + w); maxY = Math.max(maxY, n.y + h);
  }
  const pad = 80;
  const zoom = clampZoom(Math.min((vw - pad * 2) / Math.max(1, maxX - minX), (vh - pad * 2) / Math.max(1, maxY - minY), 1.5));
  return {
    zoom,
    x: (vw - (maxX - minX) * zoom) / 2 - minX * zoom,
    y: (vh - (maxY - minY) * zoom) / 2 - minY * zoom,
  };
}
