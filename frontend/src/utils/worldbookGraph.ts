import type { WorldBookCategoryDTO, WorldBookDetail, WorldBookPolicyDraft } from "../types";
import { categoryDescendants, flattenCategoryTree } from "./worldbookScope";
import {
  buildDependencyTree, DEPENDENCY_ROLES, edgeStateKey,
  type DependencyEdgeStatus, type DependencyRole, type DependencyStats, type DependencyTree,
} from "./worldbookDependency";

/** 依赖图谱的三种视图：分类结构 / 条目依赖（力导向网络）/ 依赖树（分层展开）。 */
export type WorldBookGraphView = "taxonomy" | "dependencies" | "tree";

export type GraphPoint = { x: number; y: number };
export type WorldBookGraphNode = {
  id: string;
  refId: string;
  kind: "category" | "entry";
  scopeType: WorldBookCategoryDTO["scope_type"];
  label: string;
  categoryId?: string;
  parentId?: string | null;
  radius: number;
  count?: number;
  fixed?: boolean;
  sourceDepth?: number;
  disabled?: boolean;
  /** 条目在导入策略中的角色；依赖视图才有。 */
  role?: DependencyRole;
  /** 树内展开层级与剩余深度预算。 */
  treeDepth?: number;
  remaining?: number;
  inCycle?: boolean;
  /** 未被任何导入源展开（含固定导入但未展开）。 */
  unreached?: boolean;
  /** 依赖树中的子节点数，用于折叠控件。 */
  childCount?: number;
};
export type WorldBookGraphEdge = {
  id: string;
  from: string;
  to: string;
  kind: "hierarchy" | "membership" | "dependency";
  /** 依赖边在真实展开中的状态。 */
  status?: DependencyEdgeStatus;
  /** 依赖树的父子骨架边。 */
  skeleton?: boolean;
  loop?: boolean;
};
export type WorldBookGraphData = {
  nodes: WorldBookGraphNode[];
  edges: WorldBookGraphEdge[];
  hiddenCount: number;
  entryCount: number;
  /** 依赖视图的角色分类统计（分类结构视图恒为空统计）。 */
  roles: Record<DependencyRole, number>;
  stats: DependencyStats | null;
  tree: DependencyTree | null;
};

export const categoryNodeId = (id: string) => `category:${id}`;
export const entryNodeId = (uid: string) => `entry:${uid}`;
export const dependencyEdgeId = (from: string, to: string) => JSON.stringify([from, to]);

const emptyRoles = (): Record<DependencyRole, number> =>
  Object.fromEntries(DEPENDENCY_ROLES.map((role) => [role, 0])) as Record<DependencyRole, number>;

/** A bounded view of the book, never a mutation of its import policy. */
export function buildWorldBookGraph(detail: WorldBookDetail, policy: WorldBookPolicyDraft, options: {
  view: WorldBookGraphView;
  categoryId?: string;
  query?: string;
  connectedOnly?: boolean;
  focusedUid?: string;
  limit?: number;
  /** 角色筛选；为空表示不按角色过滤。 */
  roles?: DependencyRole[];
}): WorldBookGraphData {
  const categories = detail.categories || [];
  const categoryMap = new Map(categories.map((category) => [category.id, category]));
  const fixed = new Set(policy.fixed_entry_uids);
  const sources = new Map(policy.dependency_sources.map((source) => [source.entry_uid, source.max_depth]));
  const configured = new Set([...fixed, ...sources.keys(), ...policy.dependency_edges.flatMap((edge) => [edge.from_uid, edge.to_uid])]);
  // 依赖树视图的层级语义由 depth 承担，分类节点不进树，避免两套层级互相干扰。
  const treeView = options.view === "tree";
  const dependencyView = options.view !== "taxonomy";
  const model = dependencyView ? buildDependencyTree(detail, policy) : null;
  const roleFilter = options.roles?.length ? new Set(options.roles) : null;
  const roleOf = (uid: string) => model?.roles.get(uid) || "orphan";
  const branch = options.categoryId ? categoryDescendants(categories, options.categoryId) : null;
  const query = options.query?.trim().toLocaleLowerCase() || "";
  const matches = detail.entries.filter((entry) =>
    (!branch || branch.has(entry.category_id || "unclassified")) &&
    (!roleFilter || roleFilter.has(roleOf(entry.uid))) &&
    (!options.connectedOnly || configured.has(entry.uid) || entry.uid === options.focusedUid) &&
    (!query || [entry.name, entry.uid, entry.character_id, categoryMap.get(entry.category_id || "")?.name,
      ...(entry.trigger_keys || [])].join(" ").toLocaleLowerCase().includes(query)));
  const limit = Math.max(1, options.limit ?? 400);
  // Keep the selected entry and configured relations visible first in large books.
  // 依赖视图再按「源 → 浅层 → 深层 → 未覆盖」排序，截断后留下的仍是最该看的节点。
  const fixedOnly = new Set(model?.fixedOnly || []);
  const priority = (uid: string): number => {
    if (uid === options.focusedUid) return -1;
    if (!model) return configured.has(uid) ? 1 : 2;
    const node = model.byUid.get(uid);
    if (!node) return fixedOnly.has(uid) ? 40 : 50;
    if (node.role === "source") return 0;
    return 2 + Math.min(30, node.depth);
  };
  const entries = matches.length > limit
    ? [...matches].sort((a, b) => priority(a.uid) - priority(b.uid) || a.uid.localeCompare(b.uid)).slice(0, limit)
    : matches;
  const visibleCategories = new Set<string>();
  const includeParents = (id: string) => {
    while (categoryMap.has(id) && !visibleCategories.has(id)) {
      visibleCategories.add(id);
      id = categoryMap.get(id)?.parent_id || "";
    }
  };
  if (!treeView) {
    for (const entry of entries) includeParents(entry.category_id || "unclassified");
    for (const category of categories) {
      if ((!branch || branch.has(category.id)) && !options.connectedOnly && !roleFilter &&
          (!query || category.name.toLocaleLowerCase().includes(query))) includeParents(category.id);
    }
  }
  const counts = new Map<string, number>();
  for (const entry of detail.entries) {
    const id = entry.category_id || "unclassified";
    counts.set(id, (counts.get(id) || 0) + 1);
  }
  const nodes: WorldBookGraphNode[] = treeView ? [] : flattenCategoryTree(categories)
    .filter(({ category }) => visibleCategories.has(category.id))
    .map(({ category }) => ({
      id: categoryNodeId(category.id), refId: category.id, kind: "category", scopeType: category.scope_type,
      label: category.name, parentId: category.parent_id, radius: 37, count: counts.get(category.id) || 0,
    }));
  const roles = emptyRoles();
  // 角色统计覆盖整本书，不随后续筛选变化，方便在工具栏里当筛选基数看。
  if (model) for (const entry of detail.entries) roles[roleOf(entry.uid)] += 1;
  nodes.push(...entries.map((entry): WorldBookGraphNode => {
    const node = model?.byUid.get(entry.uid);
    const role = roleOf(entry.uid);
    return {
      id: entryNodeId(entry.uid), refId: entry.uid, kind: "entry", label: entry.name || entry.uid,
      scopeType: categoryMap.get(entry.category_id || "unclassified")?.scope_type || "other",
      categoryId: entry.category_id || "unclassified", radius: 25, fixed: fixed.has(entry.uid),
      sourceDepth: sources.get(entry.uid), disabled: !entry.enabled,
      role: model ? role : undefined,
      treeDepth: node?.depth, remaining: node?.remaining,
      inCycle: model ? model.cycleSet.has(entry.uid) : undefined,
      unreached: model ? !node : undefined,
      childCount: node?.childUids.length,
    };
  }));
  const ids = new Set(nodes.map((node) => node.id));
  const edges: WorldBookGraphEdge[] = [];
  if (!treeView) {
    for (const node of nodes) {
      const parent = node.kind === "category" ? node.parentId : node.categoryId;
      if (parent && ids.has(categoryNodeId(parent))) edges.push({
        id: `${node.kind}:${node.id}`, from: categoryNodeId(parent), to: node.id,
        kind: node.kind === "category" ? "hierarchy" : "membership",
      });
    }
  }
  if (dependencyView) {
    for (const edge of policy.dependency_edges) {
      const from = entryNodeId(edge.from_uid), to = entryNodeId(edge.to_uid);
      if (!ids.has(from) || !ids.has(to)) continue;
      const state = model?.edgeStates.get(edgeStateKey(edge.from_uid, edge.to_uid));
      edges.push({
        id: dependencyEdgeId(edge.from_uid, edge.to_uid), from, to, kind: "dependency",
        status: state?.status, skeleton: state?.skeleton, loop: state?.loop,
      });
    }
  }
  return { nodes, edges, entryCount: entries.length, hiddenCount: matches.length - entries.length, roles, stats: model?.stats ?? null, tree: model };
}

function hash(value: string) {
  let result = 2166136261;
  for (const char of value) result = Math.imul(result ^ char.charCodeAt(0), 16777619);
  return result >>> 0;
}

/** Deterministic, bounded force layout; no timer or animation loop keeps running. */
export function layoutWorldBookGraph(graph: WorldBookGraphData): Record<string, GraphPoint> {
  const { nodes, edges } = graph;
  if (!nodes.length) return {};
  const index = new Map(nodes.map((node, i) => [node.id, i]));
  const roots = nodes.filter((node) => node.kind === "category" && (!node.parentId || !index.has(categoryNodeId(node.parentId))));
  const ring = roots.length < 2 ? 0 : Math.max(220, Math.sqrt(nodes.length) * 38);
  const anchors = new Map<string, GraphPoint>();
  roots.forEach((node, i) => {
    const angle = i * Math.PI * 2 / roots.length - Math.PI / 2;
    anchors.set(node.id, { x: Math.cos(angle) * ring, y: Math.sin(angle) * ring });
  });
  const groupIndex = new Map<string, number>();
  const points = nodes.map((node) => {
    if (anchors.has(node.id)) return { ...anchors.get(node.id)! };
    const parent = categoryNodeId((node.kind === "category" ? node.parentId : node.categoryId) || "");
    const anchor = anchors.get(parent) || { x: 0, y: 0 };
    const nth = groupIndex.get(parent) || 0;
    groupIndex.set(parent, nth + 1);
    const angle = nth * 2.399963 + (hash(parent) % 360) * Math.PI / 180;
    const distance = node.kind === "category" ? 190 : 120 + Math.sqrt(nth) * 53;
    const point = { x: anchor.x + Math.cos(angle) * distance, y: anchor.y + Math.sin(angle) * distance };
    if (node.kind === "category") anchors.set(node.id, point);
    return point;
  });
  const initial = points.map((point) => ({ ...point }));
  const springs = edges.map((edge) => ({ a: index.get(edge.from)!, b: index.get(edge.to)!,
    length: edge.kind === "hierarchy" ? 220 : edge.kind === "dependency" ? 185 : 155,
    strength: edge.kind === "dependency" ? 0.012 : 0.02,
  }));
  const iterations = nodes.length > 180 ? 90 : 140;
  for (let step = 0; step < iterations; step++) {
    const forces = points.map(() => ({ x: 0, y: 0 }));
    for (let a = 0; a < points.length; a++) {
      for (let b = a + 1; b < points.length; b++) {
        let dx = points[b].x - points[a].x, dy = points[b].y - points[a].y;
        if (Math.abs(dx) + Math.abs(dy) < 0.01) { dx = 1; dy = 0.5; }
        const distance = Math.hypot(dx, dy);
        const clearance = nodes[a].radius + nodes[b].radius + 58;
        const force = 1000 / Math.max(100, distance * distance) + Math.max(0, clearance - distance) * 0.2;
        const fx = dx / distance * force, fy = dy / distance * force;
        forces[a].x -= fx; forces[a].y -= fy;
        forces[b].x += fx; forces[b].y += fy;
      }
    }
    for (const spring of springs) {
      const dx = points[spring.b].x - points[spring.a].x, dy = points[spring.b].y - points[spring.a].y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const force = (distance - spring.length) * spring.strength;
      const fx = dx / distance * force, fy = dy / distance * force;
      forces[spring.a].x += fx; forces[spring.a].y += fy;
      forces[spring.b].x -= fx; forces[spring.b].y -= fy;
    }
    const cooling = 1 - step / iterations * 0.65;
    points.forEach((point, i) => {
      const gravity = nodes[i].kind === "category" ? 0.035 : 0.002;
      point.x += Math.max(-18, Math.min(18, forces[i].x + (initial[i].x - point.x) * gravity)) * cooling;
      point.y += Math.max(-18, Math.min(18, forces[i].y + (initial[i].y - point.y) * gravity)) * cooling;
    });
  }
  return Object.fromEntries(nodes.map((node, i) => [node.id, points[i]]));
}

export function worldBookEdgeGeometry(a: GraphPoint, b: GraphPoint, radiusA: number, radiusB: number, curved = false) {
  const dx = b.x - a.x, dy = b.y - a.y, length = Math.max(1, Math.hypot(dx, dy));
  const bend = curved ? Math.min(65, length * 0.2) : 0;
  const control = { x: (a.x + b.x) / 2 - dy / length * bend, y: (a.y + b.y) / 2 + dx / length * bend };
  const startAngle = Math.atan2(control.y - a.y, control.x - a.x);
  const endAngle = Math.atan2(b.y - control.y, b.x - control.x);
  const start = { x: a.x + Math.cos(startAngle) * (radiusA + 5), y: a.y + Math.sin(startAngle) * (radiusA + 5) };
  const end = { x: b.x - Math.cos(endAngle) * (radiusB + 9), y: b.y - Math.sin(endAngle) * (radiusB + 9) };
  return {
    path: `M ${start.x} ${start.y} Q ${control.x} ${control.y} ${end.x} ${end.y}`,
    label: { x: (start.x + 2 * control.x + end.x) / 4, y: (start.y + 2 * control.y + end.y) / 4 },
  };
}

/** Use a wide canvas instead of squeezing a tall cluster into a tiny zoom. */
export function spreadWorldBookGraph(positions: Record<string, GraphPoint>, aspectRatio: number): Record<string, GraphPoint> {
  const points = Object.values(positions);
  if (points.length < 2) return positions;
  const left = Math.min(...points.map((point) => point.x)), right = Math.max(...points.map((point) => point.x));
  const top = Math.min(...points.map((point) => point.y)), bottom = Math.max(...points.map((point) => point.y));
  const stretch = Math.max(1, Math.min(3.5, Math.max(0.5, aspectRatio) * (bottom - top) / Math.max(1, right - left)));
  const center = (left + right) / 2;
  return Object.fromEntries(Object.entries(positions).map(([id, point]) => [id, { x: center + (point.x - center) * stretch, y: point.y }]));
}
