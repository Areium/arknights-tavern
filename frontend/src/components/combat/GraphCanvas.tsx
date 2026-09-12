/**
 * 剧情节点图画布 — 自由平移/缩放画布 + 节点/连线交互（替代旧横向滚动方案）。
 *
 * 视图模型：world 容器套 `transform: translate(x,y) scale(zoom)`（origin 0 0），
 * 平移缩放只改 transform，节点/连线以图内坐标绝对定位，浏览器 GPU 合成保证流畅。
 *
 * 平移：空白处按住左键拖拽 / 鼠标中键拖拽 / 空格+左键（可从节点上起步）/
 *       触控板双指水平滑动（wheel 且 deltaX 主导）。平移中光标 grab→grabbing。
 * 缩放：滚轮（deltaY 主导）与触控板捏合（ctrl+wheel）均以**指针位置为锚点**；
 *       工具栏 ±、1:1、适应视图（fit view）以视口中心为锚点。区间 25%–200%，
 *       越界给出提示。
 * 节点：拖拽移动（抬起才入撤销栈）、双击/菜单编辑、锚点拖出连线；
 *       连线可选中、端点拖拽重连、右键删除。一个节点允许分出多条路线。
 * 渲染：节点卡片 memo 化；节点尺寸经 ResizeObserver 实测（连线锚点用）；
 *       视口外节点/连线跳过渲染（视口裁剪）。
 */
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  PlotGraphDocDTO, PlotGraphNodeDTO, PlotGraphNodeType,
} from "../../types";
import {
  edgeGeometry, estimateNodeH, fitView, MAX_ZOOM, MIN_ZOOM, NODE_META,
  NODE_W, WHEEL_ZOOM_SENS, withEdge, withNode, ZOOM_STEP,
  clampZoom, rewireEdge, type NodeRect, type ViewState,
} from "./graphModel";

export interface GraphNodeDisplay {
  title: string;
  subtitle?: string;
  body?: string;
  missing?: boolean;
  progress?: "done" | "current" | "locked";
}

export interface GraphCanvasApi {
  centerWorld: () => { x: number; y: number };
  zoomBy: (factor: number) => void;
  resetZoom: () => void;
  fit: () => void;
}

export interface AvailableBeat { chapterIdx: number; beatId: string; label: string }
export interface AvailableCombat { nodeId: string; label: string }

interface Props {
  doc: PlotGraphDocDTO;
  view: ViewState;
  onViewChange: (v: ViewState) => void;
  selected: { kind: "node" | "edge"; id: string } | null;
  onSelect: (s: { kind: "node" | "edge"; id: string } | null) => void;
  /** 不可变提交（页面负责入撤销栈与脏标记） */
  onDocChange: (next: PlotGraphDocDTO) => void;
  displays: Map<string, GraphNodeDisplay>;
  onOpenNode: (node: PlotGraphNodeDTO) => void;
  onRequestDeleteNode: (id: string) => void;
  onCreateCombat: (wx: number, wy: number) => void;
  onAddBeat: (beat: AvailableBeat, wx: number, wy: number) => void;
  onAddCombatNode: (item: AvailableCombat, wx: number, wy: number) => void;
  availableBeats: AvailableBeat[];
  availableCombats: AvailableCombat[];
  onImportLayout: () => void;
  canvasApiRef?: { current: GraphCanvasApi | null };
}

type Menu =
  | { kind: "blank"; sx: number; sy: number; wx: number; wy: number }
  | { kind: "node"; sx: number; sy: number; nodeId: string }
  | { kind: "edge"; sx: number; sy: number; edgeId: string }
  | null;

type Interaction =
  | { kind: "pan"; lastX: number; lastY: number; moved: boolean }
  | { kind: "drag"; id: string; startWX: number; startWY: number; nodeX: number; nodeY: number; moved: boolean }
  | { kind: "link"; from: string; side: "top" | "right" | "bottom" | "left"; wx: number; wy: number }
  | { kind: "rewire"; edgeId: string; end: "from" | "to"; wx: number; wy: number }
  | null;

const SIDES: { side: "top" | "right" | "bottom" | "left"; fx: (r: NodeRect) => number; fy: (r: NodeRect) => number }[] = [
  { side: "right", fx: (r) => r.x + r.w, fy: (r) => r.y + r.h / 2 },
  { side: "bottom", fx: (r) => r.x + r.w / 2, fy: (r) => r.y + r.h },
  { side: "left", fx: (r) => r.x, fy: (r) => r.y + r.h / 2 },
  { side: "top", fx: (r) => r.x + r.w / 2, fy: (r) => r.y },
];

export default function GraphCanvas(props: Props) {
  const { doc, view, onViewChange, selected, onSelect, onDocChange, displays } = props;
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef(view); viewRef.current = view;
  const docRef = useRef(doc); docRef.current = doc;
  const interaction = useRef<Interaction>(null);

  const [dragPos, setDragPos] = useState<{ id: string; x: number; y: number } | null>(null);
  const [linkPos, setLinkPos] = useState<{ x: number; y: number } | null>(null);
  const [rewirePos, setRewirePos] = useState<{ x: number; y: number } | null>(null);
  const [panning, setPanning] = useState(false);
  const [menu, setMenu] = useState<Menu>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [spaceHeld, setSpaceHeld] = useState(false);
  const [hint, setHint] = useState("");
  const hintTimer = useRef<number | undefined>(undefined);
  const [legendOpen, setLegendOpen] = useState(true);

  // 节点实测尺寸（连线锚点/fit view 用）；tick 触发连线重算
  const sizes = useRef(new Map<string, NodeRect>());
  const [sizesTick, setSizesTick] = useState(0);
  const ro = useRef<ResizeObserver | null>(null);

  // ── 坐标换算 ──
  const toWorld = useCallback((clientX: number, clientY: number) => {
    const v = viewRef.current;
    const rect = viewportRef.current!.getBoundingClientRect();
    return { x: (clientX - rect.left - v.x) / v.zoom, y: (clientY - rect.top - v.y) / v.zoom };
  }, []);

  const showHint = useCallback((text: string) => {
    setHint(text);
    window.clearTimeout(hintTimer.current);
    hintTimer.current = window.setTimeout(() => setHint(""), 1600);
  }, []);

  // ── 缩放（锚点：指针或视口中心）──
  const zoomAt = useCallback((clientX: number, clientY: number, factor: number) => {
    const v = viewRef.current;
    const rect = viewportRef.current!.getBoundingClientRect();
    const px = clientX - rect.left, py = clientY - rect.top;
    const target = clampZoom(v.zoom * factor);
    if (target === v.zoom) {
      showHint(target <= MIN_ZOOM ? `已达最小缩放 ${MIN_ZOOM * 100}%` : `已达最大缩放 ${MAX_ZOOM * 100}%`);
      return;
    }
    const k = target / v.zoom;
    // 以指针为锚：指针下的图内点在缩放前后保持在同一屏幕位置
    onViewChange({ zoom: target, x: px - (px - v.x) * k, y: py - (py - v.y) * k });
  }, [onViewChange, showHint]);

  const zoomCenter = useCallback((factor: number) => {
    const rect = viewportRef.current!.getBoundingClientRect();
    zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, factor);
  }, [zoomAt]);

  const fit = useCallback(() => {
    const rect = viewportRef.current!.getBoundingClientRect();
    onViewChange(fitView(docRef.current.nodes, sizes.current, rect.width, rect.height));
  }, [onViewChange]);

  // 对外 API（页面新建节点取视口中心、工具栏联动）
  useEffect(() => {
    if (props.canvasApiRef) {
      props.canvasApiRef.current = {
        centerWorld: () => {
          const rect = viewportRef.current!.getBoundingClientRect();
          const v = viewRef.current;
          return { x: (rect.width / 2 - v.x) / v.zoom - NODE_W / 2, y: (rect.height / 2 - v.y) / v.zoom - 40 };
        },
        zoomBy: zoomCenter,
        resetZoom: () => zoomCenter(1 / viewRef.current.zoom),
        fit,
      };
    }
  }, [props.canvasApiRef, zoomCenter, fit]);

  // ── 滚轮：缩放/平移（必须非 passive 才能 preventDefault）──
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (e.ctrlKey) {
        // 触控板捏合（浏览器标准化为 ctrl+wheel）
        zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * WHEEL_ZOOM_SENS * 2.4));
      } else if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        // 触控板双指水平滑动 → 平移
        const v = viewRef.current;
        onViewChange({ ...v, x: v.x - e.deltaX, y: v.y - e.deltaY * 0.4 });
      } else {
        // 鼠标滚轮 / 双指纵向 → 以指针为锚缩放
        zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * WHEEL_ZOOM_SENS));
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAt, onViewChange]);

  // ── 空格 = 抓手模式 ──
  useEffect(() => {
    const isTyping = (t: EventTarget | null) =>
      t instanceof HTMLElement && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
    const down = (e: KeyboardEvent) => {
      if (e.code !== "Space" || isTyping(e.target)) return;
      e.preventDefault();
      setSpaceHeld(true);
    };
    const up = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      setSpaceHeld(false);
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, []);

  // ── 节点尺寸测量 ──
  useEffect(() => {
    if (!ro.current) {
      ro.current = new ResizeObserver((entries) => {
        let changed = false;
        for (const en of entries) {
          const el = en.target as HTMLElement;
          const id = el.dataset.ngNode;
          if (!id) continue;
          const w = el.offsetWidth, h = el.offsetHeight;
          const prev = sizes.current.get(id);
          if (!prev || prev.w !== w || prev.h !== h) {
            sizes.current.set(id, { x: 0, y: 0, w, h });
            changed = true;
          }
        }
        if (changed) setSizesTick((t) => t + 1);
      });
    }
    const observer = ro.current;
    const el = viewportRef.current;
    if (!el) return;
    const seen = new Set<Element>();
    el.querySelectorAll<HTMLElement>("[data-ng-node]").forEach((n) => { observer.observe(n); seen.add(n); });
    return () => { seen.forEach((n) => observer.unobserve(n)); };
  });

  // ── 指针交互主循环（capture 在视口根，统一收 move/up）──
  const capture = (e: React.PointerEvent) => {
    try { viewportRef.current!.setPointerCapture(e.pointerId); } catch { /* ignore */ }
  };

  const onViewportPointerDown = (e: React.PointerEvent) => {
    closeMenu();
    // 中键 / 空格 / 空白左键 → 平移（点击不动的抬起时清除选中）
    if (e.button === 1 || (e.button === 0 && (spaceHeld || e.target === e.currentTarget || (e.target as HTMLElement).dataset.ngBg))) {
      e.preventDefault();
      capture(e);
      interaction.current = { kind: "pan", lastX: e.clientX, lastY: e.clientY, moved: false };
      setPanning(true);
    }
  };

  const onViewportPointerMove = (e: React.PointerEvent) => {
    const it = interaction.current;
    if (!it) return;
    if (it.kind === "pan") {
      const dx = e.clientX - it.lastX, dy = e.clientY - it.lastY;
      if (Math.abs(dx) + Math.abs(dy) > 2) it.moved = true;
      it.lastX = e.clientX; it.lastY = e.clientY;
      onViewChange({ ...viewRef.current, x: viewRef.current.x + dx, y: viewRef.current.y + dy });
    } else if (it.kind === "drag") {
      const w = toWorld(e.clientX, e.clientY);
      const nx = Math.round(it.nodeX + (w.x - it.startWX));
      const ny = Math.round(it.nodeY + (w.y - it.startWY));
      if (!it.moved && (Math.abs(nx - it.nodeX) > 1 || Math.abs(ny - it.nodeY) > 1)) it.moved = true;
      it.nodeX = nx; it.nodeY = ny;
      setDragPos({ id: it.id, x: nx, y: ny });
    } else if (it.kind === "link") {
      const w = toWorld(e.clientX, e.clientY);
      it.wx = w.x; it.wy = w.y;
      setLinkPos({ x: w.x, y: w.y });
    } else if (it.kind === "rewire") {
      const w = toWorld(e.clientX, e.clientY);
      it.wx = w.x; it.wy = w.y;
      setRewirePos({ x: w.x, y: w.y });
    }
  };

  const onViewportPointerUp = (e: React.PointerEvent) => {
    const it = interaction.current;
    interaction.current = null;
    setPanning(false);
    if (!it) return;

    if (it.kind === "pan") {
      if (!it.moved && e.button === 0) { onSelect(null); setEditingId(null); }
      return;
    }
    if (it.kind === "drag") {
      const pos = dragPos;
      setDragPos(null);
      if (it.moved && pos) {
        const node = docRef.current.nodes.find((n) => n.id === it.id);
        if (node && (node.x !== pos.x || node.y !== pos.y)) {
          onDocChange(withNode(docRef.current, { ...node, x: pos.x, y: pos.y }));
        }
      } else if (!it.moved) {
        onSelect({ kind: "node", id: it.id });
      }
      return;
    }
    if (it.kind === "link") {
      setLinkPos(null);
      // 落点命中节点 → 连线；落在空白 → 生成新分支节点（自由节点）并连线
      const hit = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>("[data-ng-node]");
      const targetId = hit?.dataset.ngNode;
      if (targetId && targetId !== it.from) {
        const dup = docRef.current.edges.some((ed) => ed.from === it.from && ed.to === targetId);
        if (!dup) onDocChange(withEdge(docRef.current, it.from, targetId).doc);
      } else if (!hit) {
        const node = makeNoteNode(docRef.current, it.wx - NODE_W / 2, it.wy - 24);
        const withNodeDoc = { ...docRef.current, nodes: [...docRef.current.nodes, node] };
        onDocChange(withEdge(withNodeDoc, it.from, node.id).doc);
        setEditingId(node.id); // 新分支立即可编辑
      }
      return;
    }
    if (it.kind === "rewire") {
      setRewirePos(null);
      const hit = document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>("[data-ng-node]");
      const targetId = hit?.dataset.ngNode;
      if (targetId) {
        const edge = docRef.current.edges.find((ed) => ed.id === it.edgeId);
        const other = it.end === "from" ? edge?.to : edge?.from;
        if (targetId && other && targetId !== other) {
          onDocChange(rewireEdge(docRef.current, it.edgeId, it.end, targetId));
        }
      }
    }
  };

  const closeMenu = () => setMenu(null);

  // ── 节点交互 ──
  const onNodePointerDown = (e: React.PointerEvent, node: PlotGraphNodeDTO) => {
    if (e.button !== 0 || spaceHeld) return;
    if ((e.target as HTMLElement).closest(".ng-anchor, input, textarea, button")) return;
    e.stopPropagation();
    closeMenu();
    capture(e);
    const w = toWorld(e.clientX, e.clientY);
    interaction.current = { kind: "drag", id: node.id, startWX: w.x, startWY: w.y, nodeX: node.x, nodeY: node.y, moved: false };
  };

  const onAnchorPointerDown = (e: React.PointerEvent, node: PlotGraphNodeDTO, side: "top" | "right" | "bottom" | "left") => {
    if (e.button !== 0) return;
    e.stopPropagation(); e.preventDefault();
    closeMenu();
    capture(e);
    const w = toWorld(e.clientX, e.clientY);
    interaction.current = { kind: "link", from: node.id, side, wx: w.x, wy: w.y };
    setLinkPos({ x: w.x, y: w.y });
  };

  const onEdgePointerDown = (e: React.PointerEvent, edgeId: string) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    closeMenu();
    onSelect({ kind: "edge", id: edgeId });
    setEditingId(null);
  };

  const onReconnectHandleDown = (e: React.PointerEvent, edgeId: string, end: "from" | "to") => {
    if (e.button !== 0) return;
    e.stopPropagation(); e.preventDefault();
    capture(e);
    const w = toWorld(e.clientX, e.clientY);
    interaction.current = { kind: "rewire", edgeId, end, wx: w.x, wy: w.y };
    setRewirePos({ x: w.x, y: w.y });
  };

  const onNodeDoubleClick = (node: PlotGraphNodeDTO) => {
    if (node.type === "note") setEditingId(node.id);
    else props.onOpenNode(node);
  };

  /** 新建自由节点并立即进入编辑（双击空白 / 菜单 / 空态按钮共用） */
  const createNoteAt = (wx: number, wy: number) => {
    const node = makeNoteNode(docRef.current, wx, wy);
    onDocChange(withNode(docRef.current, node));
    onSelect({ kind: "node", id: node.id });
    setEditingId(node.id);
  };

  // ── 右键菜单 ──
  const onContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    const rect = viewportRef.current!.getBoundingClientRect();
    const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
    const hit = (e.target as HTMLElement).closest<HTMLElement>("[data-ng-node]");
    const edgeEl = (e.target as HTMLElement).closest<HTMLElement>("[data-ng-edge]");
    if (hit) {
      const id = hit.dataset.ngNode!;
      onSelect({ kind: "node", id });
      setMenu({ kind: "node", sx, sy, nodeId: id });
    } else if (edgeEl) {
      const id = edgeEl.dataset.ngEdge!;
      onSelect({ kind: "edge", id });
      setMenu({ kind: "edge", sx, sy, edgeId: id });
    } else {
      const w = toWorld(e.clientX, e.clientY);
      onSelect(null);
      setMenu({ kind: "blank", sx, sy, wx: w.x, wy: w.y });
    }
  };

  // ── 派生数据 ──
  const nodeRect = useCallback((n: PlotGraphNodeDTO): NodeRect => {
    const dragged = dragPos && dragPos.id === n.id ? dragPos : null;
    const x = dragged ? dragged.x : n.x;
    const y = dragged ? dragged.y : n.y;
    const measured = sizes.current.get(n.id);
    return { x, y, w: measured?.w ?? NODE_W, h: measured?.h ?? estimateNodeH(n) };
  }, [dragPos]);

  const rects = useMemo(() => {
    const m = new Map<string, NodeRect>();
    doc.nodes.forEach((n) => m.set(n.id, nodeRect(n)));
    return m;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc.nodes, nodeRect, dragPos, sizesTick]);

  // 视口裁剪：图内可视范围（外扩 160px）
  const viewRect = useMemo(() => {
    const el = viewportRef.current;
    const vw = el?.clientWidth ?? 1200, vh = el?.clientHeight ?? 800;
    return { x: -view.x / view.zoom - 160, y: -view.y / view.zoom - 160, w: vw / view.zoom + 320, h: vh / view.zoom + 320 };
  }, [view]);

  const visibleNodes = useMemo(
    () => doc.nodes.filter((n) => {
      const r = rects.get(n.id)!;
      return r.x + r.w > viewRect.x && r.x < viewRect.x + viewRect.w &&
             r.y + r.h > viewRect.y && r.y < viewRect.y + viewRect.h;
    }),
    [doc.nodes, rects, viewRect],
  );

  const tempLink = useMemo(() => {
    if (!linkPos || !interaction.current) return null;
    const it = interaction.current as Extract<Interaction, { kind: "link" }>;
    const r = rects.get(it.from);
    if (!r) return null;
    const side = SIDES.find((s) => s.side === it.side)!;
    const sx = side.fx(r), sy = side.fy(r);
    // 简化临时曲线：控制点沿源锚点方向外推
    const ox = Math.max(48, Math.abs(linkPos.x - sx) * 0.45);
    const oy = Math.max(40, Math.abs(linkPos.y - sy) * 0.45);
    const dirX = Math.sign(linkPos.x - sx) || 1;
    const dirY = Math.sign(linkPos.y - sy) || 1;
    return `M ${sx} ${sy} C ${sx + ox * dirX} ${sy + oy * dirY}, ${linkPos.x - ox * dirX} ${linkPos.y - oy * dirY}, ${linkPos.x} ${linkPos.y}`;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkPos, rects]);

  const cursorClass = spaceHeld ? "ng-cursor-grab" : "";

  const menuNode = menu && menu.kind === "node" ? doc.nodes.find((n) => n.id === menu.nodeId) : null;

  return (
    <div
      ref={viewportRef}
      className={"ng-viewport " + cursorClass + (panning ? " ng-panning" : "")}
      data-ng-bg="1"
      onPointerDown={onViewportPointerDown}
      onPointerMove={onViewportPointerMove}
      onPointerUp={onViewportPointerUp}
      onPointerCancel={onViewportPointerUp}
      onContextMenu={onContextMenu}
      onDoubleClick={(e) => {
        if (e.target !== e.currentTarget && !(e.target as HTMLElement).dataset.ngBg) return;
        const w = toWorld(e.clientX, e.clientY);
        createNoteAt(w.x - NODE_W / 2, w.y - 24);
      }}
      style={{
        backgroundPosition: `${view.x}px ${view.y}px`,
        backgroundSize: `${28 * view.zoom}px ${28 * view.zoom}px`,
      }}
    >
      {/* 世界层：一个 transform 承载全部平移缩放 */}
      <div
        className="ng-world"
        style={{ transform: `translate3d(${view.x}px, ${view.y}px, 0) scale(${view.zoom})` }}
      >
        {/* 连线层（SVG，图内坐标系） */}
        <svg className="ng-edges" width={1} height={1}>
          <defs>
            <marker id="ng-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" style={{ fill: "var(--ng-edge-color)" }} />
            </marker>
            <marker id="ng-arrow-hl" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" style={{ fill: "var(--ng-edge-color-hl)" }} />
            </marker>
          </defs>
          {doc.edges.map((edge) => {
            const a = rects.get(edge.from), b = rects.get(edge.to);
            if (!a || !b) return null;
            const isSel = selected?.kind === "edge" && selected.id === edge.id;
            // 视口裁剪：两端都不可见则跳过
            if (a.x + a.w < viewRect.x && b.x + b.w < viewRect.x) return null;
            if (a.x > viewRect.x + viewRect.w && b.x > viewRect.x + viewRect.w) return null;
            if (a.y + a.h < viewRect.y && b.y + b.h < viewRect.y) return null;
            if (a.y > viewRect.y + viewRect.h && b.y > viewRect.y + viewRect.h) return null;
            const geo = edgeGeometry(a, b);
            return (
              <g key={edge.id} data-ng-edge={edge.id} className={"ng-edge" + (isSel ? " ng-edge-selected" : "")}>
                <path className="ng-edge-hit" d={geo.d} onPointerDown={(e) => onEdgePointerDown(e, edge.id)} />
                <path className="ng-edge-line" d={geo.d} markerEnd={`url(#${isSel ? "ng-arrow-hl" : "ng-arrow"})`} />
              </g>
            );
          })}
          {/* 拖拽中的临时连线 */}
          {tempLink && <path className="ng-edge-temp" d={tempLink} />}
          {rewirePos && <path className="ng-edge-temp" d={`M ${rewirePos.x} ${rewirePos.y} L ${rewirePos.x + 0.01} ${rewirePos.y}`} />}
        </svg>

        {/* 节点层 */}
        {visibleNodes.map((n) => (
          <GraphCard
            key={n.id}
            node={n}
            rect={rects.get(n.id)!}
            display={displays.get(n.id) ?? { title: n.title }}
            selected={selected?.kind === "node" && selected.id === n.id}
            editing={editingId === n.id}
            linkSource={linkPos != null}
            onPointerDown={onNodePointerDown}
            onAnchorDown={onAnchorPointerDown}
            onDoubleClick={onNodeDoubleClick}
            onEditCommit={(title, content) => {
              const cur = docRef.current.nodes.find((x) => x.id === n.id);
              setEditingId(null);
              if (cur && (cur.title !== title || (cur.content ?? "") !== content)) {
                onDocChange(withNode(docRef.current, { ...cur, title, content }));
              }
            }}
            onEditCancel={() => setEditingId(null)}
          />
        ))}

        {/* 选中连线的重连端点 */}
        {selected?.kind === "edge" && (() => {
          const edge = doc.edges.find((e) => e.id === selected.id);
          if (!edge) return null;
          const a = rects.get(edge.from), b = rects.get(edge.to);
          if (!a || !b) return null;
          const geo = edgeGeometry(a, b);
          return (
            <>
              <div className="ng-handle" style={{ left: geo.sx, top: geo.sy }} onPointerDown={(e) => onReconnectHandleDown(e, edge.id, "from")} title="拖拽重新连接起点" />
              <div className="ng-handle" style={{ left: geo.tx, top: geo.ty }} onPointerDown={(e) => onReconnectHandleDown(e, edge.id, "to")} title="拖拽重新连接终点" />
            </>
          );
        })()}
      </div>

      {/* 缩放工具栏 */}
      <div className="ng-toolbar">
        <button className="ng-tool-btn" title="缩小（Ctrl+滚轮亦可）" onClick={() => zoomCenter(1 / ZOOM_STEP)}>−</button>
        <button className="ng-tool-zoom" title="点击回到 100%" onClick={() => zoomCenter(1 / view.zoom)}>
          {Math.round(view.zoom * 100)}%
        </button>
        <button className="ng-tool-btn" title="放大" onClick={() => zoomCenter(ZOOM_STEP)}>＋</button>
        <span className="ng-tool-sep" />
        <button className="ng-tool-btn" title="适应视图：把所有节点纳入可视范围" onClick={fit}>⤢ 适应</button>
        <button className="ng-tool-btn" title="回到 100% 并居中" onClick={() => { zoomCenter(1 / view.zoom); }}>1:1</button>
        {hint && <span className="ng-tool-hint">{hint}</span>}
      </div>

      {/* 图例 */}
      <div className="ng-legend">
        <button className="ng-legend-toggle" onClick={() => setLegendOpen((v) => !v)}>
          {legendOpen ? "▾" : "▸"} 图例
        </button>
        {legendOpen && (
          <div className="ng-legend-body">
            {Object.entries(NODE_META).map(([type, meta]) => (
              <span key={type} className="ng-legend-item">
                <i className={"ng-legend-dot"} data-ng-type={type} />
                {meta.icon} {meta.label}
              </span>
            ))}
            <span className="ng-legend-item ng-legend-edge"><i className="ng-legend-line" />连线（箭头 = 流程方向）</span>
          </div>
        )}
      </div>

      {/* 空图引导 */}
      {doc.nodes.length === 0 && (
        <div className="ng-empty">
          <div className="ng-empty-card">
            <p className="ng-empty-title">这张图还是空的</p>
            <p className="ng-empty-sub">从剧情文档生成初始布局，或直接双击空白处新建自由节点。</p>
            <div className="ng-empty-actions">
              <button className="ng-empty-btn primary" onClick={props.onImportLayout}>从剧情结构生成布局</button>
              <button className="ng-empty-btn" onClick={() => createNoteAt(0, 0)}>新建自由节点</button>
            </div>
          </div>
        </div>
      )}

      {/* 右键菜单（视口内绝对定位） */}
      {menu && (
        <div className="ng-menu" style={{
          left: Math.min(menu.sx, (viewportRef.current?.clientWidth ?? 800) - 230),
          top: Math.min(menu.sy, (viewportRef.current?.clientHeight ?? 600) - 260),
        }} onPointerDown={(e) => e.stopPropagation()}>
          {menu.kind === "blank" && (
            <>
              <button className="ng-menu-item" onClick={() => { createNoteAt(menu.wx, menu.wy); closeMenu(); }}>✎ 新建自由节点</button>
              <button className="ng-menu-item" onClick={() => { props.onCreateCombat(menu.wx, menu.wy); closeMenu(); }}>⚔ 新建战斗节点…</button>
              <div className="ng-menu-sep" />
              <p className="ng-menu-head">添加剧情节拍（未上图）</p>
              <div className="ng-menu-list">
                {props.availableBeats.length === 0 && <span className="ng-menu-empty">（都已上图）</span>}
                {props.availableBeats.map((b) => (
                  <button key={b.beatId} className="ng-menu-item" onClick={() => { props.onAddBeat(b, menu.wx, menu.wy); closeMenu(); }}>▸ {b.label}</button>
                ))}
              </div>
              <p className="ng-menu-head">添加战斗节点（未上图）</p>
              <div className="ng-menu-list">
                {props.availableCombats.length === 0 && <span className="ng-menu-empty">（都已上图）</span>}
                {props.availableCombats.map((c) => (
                  <button key={c.nodeId} className="ng-menu-item" onClick={() => { props.onAddCombatNode(c, menu.wx, menu.wy); closeMenu(); }}>⚔ {c.label}</button>
                ))}
              </div>
              {doc.nodes.length === 0 && (
                <>
                  <div className="ng-menu-sep" />
                  <button className="ng-menu-item" onClick={() => { props.onImportLayout(); closeMenu(); }}>⚙ 从剧情结构生成布局</button>
                </>
              )}
            </>
          )}
          {menu.kind === "node" && menuNode && (
            <>
              <button className="ng-menu-item" onClick={() => { onNodeDoubleClick(menuNode); closeMenu(); }}>
                {menuNode.type === "note" ? "✎ 编辑节点" : "↗ 打开编辑器"}
              </button>
              <button className="ng-menu-item danger" onClick={() => { props.onRequestDeleteNode(menu.nodeId); closeMenu(); }}>🗑 从图中移除…</button>
            </>
          )}
          {menu.kind === "edge" && (
            <button className="ng-menu-item danger" onClick={() => {
              onDocChange({ ...docRef.current, edges: docRef.current.edges.filter((e) => e.id !== menu.edgeId) });
              onSelect(null);
              closeMenu();
            }}>🗑 删除连线</button>
          )}
        </div>
      )}
    </div>
  );
}

function makeNoteNode(doc: PlotGraphDocDTO, x: number, y: number): PlotGraphNodeDTO {
  // 就地生成 id（不走 genId，避免重复渲染闭包取旧 doc）
  let id = `n_${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36).padStart(2, "0")}`;
  while (doc.nodes.some((n) => n.id === id)) id += "x";
  return { id, type: "note", title: "新节点", content: "", x: Math.round(x), y: Math.round(y), ref: null };
}

// ── 节点卡片 ──

interface CardProps {
  node: PlotGraphNodeDTO;
  rect: NodeRect;
  display: GraphNodeDisplay;
  selected: boolean;
  editing: boolean;
  linkSource: boolean;
  onPointerDown: (e: React.PointerEvent, node: PlotGraphNodeDTO) => void;
  onAnchorDown: (e: React.PointerEvent, node: PlotGraphNodeDTO, side: "top" | "right" | "bottom" | "left") => void;
  onDoubleClick: (node: PlotGraphNodeDTO) => void;
  onEditCommit: (title: string, content: string) => void;
  onEditCancel: () => void;
}

const GraphCard = memo(function GraphCard({
  node, rect, display, selected, editing, linkSource,
  onPointerDown, onAnchorDown, onDoubleClick, onEditCommit, onEditCancel,
}: CardProps) {
  const meta = NODE_META[node.type as PlotGraphNodeType] ?? NODE_META.note;
  const [title, setTitle] = useState(node.title);
  const [content, setContent] = useState(node.content ?? "");

  // 进入编辑时同步草稿
  useEffect(() => {
    if (editing) { setTitle(node.title); setContent(node.content ?? ""); }
  }, [editing, node.title, node.content]);

  const submit = () => onEditCommit(title.trim() || display.title || "未命名", content);

  return (
    <div
      data-ng-node={node.id}
      className={
        "ng-node " + `ng-node-${node.type}` +
        (selected ? " ng-selected" : "") +
        (display.missing ? " ng-missing" : "") +
        (linkSource ? " ng-linking" : "")
      }
      style={{ left: rect.x, top: rect.y, width: NODE_W }}
      onPointerDown={(e) => onPointerDown(e, node)}
      onDoubleClick={() => onDoubleClick(node)}
      onBlur={(e) => { if (editing && !e.currentTarget.contains(e.relatedTarget as Node)) submit(); }}
      onKeyDown={(e) => {
        if (editing && e.key === "Escape") onEditCancel();
        if (editing && e.key === "Enter" && (e.target as HTMLElement).tagName === "INPUT") submit();
      }}
    >
      <i className="ng-node-bar" />
      {editing ? (
        <div className="ng-node-edit">
          <input
            className="ng-edit-title" value={title} autoFocus
            onChange={(e) => setTitle(e.target.value)}
            placeholder="节点标题"
          />
          <textarea
            className="ng-edit-body" value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="内容备注（可空）"
            rows={3}
          />
          <div className="ng-edit-tip">Enter 保存标题 · Esc 取消 · 点击空白结束</div>
        </div>
      ) : (
        <>
          <div className="ng-node-head">
            <span className="ng-node-icon">{meta.icon}</span>
            <span className="ng-node-title" title={display.title}>{display.title || node.title || meta.label}</span>
          </div>
          {(display.subtitle || display.missing) && (
            <div className="ng-node-sub" title={display.subtitle}>
              {display.missing ? "⚠ 引用已失效" : display.subtitle}
            </div>
          )}
          {display.body && <div className="ng-node-body">{display.body}</div>}
          {display.progress && (
            <div className={"ng-node-progress ng-progress-" + display.progress}>
              {display.progress === "done" ? "已完成" : display.progress === "current" ? "进行中" : "未到达"}
            </div>
          )}
        </>
      )}
      {/* 边缘锚点：悬停浮现，拖出即连线 */}
      {SIDES.map((s) => (
        <i
          key={s.side}
          className={"ng-anchor ng-anchor-" + s.side}
          onPointerDown={(e) => onAnchorDown(e, node, s.side)}
          title="拖拽拉出连线（拖到空白生成新分支）"
        />
      ))}
    </div>
  );
});
