import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  entryNodeId, layoutWorldBookGraph, spreadWorldBookGraph, worldBookEdgeGeometry,
  type GraphPoint, type WorldBookGraphData, type WorldBookGraphNode,
} from "../utils/worldbookGraph";
import WorldBookGraphIcon from "./WorldBookGraphIcon";

type Camera = { x: number; y: number; zoom: number };
type Gesture = {
  kind: "pan" | "node";
  pointerId: number;
  startX: number;
  startY: number;
  origin: GraphPoint;
  nodeId?: string;
  moved: boolean;
};
const KINDS = { worldview: "世界观", character: "角色", other: "其他" };
const clampZoom = (value: number) => Math.max(0.15, Math.min(2.5, value));

function boundsFor(graph: WorldBookGraphData, positions: Record<string, GraphPoint>) {
  const points = graph.nodes.flatMap((node) => positions[node.id] ? [{ ...positions[node.id], radius: node.radius }] : []);
  if (!points.length) return { left: -200, top: -150, width: 400, height: 300 };
  const left = Math.min(...points.map((p) => p.x - p.radius - 55));
  const top = Math.min(...points.map((p) => p.y - p.radius - 25));
  return { left, top,
    width: Math.max(...points.map((p) => p.x + p.radius + 55)) - left,
    height: Math.max(...points.map((p) => p.y + p.radius + 50)) - top,
  };
}

export default function WorldBookGraphCanvas({ graph, view, selectedId, selectedEdgeId, linkFromUid, busy,
  onSelectNode, onSelectEdge, onLinkStart, onCancelLink, onClear, onDropEntry,
}: {
  graph: WorldBookGraphData;
  view: "taxonomy" | "dependencies";
  selectedId: string | null;
  selectedEdgeId: string | null;
  linkFromUid: string | null;
  busy: boolean;
  onSelectNode: (node: WorldBookGraphNode) => void;
  onSelectEdge: (id: string) => void;
  onLinkStart: (uid: string) => void;
  onCancelLink: () => void;
  onClear: () => void;
  onDropEntry: (event: React.DragEvent) => void;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const id = useId().replace(/:/g, "");
  const [camera, setCamera] = useState<Camera>({ x: 0, y: 0, zoom: 1 });
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [cursor, setCursor] = useState<GraphPoint | null>(null);
  const [dragging, setDragging] = useState(false);
  const [layoutVersion, setLayoutVersion] = useState(0);
  // Flags and names do not invalidate node positions while the user edits a policy.
  const layoutKey = JSON.stringify([graph.nodes.map((node) => node.id), graph.edges.map((edge) => [edge.from, edge.to, edge.kind])]);
  const initial = useMemo(() => layoutWorldBookGraph(graph), [layoutKey, layoutVersion]);
  const [positions, setPositions] = useState(initial);
  const fittedKey = useRef("");
  const fittedSize = useRef("");
  const autoFit = useRef(true);
  const nodeMap = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph.nodes]);
  const cameraRef = useRef(camera);
  cameraRef.current = camera;
  const bounds = useMemo(() => boundsFor(graph, positions), [graph, positions]);
  const activeId = linkFromUid ? entryNodeId(linkFromUid) : hoverId || selectedId;
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
    const key = layoutKey + ":" + layoutVersion;
    const sizeKey = size.width + ":" + size.height;
    const newLayout = fittedKey.current !== key;
    if (!newLayout && (!autoFit.current || fittedSize.current === sizeKey)) return;
    if (newLayout) autoFit.current = true;
    fittedKey.current = key;
    fittedSize.current = sizeKey;
    const arranged = spreadWorldBookGraph(initial, Math.max(100, size.width - 110) / Math.max(100, size.height - 150));
    setPositions(arranged);
    fitPositions(arranged);
  }, [initial, layoutKey, layoutVersion, size, fitPositions]);

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
    if (node && linkFromUid) { onSelectNode(node); return; }
    gesture.current = { kind: node ? "node" : "pan", pointerId: event.pointerId,
      startX: event.clientX, startY: event.clientY, origin: node ? positions[node.id] : { x: camera.x, y: camera.y },
      nodeId: node?.id, moved: false,
    };
    viewport.current?.setPointerCapture(event.pointerId);
  };
  const move = (event: React.PointerEvent) => {
    if (linkFromUid) setCursor(worldPoint(event));
    const current = gesture.current;
    if (!current || current.pointerId !== event.pointerId) return;
    const dx = event.clientX - current.startX, dy = event.clientY - current.startY;
    if (!current.moved && Math.hypot(dx, dy) < 4) return;
    autoFit.current = false;
    current.moved = true; setDragging(true);
    if (current.kind === "pan") setCamera((cam) => ({ ...cam, x: current.origin.x + dx, y: current.origin.y + dy }));
    else setPositions((next) => ({ ...next, [current.nodeId!]: {
      x: current.origin.x + dx / camera.zoom, y: current.origin.y + dy / camera.zoom,
    } }));
  };
  const end = (event: React.PointerEvent, cancelled = false) => {
    const current = gesture.current;
    if (!current || current.pointerId !== event.pointerId) return;
    gesture.current = null; setDragging(false);
    if (viewport.current?.hasPointerCapture(event.pointerId)) viewport.current.releasePointerCapture(event.pointerId);
    if (!cancelled && !current.moved) {
      if (current.nodeId) { const node = nodeMap.get(current.nodeId); if (node) onSelectNode(node); }
      else { onClear(); onCancelLink(); }
    }
  };
  const centerSelected = () => {
    autoFit.current = false;
    const point = selectedId ? positions[selectedId] : null;
    if (point) setCamera((current) => ({ ...current, x: size.width / 2 - point.x * current.zoom, y: size.height / 2 - point.y * current.zoom }));
  };
  const linkSource = linkFromUid ? positions[entryNodeId(linkFromUid)] : null;
  // Small graphs stay readable at fit-to-view zoom. Dense graphs reveal entry
  // labels on focus instead of rendering hundreds of illegible tiny captions.
  const visualScale = Math.max(1, Math.min(1.7, 1 / camera.zoom));

  return <div ref={viewport} className={"wbg-canvas" + (dragging ? " is-dragging" : "") + (linkFromUid ? " is-linking" : "")}
    role="region" aria-label={view === "taxonomy" ? "世界书分类图画布" : "世界书依赖图画布"} tabIndex={0}
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
    <svg className="wbg-svg" role="group" aria-label={view === "taxonomy" ? "世界书分类关系图" : "世界书有向依赖图"}>
      <defs>
        <marker id={id + "-arrow"} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 1 1 L 9 5 L 1 9 Z" className="wbg-arrow" /></marker>
        <marker id={id + "-active"} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 1 1 L 9 5 L 1 9 Z" className="wbg-arrow-active" /></marker>
      </defs>
      <g transform={`translate(${camera.x},${camera.y}) scale(${camera.zoom})`}>
        {graph.edges.map((edge) => {
          const a = positions[edge.from], b = positions[edge.to];
          if (!a || !b) return null;
          const from = nodeMap.get(edge.from)!, to = nodeMap.get(edge.to)!;
          const dependency = edge.kind === "dependency";
          const active = edge.id === selectedEdgeId || edge.from === activeId || edge.to === activeId;
          const geometry = worldBookEdgeGeometry(a, b, from.radius * visualScale, to.radius * visualScale, dependency && edgeDirections.has(JSON.stringify([edge.to, edge.from])));
          return <g key={edge.id} data-wbg-edge={edge.id}
            className={`wbg-edge wbg-edge-${edge.kind}${active ? " is-active" : ""}${related && !active ? " is-muted" : ""}`}
            role={dependency ? "button" : undefined} tabIndex={dependency ? 0 : undefined}
            aria-label={dependency ? `${from.label} 依赖 ${to.label}` : undefined}
            onClick={dependency ? (event) => { event.stopPropagation(); onCancelLink(); onSelectEdge(edge.id); } : undefined}
            onKeyDown={dependency ? (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.stopPropagation(); onSelectEdge(edge.id); } } : undefined}>
            <title>{from.label + (dependency ? " → 依赖 → " : " / ") + to.label}</title>
            {dependency && <path className="wbg-edge-hit" d={geometry.path} />}
            <path className="wbg-edge-line" d={geometry.path} markerEnd={dependency ? `url(#${id}${active ? "-active" : "-arrow"})` : undefined} />
            {dependency && (active || graph.entryCount < 24) && <text className="wbg-edge-label" x={geometry.label.x} y={geometry.label.y - 9 / camera.zoom} style={{ fontSize: 10 / Math.min(1, camera.zoom) }}>依赖</text>}
          </g>;
        })}
        {linkSource && cursor && <path className="wbg-pending-edge" d={worldBookEdgeGeometry(linkSource, cursor, 25 * visualScale, 0).path} markerEnd={`url(#${id}-active)`} />}
        {graph.nodes.map((node) => {
          const point = positions[node.id];
          if (!point) return null;
          const selected = selectedId === node.id;
          const linking = linkFromUid === node.refId && node.kind === "entry";
          const chars = Array.from(node.label);
          const shortLabel = chars.length > 13 ? chars.slice(0, 12).join("") + "…" : node.label;
          const scale = visualScale;
          const inFocus = !activeId || related?.has(node.id);
          const showLabel = selected || hoverId === node.id ||
            (inFocus && (node.kind === "category" || graph.entryCount <= 24 || camera.zoom >= 0.5));
          return <g key={node.id} transform={`translate(${point.x},${point.y})`} data-wbg-node={node.id} data-wbg-kind={node.scopeType}
            className={`wbg-node wbg-node-${node.kind}${selected ? " is-selected" : ""}${linking ? " is-source" : ""}${related && !related.has(node.id) && !linkFromUid ? " is-muted" : ""}${node.disabled ? " is-disabled" : ""}`}
            tabIndex={0} role="button" aria-label={`${node.kind === "category" ? "选择分类" : "选择节点"} ${node.label}`} aria-pressed={selected}
            onPointerDown={(event) => begin(event, node)} onPointerEnter={() => !dragging && setHoverId(node.id)} onPointerLeave={() => setHoverId(null)}
            onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.stopPropagation(); onSelectNode(node); } }}>
            <title>{node.label + " · " + (node.kind === "category" ? "分类" : KINDS[node.scopeType]) + (node.fixed ? " · 固定导入" : "") + (node.sourceDepth !== undefined ? ` · 导入源 / 深度 ${node.sourceDepth}` : "") + (node.disabled ? " · 已停用" : "")}</title>
            <g transform={`scale(${scale})`}>
            <circle className="wbg-node-halo" r={node.radius + 9} />
            {node.fixed && <circle className="wbg-fixed-ring" r={node.radius + 5} />}
            <circle className="wbg-node-disc" r={node.radius} />
            {node.kind === "category" ? <>
              <path className="wbg-folder-glyph" d="M-10-9h8l3 4h10v12h-22V-9Z" />
              <text className="wbg-category-count" y="23">{node.count} 条</text>
            </> : showLabel && <text className="wbg-node-monogram" y="5">{chars.slice(0, 2).join("")}</text>}
            {node.sourceDepth !== undefined && <g className="wbg-source-badge" transform={`translate(${node.radius - 2},${-node.radius + 2})`}><circle r="10" /><text y="3.5">{node.sourceDepth}</text></g>}
            {showLabel && <text className="wbg-node-label" y={node.radius + 23} style={{ fontSize: (node.kind === "category" ? 13 : 12) / Math.min(1, scale * camera.zoom) }}>{shortLabel}</text>}
            {node.disabled && showLabel && <text className="wbg-node-caption" y={node.radius + 39}>已停用</text>}
            {view === "dependencies" && node.kind === "entry" && selected && !busy && !linkFromUid &&
              <g className="wbg-link-handle" role="button" tabIndex={0} aria-label={`从 ${node.label} 添加依赖`} transform={`translate(${node.radius + 17},0)`}
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
      <span>{view === "taxonomy" ? "分类结构" : "关系网络"}</span>
      <span>{graph.nodes.filter((node) => node.kind === "category").length} 分类 · {graph.entryCount} 条目</span>
      {graph.hiddenCount > 0 && <span className="wbg-warning">另有 {graph.hiddenCount} 条未上图，请搜索或筛选分类</span>}
    </div>
    {linkFromUid && <div className="wbg-link-banner" role="status" data-wbg-control><WorldBookGraphIcon name="link" /> 点击目标条目建立依赖 <button onClick={onCancelLink}>取消 · Esc</button></div>}
    {!graph.nodes.length && <div className="wbg-empty"><WorldBookGraphIcon name="graph" size={42} /><strong>暂无匹配的节点</strong><p>试试清空搜索或切换分类；也可以从节点目录中选择条目。</p></div>}

    <div className="wbg-canvas-footer" data-wbg-control>
      <div className="wbg-legend" aria-label="节点图例">
        {Object.entries(KINDS).map(([kind, label]) => <span key={kind}><i data-wbg-kind={kind} />{label}</span>)}
        {view === "dependencies" && <><span><i className="wbg-legend-fixed" />固定导入</span><span><i className="wbg-legend-source" />导入源</span></>}
      </div>
      <div className="wbg-canvas-controls">
        <button aria-label="缩小图谱" title="缩小（-）" onClick={() => zoomAt(1 / 1.2, size.width / 2, size.height / 2)}>−</button>
        <button className="wbg-zoom-value" title="恢复 100%" onClick={() => zoomAt(1 / camera.zoom, size.width / 2, size.height / 2)}>{Math.round(camera.zoom * 100)}%</button>
        <button aria-label="放大图谱" title="放大（+）" onClick={() => zoomAt(1.2, size.width / 2, size.height / 2)}>＋</button>
        <span className="wbg-control-divider" />
        <button aria-label="适应全部节点" title="适应全部节点（0）" onClick={() => fitPositions(positions)}><WorldBookGraphIcon name="fit" /></button>
        <button aria-label="定位选中节点" title="定位选中节点" disabled={!selectedId} onClick={centerSelected}>◎</button>
        <button aria-label="重新布局图谱" title="重新布局（仅调整视图，不改变分类与依赖）" onClick={() => setLayoutVersion((value) => value + 1)}><WorldBookGraphIcon name="layout" /></button>
      </div>
    </div>
    <span className="wbg-gesture-hint" data-wbg-control>拖动节点 · 空白平移 · 滚轮缩放</span>
    {graph.nodes.length > 4 && <svg className="wbg-minimap" aria-label="图谱缩略图" viewBox={`${bounds.left} ${bounds.top} ${bounds.width} ${bounds.height}`} data-wbg-control>
      {graph.edges.map((edge) => positions[edge.from] && positions[edge.to] ? <line key={edge.id} x1={positions[edge.from].x} y1={positions[edge.from].y} x2={positions[edge.to].x} y2={positions[edge.to].y} /> : null)}
      {graph.nodes.map((node) => positions[node.id] ? <circle key={node.id} cx={positions[node.id].x} cy={positions[node.id].y} r={node.kind === "category" ? 12 : 6} data-wbg-kind={node.scopeType} /> : null)}
      <rect x={-camera.x / camera.zoom} y={-camera.y / camera.zoom} width={size.width / camera.zoom} height={size.height / camera.zoom} />
    </svg>}
  </div>;
}
