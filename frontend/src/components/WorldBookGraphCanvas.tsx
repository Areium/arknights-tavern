import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  entryNodeId, layoutWorldBookGraph, spreadWorldBookGraph, worldBookEdgeGeometry,
  type GraphPoint, type WorldBookGraphData, type WorldBookGraphNode,
} from "../utils/worldbookGraph";
import {
  DEPENDENCY_ROLES, ROLE_GLYPHS, ROLE_HINTS, ROLE_LABELS, layoutDependencyTree,
} from "../utils/worldbookDependency";
import { pickedInRect, type BatchRect } from "../utils/worldbookBatch";
import WorldBookGraphIcon from "./WorldBookGraphIcon";

type Camera = { x: number; y: number; zoom: number };
type Gesture = {
  kind: "pan" | "node" | "marquee";
  pointerId: number;
  startX: number;
  startY: number;
  origin: GraphPoint;
  nodeId?: string;
  /** 本次拖动要一起位移的节点：被拖动节点 + 直接相连节点，已去重。 */
  follow?: string[];
  /** 世界坐标下的实时位移；拖动中只写这一个值，节点位置在抬手时一次性提交。 */
  offset?: GraphPoint;
  moved: boolean;
};
export type TreeViewOptions = { depthLimit: number; collapsed: Set<string>; showLoose: boolean };
export type GraphColoring = "kind" | "role";
const KINDS = { worldview: "世界观", character: "角色", other: "其他" };
const clampZoom = (value: number) => Math.max(0.15, Math.min(2.5, value));
/** 批量连线时最多画这么多条待定边，避免上百个源把画布糊住。 */
const PENDING_EDGE_LIMIT = 12;
/** 「拖动跟随」开关的持久化键。它是全局画布偏好，与具体世界书无关。 */
const FOLLOW_PREF_KEY = "ark_wbg_drag_follow";

/**
 * 读取「拖动跟随」开关，默认开启（与跟随功能引入时的行为一致，老用户不会突然发现手感变了）。
 * 只有用户显式关掉才写 "0"；localStorage 不可用（隐私模式等）时静默回落到默认值。
 */
function readFollowPref(): boolean {
  try { return localStorage.getItem(FOLLOW_PREF_KEY) !== "0"; } catch { return true; }
}

function writeFollowPref(enabled: boolean) {
  try { localStorage.setItem(FOLLOW_PREF_KEY, enabled ? "1" : "0"); } catch { /* ignore */ }
}

/**
 * 拖动跟随集合：被拖动节点自身 + 与它在**当前图上真实存在的边**直接相连的节点。
 *
 * 只取一跳，所以不会顺着链条无限展开，也就不存在递归；用 Set 去重，
 * 双向边（A→B 与 B→A 同时存在）或平行边不会让同一节点被位移两次。
 * 节点自身恒为集合第一项，拖动高亮按 `follow[0]` 取被拖动节点。
 * 关闭「拖动跟随」时不调用本函数，集合退化为只含被拖动节点自身。
 */
function followSetFor(graph: WorldBookGraphData, nodeId: string): string[] {
  const ids = new Set<string>([nodeId]);
  for (const edge of graph.edges) {
    if (edge.from === nodeId) ids.add(edge.to);
    else if (edge.to === nodeId) ids.add(edge.from);
  }
  return [...ids];
}

function boundsFor(graph: WorldBookGraphData, positions: Record<string, GraphPoint>, pad = 55) {
  const points = graph.nodes.flatMap((node) => positions[node.id] ? [{ ...positions[node.id], radius: node.radius }] : []);
  if (!points.length) return { left: -200, top: -150, width: 400, height: 300 };
  const left = Math.min(...points.map((p) => p.x - p.radius - pad));
  const top = Math.min(...points.map((p) => p.y - p.radius - 25));
  return { left, top,
    width: Math.max(...points.map((p) => p.x + p.radius + pad)) - left,
    height: Math.max(...points.map((p) => p.y + p.radius + 50)) - top,
  };
}

export default function WorldBookGraphCanvas({ graph, view, selectedId, selectedEdgeId, linkFromUids, pickedIds, busy, coloring, tree,
  onToggleCollapse, onSelectNode, onPickMany, onSelectEdge, onLinkStart, onCancelLink, onClear, onDropEntry,
}: {
  graph: WorldBookGraphData;
  view: "taxonomy" | "dependencies" | "tree";
  selectedId: string | null;
  selectedEdgeId: string | null;
  /** 批量连线的来源条目 UID；非空时进入「点击目标建立依赖」模式。 */
  linkFromUids: string[] | null;
  /** 批量选中的条目 UID。 */
  pickedIds: string[];
  busy: boolean;
  coloring: GraphColoring;
  tree: TreeViewOptions | null;
  onToggleCollapse: (uid: string) => void;
  /** additive 为 true 表示 Ctrl / Shift 点击：加入或移出批量选择。 */
  onSelectNode: (node: WorldBookGraphNode, additive: boolean) => void;
  onPickMany: (uids: string[], additive: boolean) => void;
  onSelectEdge: (id: string) => void;
  onLinkStart: (uid: string) => void;
  onCancelLink: () => void;
  onClear: () => void;
  onDropEntry: (event: React.DragEvent) => void;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const marqueeRef = useRef<BatchRect | null>(null);
  const id = useId().replace(/:/g, "");
  const [camera, setCamera] = useState<Camera>({ x: 0, y: 0, zoom: 1 });
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [cursor, setCursor] = useState<GraphPoint | null>(null);
  const [dragging, setDragging] = useState(false);
  const [marquee, setMarquee] = useState<BatchRect | null>(null);
  // 拖动期间的两个轻量状态：跟随集合（按下时定一次）与位移（每帧一个点）。
  // positions 是 N 个节点的整表，只在抬手时写一次，避免每帧重建整表导致卡顿。
  const [follow, setFollow] = useState<string[] | null>(null);
  const [dragOffset, setDragOffset] = useState<GraphPoint | null>(null);
  /** 拖动跟随开关：关掉后拖动只移动被拖动的那个节点，其余节点留在原地。 */
  const [followEnabled, setFollowEnabled] = useState(readFollowPref);
  const [layoutVersion, setLayoutVersion] = useState(0);
  const dependencyView = view !== "taxonomy";
  // 依赖树只画条目：层级语义由 depth 承担，分类归属交给「分类结构」视图与节点目录。
  const allowedUids = useMemo(() => new Set(graph.nodes.filter((node) => node.kind === "entry").map((node) => node.refId)), [graph.nodes]);
  const treeLayout = useMemo(() => (tree && graph.tree
    ? layoutDependencyTree(graph.tree, {
      allowed: allowedUids, depthLimit: tree.depthLimit, collapsed: tree.collapsed, showLoose: tree.showLoose,
    })
    : null), [graph.tree, tree, allowedUids]);
  // 依赖树按条目 UID 布局，画布按 entry:<uid> 取点，这里做一次显式映射。
  const treePositions = useMemo(() => {
    if (!treeLayout) return null;
    const result: Record<string, GraphPoint> = {};
    for (const node of graph.nodes) {
      const point = treeLayout.positions[node.refId];
      if (point) result[node.id] = point;
    }
    return result;
  }, [treeLayout, graph.nodes]);
  // Flags and names do not invalidate node positions while the user edits a policy.
  const layoutKey = JSON.stringify([graph.nodes.map((node) => node.id), graph.edges.map((edge) => [edge.from, edge.to, edge.kind])]);
  // 依赖树会随层级上限与折叠变化重排；力导向布局只为节点/边的集合变化重排。
  const treeKey = treeLayout ? `tree:${layoutKey}:${layoutVersion}:${tree?.depthLimit}:${tree?.showLoose}:${[...(tree?.collapsed || [])].sort().join(",")}` : "";
  const layoutSignature = treeKey || `force:${layoutKey}:${layoutVersion}`;
  const initial = useMemo(() => (treePositions ?? layoutWorldBookGraph(graph)), [layoutSignature, layoutVersion]);
  const [positions, setPositions] = useState(initial);
  const fittedKey = useRef("");
  const fittedSize = useRef("");
  const autoFit = useRef(true);
  const nodeMap = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph.nodes]);
  const pickedSet = useMemo(() => new Set(pickedIds), [pickedIds]);
  const linkSources = linkFromUids || [];
  const visibleEntryUids = useMemo(() => graph.nodes
    .filter((node) => node.kind === "entry" && positions[node.id])
    .map((node) => node.refId), [graph.nodes, positions]);
  const followSet = useMemo(() => (follow ? new Set(follow) : null), [follow]);
  /** follow 的第一项恒为被拖动的节点（见 followSetFor）。 */
  const dragNodeId = follow?.[0] ?? null;
  /**
   * 画布取点入口：拖动期间读「已提交位置 + 实时位移」，所以连线端点与节点同步跟随；
   * 拖动结束位移归零、位置已写进 positions，画面不会跳。
   * 缩略图仍读 positions（拖动中不跟随），避免视口框跟着位移抖动。
   */
  const at = useCallback((id: string): GraphPoint | undefined => {
    const base = positions[id];
    if (!base || !dragOffset || !followSet?.has(id)) return base;
    return { x: base.x + dragOffset.x, y: base.y + dragOffset.y };
  }, [positions, dragOffset, followSet]);
  const cameraRef = useRef(camera);
  cameraRef.current = camera;
  const bounds = useMemo(() => boundsFor(graph, positions), [graph, positions]);
  const activeId = linkSources.length ? entryNodeId(linkSources[0]) : hoverId || selectedId;
  const related = useMemo(() => {
    if (!activeId && !selectedEdgeId) return null;
    const result = new Set(activeId ? [activeId] : []);
    for (const edge of graph.edges) {
      if (edge.from === activeId || edge.to === activeId || edge.id === selectedEdgeId) {
        result.add(edge.from); result.add(edge.to);
      }
    }
    return result;
  }, [activeId, selectedEdgeId, graph.edges]);
  const edgeDirections = useMemo(() => new Set(graph.edges.filter((edge) => edge.kind === "dependency")
    .map((edge) => JSON.stringify([edge.from, edge.to]))), [graph.edges]);

  const fitPositions = useCallback((next: Record<string, GraphPoint>) => {
    if (!size.width || !size.height) return;
    const box = boundsFor(graph, next);
    const zoom = clampZoom(Math.min(1.15, Math.max(80, size.width - 110) / box.width, Math.max(80, size.height - 150) / box.height));
    setCamera({ x: size.width / 2 - (box.left + box.width / 2) * zoom,
      y: size.height / 2 - (box.top + box.height / 2) * zoom - 10, zoom });
  }, [graph, size]);

  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    let previous = { width: 0, height: 0 };
    const observer = new ResizeObserver(([entry]) => {
      const next = { width: entry.contentRect.width, height: entry.contentRect.height };
      const deltaX = next.width - previous.width, deltaY = next.height - previous.height;
      if (previous.width) setCamera((current) => ({ ...current,
        x: current.x + deltaX / 2, y: current.y + deltaY / 2,
      }));
      previous = next;
      setSize(next);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!size.width || !size.height) return;
    const key = layoutSignature;
    const sizeKey = size.width + ":" + size.height;
    const newLayout = fittedKey.current !== key;
    if (!newLayout && (!autoFit.current || fittedSize.current === sizeKey)) return;
    if (newLayout) autoFit.current = true;
    fittedKey.current = key;
    fittedSize.current = sizeKey;
    // 分层树保持等距整齐，不再横向拉伸；力导向网络继续按视口比例铺开。
    const arranged = treePositions ?? spreadWorldBookGraph(initial, Math.max(100, size.width - 110) / Math.max(100, size.height - 150));
    setPositions(arranged);
    fitPositions(arranged);
  }, [initial, layoutSignature, size, fitPositions, treePositions]);

  useEffect(() => {
    if (!selectedId || !positions[selectedId] || !size.width) return;
    const point = positions[selectedId], current = cameraRef.current;
    const x = point.x * current.zoom + current.x, y = point.y * current.zoom + current.y;
    if (x < 65 || x > size.width - 65 || y < 65 || y > size.height - 90) {
      setCamera({ ...current, x: size.width / 2 - point.x * current.zoom, y: size.height / 2 - point.y * current.zoom });
    }
  }, [selectedId]);

  const zoomAt = useCallback((factor: number, x: number, y: number) => {
    autoFit.current = false;
    setCamera((current) => {
      const zoom = clampZoom(current.zoom * factor);
      return { zoom, x: x - (x - current.x) * zoom / current.zoom, y: y - (y - current.y) * zoom / current.zoom };
    });
  }, []);

  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = el.getBoundingClientRect();
      zoomAt(Math.exp(-event.deltaY * 0.0015), event.clientX - rect.left, event.clientY - rect.top);
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [zoomAt]);

  const worldPoint = (event: React.PointerEvent) => {
    const rect = viewport.current!.getBoundingClientRect();
    return { x: (event.clientX - rect.left - camera.x) / camera.zoom, y: (event.clientY - rect.top - camera.y) / camera.zoom };
  };
  const begin = (event: React.PointerEvent, node?: WorldBookGraphNode) => {
    if (event.button !== 0 && event.button !== 1) return;
    event.preventDefault(); event.stopPropagation();
    viewport.current?.focus({ preventScroll: true });
    if (node && linkSources.length) { onSelectNode(node, false); return; }
    // 空白处 Shift / Alt 拖拽 = 框选；普通拖拽仍然是平移。
    const marqueeMode = !node && (event.shiftKey || event.altKey);
    const origin = node ? positions[node.id] : marqueeMode ? worldPoint(event) : { x: camera.x, y: camera.y };
    // 跟随集合在按下时定一次：拖动过程中图与筛选不变，不需要每帧重算。
    // 关闭「拖动跟随」时集合退化为只含被拖动节点自身 —— 后面的位移、提交、渲染
    // 全都走同一条路径，不需要为「单节点拖动」再写一套分支。
    const followIds = node ? (followEnabled ? followSetFor(graph, node.id) : [node.id]) : undefined;
    gesture.current = { kind: node ? "node" : marqueeMode ? "marquee" : "pan", pointerId: event.pointerId,
      startX: event.clientX, startY: event.clientY, origin, nodeId: node?.id, follow: followIds, moved: false,
    };
    if (node) { setFollow(followIds!); setDragOffset({ x: 0, y: 0 }); }
    if (marqueeMode) { marqueeRef.current = { left: origin.x, top: origin.y, right: origin.x, bottom: origin.y }; setMarquee(marqueeRef.current); }
    viewport.current?.setPointerCapture(event.pointerId);
  };
  const move = (event: React.PointerEvent) => {
    if (linkSources.length) setCursor(worldPoint(event));
    const current = gesture.current;
    if (!current || current.pointerId !== event.pointerId) return;
    const dx = event.clientX - current.startX, dy = event.clientY - current.startY;
    if (!current.moved && Math.hypot(dx, dy) < 4) return;
    autoFit.current = false;
    current.moved = true; setDragging(true);
    if (current.kind === "pan") setCamera((cam) => ({ ...cam, x: current.origin.x + dx, y: current.origin.y + dy }));
    else if (current.kind === "marquee") {
      const point = worldPoint(event);
      marqueeRef.current = { left: current.origin.x, top: current.origin.y, right: point.x, bottom: point.y };
      setMarquee(marqueeRef.current);
    } else {
      // 拖动节点：位移同时存进 ref（抬手时提交用）与 state（渲染用），
      // 被拖动节点与跟随节点都只是「基准位置 + 同一个位移」，相对位置恒定。
      const offset = { x: dx / camera.zoom, y: dy / camera.zoom };
      current.offset = offset;
      setDragOffset(offset);
    }
  };
  const end = (event: React.PointerEvent, cancelled = false) => {
    const current = gesture.current;
    if (!current || current.pointerId !== event.pointerId) return;
    gesture.current = null; setDragging(false);
    if (viewport.current?.hasPointerCapture(event.pointerId)) viewport.current.releasePointerCapture(event.pointerId);
    // 位置只在这里写一次：被拖动节点与直接相连的节点按同一位移一起落表。
    // 取消（pointercancel）时放弃本次拖动，位置保持拖动前的值。
    if (current.kind === "node" && current.moved && !cancelled && current.offset && current.follow) {
      const delta = current.offset, ids = current.follow;
      setPositions((next) => {
        const moved = { ...next };
        for (const id of ids) if (moved[id]) moved[id] = { x: moved[id].x + delta.x, y: moved[id].y + delta.y };
        return moved;
      });
    }
    setFollow(null); setDragOffset(null);
    if (!cancelled && !current.moved) {
      if (current.nodeId) {
        const node = nodeMap.get(current.nodeId);
        if (node) onSelectNode(node, event.ctrlKey || event.metaKey || event.shiftKey);
      } else if (current.kind !== "marquee") { onClear(); onCancelLink(); }
    }
    if (current.kind === "marquee") {
      const box = marqueeRef.current;
      marqueeRef.current = null; setMarquee(null);
      // 位移过小的一下 Shift 点击不当作框选，避免无意义的状态写入。
      if (!cancelled && box && (Math.abs(box.right - box.left) > 2 || Math.abs(box.bottom - box.top) > 2)) {
        onPickMany(pickedInRect(graph.nodes, positions, box), true);
      }
    }
  };
  const centerSelected = () => {
    autoFit.current = false;
    const point = selectedId ? positions[selectedId] : null;
    if (point) setCamera((current) => ({ ...current, x: size.width / 2 - point.x * current.zoom, y: size.height / 2 - point.y * current.zoom }));
  };
  /** 切换「拖动跟随」并持久化。拖动过程中不可切换：手势按下时已定好跟随集合，中途改会让本次拖动语义不一致。 */
  const toggleFollow = () => {
    setFollowEnabled((current) => {
      const next = !current;
      writeFollowPref(next);
      return next;
    });
  };
  // Small graphs stay readable at fit-to-view zoom. Dense graphs reveal entry
  // labels on focus instead of rendering hundreds of illegible tiny captions.
  const visualScale = Math.max(1, Math.min(1.7, 1 / camera.zoom));
  const visibleCount = graph.nodes.reduce((total, node) => total + (positions[node.id] ? 1 : 0), 0);
  const caption = treeLayout
    ? { title: "依赖树", detail: `${treeLayout.levels.length ? treeLayout.levels[0].depth + "–" + treeLayout.levels[treeLayout.levels.length - 1].depth : 0} 层 · 可见 ${treeLayout.visible} 节点` }
    : view === "taxonomy"
      ? { title: "分类结构", detail: `${graph.nodes.filter((node) => node.kind === "category").length} 分类 · ${graph.entryCount} 条目` }
      : { title: "关系网络", detail: `${graph.nodes.filter((node) => node.kind === "category").length} 分类 · ${graph.entryCount} 条目` };

  return <div ref={viewport} className={"wbg-canvas" + (dragging ? " is-dragging" : "") + (linkSources.length ? " is-linking" : "")
    + (coloring === "role" && dependencyView ? " is-role-coloring" : "") + (treeLayout ? " is-tree" : "")}
    role="region" aria-label={view === "taxonomy" ? "世界书分类图画布" : view === "tree" ? "世界书依赖树画布" : "世界书依赖图画布"} tabIndex={0}
    style={{ backgroundPosition: `${camera.x}px ${camera.y}px`, backgroundSize: `${28 * camera.zoom}px ${28 * camera.zoom}px` }}
    onPointerDown={(event) => {
      if (!(event.target as Element).closest("[data-wbg-control], [data-wbg-node], [data-wbg-edge]")) begin(event);
    }} onPointerMove={move} onPointerUp={(event) => end(event)} onPointerCancel={(event) => end(event, true)}
    onDragOver={(event) => event.preventDefault()} onDrop={onDropEntry}
    onKeyDown={(event) => {
      if (event.key === "Escape") { onCancelLink(); onClear(); }
      if (event.target !== event.currentTarget) return;
      autoFit.current = false;
      if (["+", "=", "-", "0", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) event.preventDefault();
      if (event.key === "+" || event.key === "=") zoomAt(1.2, size.width / 2, size.height / 2);
      if (event.key === "-") zoomAt(1 / 1.2, size.width / 2, size.height / 2);
      if (event.key === "0") fitPositions(positions);
      const arrows: Record<string, GraphPoint> = { ArrowLeft: { x: 45, y: 0 }, ArrowRight: { x: -45, y: 0 }, ArrowUp: { x: 0, y: 45 }, ArrowDown: { x: 0, y: -45 } };
      if (arrows[event.key]) setCamera((current) => ({ ...current, x: current.x + arrows[event.key].x, y: current.y + arrows[event.key].y }));
    }}>
    <svg className="wbg-svg" role="group" aria-label={view === "taxonomy" ? "世界书分类关系图" : view === "tree" ? "世界书依赖分层树" : "世界书有向依赖图"}>
      <defs>
        <marker id={id + "-arrow"} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 1 1 L 9 5 L 1 9 Z" className="wbg-arrow" /></marker>
        <marker id={id + "-active"} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 1 1 L 9 5 L 1 9 Z" className="wbg-arrow-active" /></marker>
      </defs>
      <g transform={`translate(${camera.x},${camera.y}) scale(${camera.zoom})`}>
        {treeLayout && <g className="wbg-tree-guides" aria-hidden="true">
          {treeLayout.levels.map((level) => <line key={level.depth} x1={bounds.left - 70} x2={bounds.left + bounds.width + 70}
            y1={level.y - 74} y2={level.y - 74} vectorEffect="non-scaling-stroke" />)}
          {treeLayout.bands.map((band) => <line key={band.kind} x1={bounds.left - 70} x2={bounds.left + bounds.width + 70}
            y1={band.y - 62} y2={band.y - 62} vectorEffect="non-scaling-stroke" />)}
          {treeLayout.levels.map((level) => <text key={"label-" + level.depth} className="wbg-tree-level-label" x={bounds.left - 54}
            y={level.y - 80} style={{ fontSize: 11 / Math.max(0.12, camera.zoom) }}>{level.label} · {level.count} 节点</text>)}
          {treeLayout.bands.map((band) => <text key={"band-" + band.kind} className={"wbg-tree-level-label is-" + band.kind} x={bounds.left - 54}
            y={band.y - 68} style={{ fontSize: 11 / Math.max(0.12, camera.zoom) }}>{band.label} · {band.count} 条</text>)}
        </g>}
        {graph.edges.map((edge) => {
          const a = at(edge.from), b = at(edge.to);
          if (!a || !b) return null;
          const from = nodeMap.get(edge.from)!, to = nodeMap.get(edge.to)!;
          const dependency = edge.kind === "dependency";
          const active = edge.id === selectedEdgeId || edge.from === activeId || edge.to === activeId;
          const extra = !!treeLayout && dependency && !edge.skeleton;
          const curved = dependency && (treeLayout ? extra : edgeDirections.has(JSON.stringify([edge.to, edge.from])));
          const geometry = worldBookEdgeGeometry(a, b, from.radius * visualScale, to.radius * visualScale, curved);
          const status = dependency ? edge.status : undefined;
          const arrow = dependency && status !== "capped" && status !== "idle";
          return <g key={edge.id} data-wbg-edge={edge.id}
            className={`wbg-edge wbg-edge-${edge.kind}${active ? " is-active" : ""}${related && !active ? " is-muted" : ""}`
              + (edge.skeleton ? " is-skeleton" : "") + (extra ? " is-extra" : "")
              + (status === "capped" ? " is-capped" : "") + (status === "idle" ? " is-idle" : "") + (edge.loop ? " is-loop" : "")}
            role={dependency ? "button" : undefined} tabIndex={dependency ? 0 : undefined}
            aria-label={dependency ? `${from.label} 依赖 ${to.label}${status && status !== "active" ? "（" + (status === "capped" ? "深度用尽未展开" : "上游未进入候选范围") + "）" : ""}` : undefined}
            onClick={dependency ? (event) => { event.stopPropagation(); onCancelLink(); onSelectEdge(edge.id); } : undefined}
            onKeyDown={dependency ? (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.stopPropagation(); onSelectEdge(edge.id); } } : undefined}>
            <title>{from.label + (dependency ? " → 依赖 → " : " / ") + to.label + (dependency && status ? " · " + (status === "active" ? "参与展开" : status === "capped" ? "深度用尽，未展开" : "上游未进入候选范围") : "") + (edge.loop ? " · 位于依赖环" : "")}</title>
            {dependency && <path className="wbg-edge-hit" d={geometry.path} />}
            <path className="wbg-edge-line" d={geometry.path} markerEnd={arrow ? `url(#${id}${active ? "-active" : "-arrow"})` : undefined} />
            {dependency && !treeLayout && (active || graph.entryCount < 24) && <text className="wbg-edge-label" x={geometry.label.x} y={geometry.label.y - 9 / camera.zoom} style={{ fontSize: 10 / Math.min(1, camera.zoom) }}>依赖</text>}
          </g>;
        })}
        {!!linkSources.length && cursor && linkSources.slice(0, PENDING_EDGE_LIMIT).map((uid) => {
          const point = at(entryNodeId(uid));
          return point ? <path key={uid} className="wbg-pending-edge" d={worldBookEdgeGeometry(point, cursor, 25 * visualScale, 0).path} markerEnd={`url(#${id}-active)`} /> : null;
        })}
        {marquee && <rect className="wbg-marquee" x={Math.min(marquee.left, marquee.right)} y={Math.min(marquee.top, marquee.bottom)}
          width={Math.abs(marquee.right - marquee.left)} height={Math.abs(marquee.bottom - marquee.top)} vectorEffect="non-scaling-stroke" />}
        {graph.nodes.map((node) => {
          const point = at(node.id);
          if (!point) return null;
          const selected = selectedId === node.id;
          // 跟随提示只给「被带动」的节点，被拖动的那个由 is-selected / hover 表达。
          const following = !!dragNodeId && node.id !== dragNodeId && !!followSet?.has(node.id);
          const linking = node.kind === "entry" && linkSources.includes(node.refId);
          const picked = node.kind === "entry" && pickedSet.has(node.refId);
          const chars = Array.from(node.label);
          const shortLabel = chars.length > 13 ? chars.slice(0, 12).join("") + "…" : node.label;
          const scale = visualScale;
          const inFocus = !activeId || related?.has(node.id);
          const showLabel = selected || hoverId === node.id ||
            (inFocus && (node.kind === "category" || graph.entryCount <= 24 || camera.zoom >= 0.5));
          const role = node.role;
          const showBadge = !!role && (showLabel || role === "source" || !!node.fixed || !!node.inCycle);
          // 只有「确实画得出来」的下游才给折叠手柄：被层级上限或角色筛选挡住的分支
          // 交给工具栏的展开层级处理，避免手柄点了没反应。
          const childUids = treeLayout && graph.tree ? graph.tree.byUid.get(node.refId)?.childUids || [] : [];
          const drawnChildren = treeLayout ? childUids.filter((uid) => treeLayout.positions[uid]).length : 0;
          const folded = !!treeLayout && !!tree?.collapsed.has(node.refId);
          const showHandle = !!treeLayout && (drawnChildren > 0 || (folded && childUids.length > 0));
          // 正好卡在层级上限的节点：下游不是被折叠，而是被「展开层级」截断的。
          const atLimit = !!treeLayout && !!tree && node.treeDepth !== undefined && node.treeDepth >= tree.depthLimit && !!node.childCount;
          const caption = [node.disabled ? "已停用" : "", node.treeDepth !== undefined ? `第 ${node.treeDepth} 层 · 余 ${node.remaining}` : "",
            atLimit ? `下游 ${node.childCount} 未展开` : ""].filter(Boolean).join(" · ");
          const roleText = role ? ROLE_LABELS[role] : KINDS[node.scopeType];
          return <g key={node.id} transform={`translate(${point.x},${point.y})`} data-wbg-node={node.id} data-wbg-kind={node.scopeType}
            data-wbg-role={role} data-wbg-depth={node.treeDepth}
            className={`wbg-node wbg-node-${node.kind}${selected ? " is-selected" : ""}${linking ? " is-source" : ""}${picked ? " is-picked" : ""}${following ? " is-following" : ""}${related && !related.has(node.id) && !linkSources.length ? " is-muted" : ""}${node.disabled ? " is-disabled" : ""}${node.inCycle ? " is-cycle" : ""}${node.unreached ? " is-unreached" : ""}`}
            tabIndex={0} role="button" aria-label={`${node.kind === "category" ? "选择分类" : "选择节点"} ${node.label}${role ? "（" + roleText + "）" : ""}${picked ? "，已批量选中" : ""}`} aria-pressed={selected || picked}
            onPointerDown={(event) => begin(event, node)} onPointerEnter={() => !dragging && setHoverId(node.id)} onPointerLeave={() => setHoverId(null)}
            onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.stopPropagation(); onSelectNode(node, event.ctrlKey || event.metaKey || event.shiftKey); } }}>
            <title>{node.label + " · " + (node.kind === "category" ? "分类" : roleText)
              + (node.fixed ? " · 固定导入" : "") + (node.sourceDepth !== undefined ? ` · 导入源 / 预算深度 ${node.sourceDepth}` : "")
              + (node.treeDepth !== undefined ? ` · 第 ${node.treeDepth} 层 · 剩余 ${node.remaining}` : "")
              + (node.inCycle ? " · 位于依赖环" : "") + (node.unreached ? " · 未被导入源展开" : "") + (node.disabled ? " · 已停用" : "")}</title>
            <g transform={`scale(${scale})`}>
            <circle className="wbg-node-halo" r={node.radius + 9} />
            {node.fixed && <circle className="wbg-fixed-ring" r={node.radius + 5} />}
            {node.inCycle && <circle className="wbg-cycle-ring" r={node.radius + 7} />}
            <circle className="wbg-node-disc" r={node.radius} />
            {node.kind === "category" ? <>
              <path className="wbg-folder-glyph" d="M-10-9h8l3 4h10v12h-22V-9Z" />
              <text className="wbg-category-count" y="23">{node.count} 条</text>
            </> : showLabel && <text className="wbg-node-monogram" y="5">{chars.slice(0, 2).join("")}</text>}
            {showBadge && role && <g className="wbg-role-badge" data-wbg-role={role} transform={`translate(${-node.radius + 1},${-node.radius + 1})`}><circle r="9" /><text y="3.4">{ROLE_GLYPHS[role]}</text></g>}
            {node.sourceDepth !== undefined && <g className="wbg-source-badge" transform={`translate(${node.radius - 2},${-node.radius + 2})`}><circle r="10" /><text y="3.5">{node.sourceDepth}</text></g>}
            {showLabel && <text className="wbg-node-label" y={node.radius + 23} style={{ fontSize: (node.kind === "category" ? 13 : 12) / Math.min(1, scale * camera.zoom) }}>{shortLabel}</text>}
            {showLabel && caption && <text className="wbg-node-caption" y={node.radius + 39}>{caption}</text>}
            {picked && <g className="wbg-pick-badge" transform={`translate(${node.radius - 3},${node.radius - 3})`}><circle r="8.5" /><path d="M-4 0.5l2.6 2.6 5-5.4" /></g>}
            {showHandle && <g className={"wbg-collapse-handle" + (folded ? " is-collapsed" : "")} role="button" tabIndex={0}
              aria-label={(folded ? "展开 " : "折叠 ") + node.label + " 的下游 " + childUids.length + " 个节点"}
              transform={`translate(${node.radius + 15},0)`}
              onPointerDown={(event) => event.stopPropagation()} onClick={(event) => { event.stopPropagation(); onToggleCollapse(node.refId); }}
              onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.stopPropagation(); onToggleCollapse(node.refId); } }}>
              <circle r="9" /><path d={"M-3.5 0H3.5" + (folded ? "M0-3.5V3.5" : "")} />
              <text y="21">{childUids.length}{folded ? " 未展开" : ""}</text>
            </g>}
            {dependencyView && node.kind === "entry" && selected && !busy && !linkSources.length &&
              <g className="wbg-link-handle" role="button" tabIndex={0} aria-label={`从 ${node.label} 添加依赖`} transform={`translate(${node.radius + 17},${showHandle ? 26 : 0})`}
                onPointerDown={(event) => event.stopPropagation()} onClick={(event) => { event.stopPropagation(); onLinkStart(node.refId); }}
                onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.stopPropagation(); onLinkStart(node.refId); } }}>
                <circle r="10" /><path d="M-4 0H4M0-4V4" />
              </g>}
            </g>
          </g>;
        })}
      </g>
    </svg>

    <div className="wbg-canvas-caption" data-wbg-control>
      <span>{caption.title}</span>
      <span>{caption.detail}</span>
      {graph.hiddenCount > 0 && <span className="wbg-warning">另有 {graph.hiddenCount} 条未上图，请搜索或筛选分类</span>}
      {treeLayout && treeLayout.hidden > 0 && <span className="wbg-warning">层级上限或折叠隐藏 {treeLayout.hidden} 个节点</span>}
      {treeLayout && treeLayout.hasDeeper && <span className="wbg-warning">还有更深的层级未展开</span>}
    </div>
    {!!linkSources.length && <div className="wbg-link-banner" role="status" data-wbg-control><WorldBookGraphIcon name="link" />
      {linkSources.length > 1 ? ` 点击目标条目，为 ${linkSources.length} 个条目建立依赖 ` : " 点击目标条目建立依赖 "}
      <button onClick={onCancelLink}>取消 · Esc</button></div>}
    {!!pickedIds.length && <div className="wbg-pick-hint" role="status" data-wbg-control>已批量选中 {pickedIds.length} 个条目 · Ctrl/Shift 点击可增减</div>}
    {!graph.nodes.length && <div className="wbg-empty"><WorldBookGraphIcon name="graph" size={42} /><strong>暂无匹配的节点</strong><p>试试清空搜索或切换分类；也可以从节点目录中选择条目。</p></div>}
    {view === "tree" && !!graph.nodes.length && !treeLayout?.visible && !treeLayout?.bands.length && <div className="wbg-empty">
      <WorldBookGraphIcon name="graph" size={42} /><strong>还没有可展开的导入源</strong>
      <p>在节点属性中把条目设为「导入源」并设置遍历深度，依赖树就会从该节点按层展开。</p>
    </div>}

    <div className="wbg-canvas-footer" data-wbg-control>
      <div className="wbg-legend" aria-label="节点图例">
        {coloring === "role" && dependencyView
          ? DEPENDENCY_ROLES.map((role) => <span key={role} title={ROLE_HINTS[role]}><i data-wbg-role={role} />{ROLE_LABELS[role]}</span>)
          : Object.entries(KINDS).map(([kind, label]) => <span key={kind}><i data-wbg-kind={kind} />{label}</span>)}
        {dependencyView && coloring !== "role" && <><span><i className="wbg-legend-fixed" />固定导入</span><span><i className="wbg-legend-source" />导入源</span></>}
        {dependencyView && !!graph.stats?.cycleCount && <span><i className="wbg-legend-cycle" />依赖环</span>}
        {treeLayout && <span><i className="wbg-legend-edge is-active" />参与展开</span>}
        {treeLayout && !!graph.stats?.cappedEdges && <span><i className="wbg-legend-edge is-capped" />超深度</span>}
        {treeLayout && !!graph.stats?.idleEdges && <span><i className="wbg-legend-edge is-idle" />未启用</span>}
      </div>
      <div className="wbg-canvas-controls">
        <button aria-label="缩小图谱" title="缩小（-）" onClick={() => zoomAt(1 / 1.2, size.width / 2, size.height / 2)}>−</button>
        <button className="wbg-zoom-value" title="恢复 100%" onClick={() => zoomAt(1 / camera.zoom, size.width / 2, size.height / 2)}>{Math.round(camera.zoom * 100)}%</button>
        <button aria-label="放大图谱" title="放大（+）" onClick={() => zoomAt(1.2, size.width / 2, size.height / 2)}>＋</button>
        <span className="wbg-control-divider" />
        <button aria-label="适应全部节点" title="适应全部节点（0）" onClick={() => fitPositions(positions)}><WorldBookGraphIcon name="fit" /></button>
        <button aria-label="定位选中节点" title="定位选中节点" disabled={!selectedId} onClick={centerSelected}>◎</button>
        <button aria-label="全选可见条目" title="全选可见条目（并入当前批量选择）" disabled={!visibleEntryUids.length}
          onClick={() => onPickMany(visibleEntryUids, true)}>▣</button>
        <button aria-label={treeLayout ? "重置依赖树布局" : "重新布局图谱"} title={treeLayout ? "重置布局（清除手动拖动，不改变策略）" : "重新布局（仅调整视图，不改变分类与依赖）"} onClick={() => setLayoutVersion((value) => value + 1)}><WorldBookGraphIcon name="layout" /></button>
        <span className="wbg-control-divider" />
        {/* 拖动跟随开关：按下的语义是「设置」而不是一次性动作，所以用 aria-pressed + 常驻高亮表达状态。 */}
        <button aria-label="拖动跟随" aria-pressed={followEnabled} data-wbg-follow={followEnabled ? "on" : "off"}
          className={followEnabled ? "is-active" : undefined}
          title={followEnabled
            ? "拖动跟随：开 —— 拖动节点时，与它直接相连的节点一起位移（点击关闭）"
            : "拖动跟随：关 —— 拖动节点只移动它自己（点击开启）"}
          onClick={toggleFollow}><WorldBookGraphIcon name="link" /></button>
      </div>
    </div>
    <span className="wbg-gesture-hint" data-wbg-control>{treeLayout ? "点击 ⊕ 折叠分支 · " : ""}拖动节点{followEnabled ? "（直接相连的节点同步跟随）" : "（仅移动该节点）"} · Shift 拖拽框选 · Ctrl/Shift 点击多选 · 空白平移 · 滚轮缩放</span>
    {visibleCount > 4 && <svg className="wbg-minimap" aria-label="图谱缩略图" viewBox={`${bounds.left} ${bounds.top} ${bounds.width} ${bounds.height}`} data-wbg-control>
      {graph.edges.map((edge) => positions[edge.from] && positions[edge.to] ? <line key={edge.id} x1={positions[edge.from].x} y1={positions[edge.from].y} x2={positions[edge.to].x} y2={positions[edge.to].y} /> : null)}
      {graph.nodes.map((node) => positions[node.id] ? <circle key={node.id} cx={positions[node.id].x} cy={positions[node.id].y} r={node.kind === "category" ? 12 : 6} data-wbg-kind={node.scopeType} data-wbg-role={node.role} /> : null)}
      <rect x={-camera.x / camera.zoom} y={-camera.y / camera.zoom} width={size.width / camera.zoom} height={size.height / camera.zoom} />
    </svg>}
  </div>;
}
