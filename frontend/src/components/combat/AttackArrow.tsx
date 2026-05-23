type Point = { x: number; y: number };

function qBezier(p0: Point, p1: Point, p2: Point, t: number): Point {
  const mt = 1 - t;
  return {
    x: mt * mt * p0.x + 2 * mt * t * p1.x + t * t * p2.x,
    y: mt * mt * p0.y + 2 * mt * t * p1.y + t * t * p2.y,
  };
}

function qBezierTangent(p0: Point, p1: Point, p2: Point, t: number): Point {
  const mt = 1 - t;
  return {
    x: 2 * mt * (p1.x - p0.x) + 2 * t * (p2.x - p1.x),
    y: 2 * mt * (p1.y - p0.y) + 2 * t * (p2.y - p1.y),
  };
}

/** Get the screen-space center of a grid cell by walking the DOM */
function getCellCenter(
  gridEl: HTMLElement,
  row: number,
  col: number,
): Point | null {
  try {
    const rowEl = gridEl.children[row + 1]; // +1 skip column-labels row
    if (!rowEl) return null;
    // rowEl.children: [0]=row label, [1]=cell at col 0, [2]=cell at col 1, ...
    const cellEl = rowEl.children[col + 1] as HTMLElement | undefined;
    if (!cellEl) return null;
    const r = cellEl.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  } catch {
    return null;
  }
}

const TRIM_START = 0.18;
const TRIM_END = 0.82;
const ARC_STEPS = 48;

interface Props {
  from: [number, number]; // [row, col]
  to: [number, number];   // [row, col]
  gridEl: HTMLElement;
  parentEl: HTMLElement;
}

export default function AttackArrow({ from, to, gridEl, parentEl }: Props) {
  const pFrom = getCellCenter(gridEl, from[0], from[1]);
  const pTo = getCellCenter(gridEl, to[0], to[1]);

  // 调试：检查坐标是否成功获取
  if (!pFrom || !pTo) {
    console.warn('[AttackArrow] Failed to get cell centers', { pFrom, pTo, from, to });
    return null;
  }

  // Convert screen-space to parent-relative
  const pr = parentEl.getBoundingClientRect();
  const relFrom: Point = { x: pFrom.x - pr.left, y: pFrom.y - pr.top };
  const relTo: Point = { x: pTo.x - pr.left, y: pTo.y - pr.top };

  const dx = relTo.x - relFrom.x;
  const dy = relTo.y - relFrom.y;
  const len = Math.sqrt(dx * dx + dy * dy);
  if (len < 1) return null;

  // Control point: midpoint + perpendicular offset, always curving upward on screen
  const mx = (relFrom.x + relTo.x) / 2;
  const my = (relFrom.y + relTo.y) / 2;
  const arcHeight = Math.max(len * 0.35, 30);
  const p1y = dx / len;
  const p2y = -dx / len;
  const useFirst = p1y < p2y;
  const perpX = useFirst ? -dy / len : dy / len;
  const perpY = useFirst ? dx / len : -dx / len;
  const cp: Point = {
    x: mx + perpX * arcHeight,
    y: my + perpY * arcHeight,
  };

  // Build polyline from trimStart to trimEnd
  // 舍入坐标到小数点后两位，处理高 DPI 屏幕的浮点精度问题
  const points: string[] = [];
  for (let i = 0; i <= ARC_STEPS; i++) {
    const t = TRIM_START + (TRIM_END - TRIM_START) * (i / ARC_STEPS);
    const pt = qBezier(relFrom, cp, relTo, t);
    const x = Math.round(pt.x * 100) / 100;
    const y = Math.round(pt.y * 100) / 100;
    points.push(`${x},${y}`);
  }

  // Arrowhead at trimEnd
  const tip = qBezier(relFrom, cp, relTo, TRIM_END);
  const tan = qBezierTangent(relFrom, cp, relTo, TRIM_END);
  const tLen = Math.sqrt(tan.x * tan.x + tan.y * tan.y);
  if (tLen < 0.001) return null;
  const tux = tan.x / tLen;
  const tuy = tan.y / tLen;

  const headLen = 10;
  const headW = 5;
  const bx = tip.x - tux * headLen;
  const by = tip.y - tuy * headLen;
  const hx = -tuy * headW;
  const hy = tux * headW;

  const pad = 40;
  const minX = Math.min(relFrom.x, relTo.x, cp.x) - pad;
  const minY = Math.min(relFrom.y, relTo.y, cp.y) - pad;
  const maxX = Math.max(relFrom.x, relTo.x, cp.x) + pad;
  const maxY = Math.max(relFrom.y, relTo.y, cp.y) + pad;
  const vbW = maxX - minX;
  const vbH = maxY - minY;

  return (
    <svg
      className="attack-arrow-svg"
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width: "100%",
        height: "100%",
        zIndex: 50,
        pointerEvents: "none",
        overflow: "visible",
      }}
      width={parentEl.clientWidth}
      height={parentEl.clientHeight}
      preserveAspectRatio="none"
      viewBox={`${minX} ${minY} ${vbW} ${vbH}`}
    >
      <g className="attack-arrow-group">
        <polyline
          points={points.join(" ")}
          fill="none"
          className="attack-arrow-glow"
        />
        <polyline
          points={points.join(" ")}
          fill="none"
          className="attack-arrow-line"
        />
        <polygon
          points={`${tip.x},${tip.y} ${bx + hx},${by + hy} ${bx - hx},${by - hy}`}
          className="attack-arrow-head"
        />
      </g>
    </svg>
  );
}
