import type { Point } from "./gridUtils";

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

const TRIM_START = 0.18;
const TRIM_END = 0.82;
const ARC_STEPS = 48;

interface Props {
  /** Parent-relative pixel position of source cell centre. */
  fromPos: Point;
  /** Parent-relative pixel position of target cell centre (optional when using toPoint). */
  toPos?: Point | null;
  /** Parent-relative mouse position override (used during card drag). */
  toPoint?: Point | null;
  /** Container pixel dimensions for SVG viewBox. */
  containerWidth: number;
  containerHeight: number;
}

export default function AttackArrow({ fromPos, toPos, toPoint, containerWidth, containerHeight }: Props) {
  const relFrom = fromPos;
  const relTo = toPoint || toPos;

  if (!relTo) return null;

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
      viewBox={`0 0 ${containerWidth} ${containerHeight}`}
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
