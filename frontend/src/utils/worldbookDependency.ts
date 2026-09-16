/**
 * 世界书依赖模型：条目节点的角色分类 + 按导入源展开的依赖树。
 *
 * 遍历语义与后端 `src/worldbook_scope.py:expand_sources` 一致：多源入队、同一节点保留
 * 「最大剩余深度」、剩余深度为 0 时不再展开。因此依赖树展示的就是真实注入时会被展开的
 * 范围，而不是另一套近似示意结构；未展开的边会被明确标成「超深度」或「未启用」。
 */
import type { WorldBookDetail, WorldBookPolicyDraft } from "../types";

export type TreePoint = { x: number; y: number };

export type DependencyRole = "source" | "fixed" | "bridge" | "leaf" | "orphan";

/** 图例与筛选的固定顺序。 */
export const DEPENDENCY_ROLES: DependencyRole[] = ["source", "fixed", "bridge", "leaf", "orphan"];

export const ROLE_LABELS: Record<DependencyRole, string> = {
  source: "导入源",
  fixed: "固定导入",
  bridge: "中转节点",
  leaf: "叶子节点",
  orphan: "未配置",
};

export const ROLE_GLYPHS: Record<DependencyRole, string> = {
  source: "源", fixed: "固", bridge: "转", leaf: "叶", orphan: "未",
};

export const ROLE_HINTS: Record<DependencyRole, string> = {
  source: "沿出边按遍历深度展开的起点",
  fixed: "始终作为注入候选，但不隐式展开依赖",
  bridge: "既是依赖目标，又继续向下展开",
  leaf: "只作为依赖目标，没有下游",
  orphan: "没有参与固定导入、导入源或依赖边",
};

/** 依赖边在真实展开中的状态。 */
export type DependencyEdgeStatus = "active" | "capped" | "idle";

export type DependencyEdgeState = {
  fromUid: string;
  toUid: string;
  status: DependencyEdgeStatus;
  /** 位于依赖环内（同一强连通分量）。 */
  loop: boolean;
  /** 依赖树的父子骨架边。 */
  skeleton: boolean;
};

export type DependencyTreeNode = {
  uid: string;
  /** 自所属导入源起算的展开层级。 */
  depth: number;
  /** 展开该节点时剩余的深度预算。 */
  remaining: number;
  /** 根导入源（自身即源时为自身）。 */
  sourceUid: string;
  parentUid: string | null;
  childUids: string[];
  role: DependencyRole;
  inCycle: boolean;
};

export type DependencyStats = {
  sourceCount: number;
  fixedCount: number;
  reachableCount: number;
  /** 未被任何导入源展开、且未固定导入的条目数。 */
  looseCount: number;
  /** 固定导入但未被展开的条目数。 */
  fixedOnlyCount: number;
  maxDepth: number;
  activeEdges: number;
  cappedEdges: number;
  idleEdges: number;
  loopEdges: number;
  /** 处于依赖环内的节点数。 */
  cycleCount: number;
  /** 每个层级上的节点数（下标即层级）。 */
  depthCounts: number[];
};

export type DependencyTree = {
  roots: string[];
  nodes: DependencyTreeNode[];
  byUid: Map<string, DependencyTreeNode>;
  /** 全部条目的角色，含未被展开的条目。 */
  roles: Map<string, DependencyRole>;
  edgeStates: Map<string, DependencyEdgeState>;
  reachable: Set<string>;
  loose: string[];
  fixedOnly: string[];
  cycleUids: string[];
  /** 位于依赖环内的条目集合，含未被任何源到达的环。 */
  cycleSet: Set<string>;
  stats: DependencyStats;
};

export const edgeStateKey = (from: string, to: string) => JSON.stringify([from, to]);

/** 节点角色只描述策略配置，与是否被展开无关。 */
export function classifyDependencyRoles(detail: WorldBookDetail, policy: WorldBookPolicyDraft): Map<string, DependencyRole> {
  const known = new Set((detail.entries || []).map((entry) => entry.uid));
  const outgoing = new Set<string>();
  const incoming = new Set<string>();
  for (const edge of policy.dependency_edges || []) {
    if (typeof edge?.from_uid !== "string" || typeof edge?.to_uid !== "string") continue;
    if (!known.has(edge.from_uid) || !known.has(edge.to_uid)) continue;
    outgoing.add(edge.from_uid);
    incoming.add(edge.to_uid);
  }
  const sources = new Set<string>();
  for (const source of policy.dependency_sources || []) if (known.has(source?.entry_uid)) sources.add(source.entry_uid);
  const fixed = new Set<string>();
  for (const uid of policy.fixed_entry_uids || []) if (known.has(uid)) fixed.add(uid);
  const roles = new Map<string, DependencyRole>();
  for (const uid of known) {
    roles.set(uid,
      sources.has(uid) ? "source"
        : fixed.has(uid) ? "fixed"
          : outgoing.has(uid) && incoming.has(uid) ? "bridge"
            : incoming.has(uid) ? "leaf"
              : "orphan");
  }
  return roles;
}

/** Tarjan 强连通分量；返回每个节点的分量号与各分量大小。 */
function stronglyConnected(adjacency: Map<string, string[]>, nodes: string[]) {
  const index = new Map<string, number>();
  const low = new Map<string, number>();
  const component = new Map<string, number>();
  const onStack = new Set<string>();
  const stack: string[] = [];
  const sizes: number[] = [];
  let counter = 0;
  for (const root of nodes) {
    if (index.has(root)) continue;
    const work: Array<{ uid: string; edge: number }> = [{ uid: root, edge: 0 }];
    index.set(root, counter); low.set(root, counter); counter++;
    stack.push(root); onStack.add(root);
    while (work.length) {
      const frame = work[work.length - 1];
      const neighbours = adjacency.get(frame.uid) || [];
      if (frame.edge < neighbours.length) {
        const next = neighbours[frame.edge++];
        if (!index.has(next)) {
          index.set(next, counter); low.set(next, counter); counter++;
          stack.push(next); onStack.add(next);
          work.push({ uid: next, edge: 0 });
        } else if (onStack.has(next)) {
          low.set(frame.uid, Math.min(low.get(frame.uid)!, index.get(next)!));
        }
        continue;
      }
      work.pop();
      if (work.length) {
        const parent = work[work.length - 1];
        low.set(parent.uid, Math.min(low.get(parent.uid)!, low.get(frame.uid)!));
      }
      if (low.get(frame.uid) === index.get(frame.uid)) {
        let size = 0;
        for (;;) {
          const uid = stack.pop()!;
          onStack.delete(uid);
          component.set(uid, sizes.length);
          size++;
          if (uid === frame.uid) break;
        }
        sizes.push(size);
      }
    }
  }
  return { component, sizes };
}

export function buildDependencyTree(detail: WorldBookDetail, policy: WorldBookPolicyDraft): DependencyTree {
  const entries = detail.entries || [];
  const known = new Set(entries.map((entry) => entry.uid));
  const roles = classifyDependencyRoles(detail, policy);
  const adjacency = new Map<string, string[]>();
  const reverse = new Map<string, string[]>();
  const pairs: Array<[string, string]> = [];
  const seenPairs = new Set<string>();
  for (const edge of policy.dependency_edges || []) {
    const from = edge?.from_uid, to = edge?.to_uid;
    if (typeof from !== "string" || typeof to !== "string") continue;
    if (!known.has(from) || !known.has(to)) continue;
    const key = edgeStateKey(from, to);
    if (seenPairs.has(key)) continue;
    seenPairs.add(key);
    pairs.push([from, to]);
    adjacency.set(from, [...(adjacency.get(from) || []), to]);
    reverse.set(to, [...(reverse.get(to) || []), from]);
  }
  for (const list of adjacency.values()) list.sort();

  const budget = new Map<string, number>();
  for (const source of policy.dependency_sources || []) {
    if (typeof source?.entry_uid !== "string" || !known.has(source.entry_uid)) continue;
    if (!Number.isInteger(source.max_depth)) continue;
    budget.set(source.entry_uid, Math.max(0, Math.min(32, source.max_depth)));
  }
  const fixed = new Set<string>();
  for (const uid of policy.fixed_entry_uids || []) if (known.has(uid)) fixed.add(uid);

  // 与后端 expand_sources 同构：多源入队，按最大剩余深度去重，剩余 0 即停止展开。
  const record = new Map<string, { remaining: number; parentUid: string | null }>();
  const queue: Array<{ uid: string; remaining: number; parentUid: string | null }> = [];
  for (const [uid, depth] of budget) queue.push({ uid, remaining: depth, parentUid: null });
  for (let i = 0; i < queue.length; i++) {
    const item = queue[i];
    const current = record.get(item.uid);
    if (current && item.remaining <= current.remaining) continue;
    record.set(item.uid, { remaining: item.remaining, parentUid: item.parentUid });
    if (item.remaining <= 0) continue;
    for (const target of adjacency.get(item.uid) || []) {
      queue.push({ uid: target, remaining: item.remaining - 1, parentUid: item.uid });
    }
  }
  // 导入源始终落在树根，即使它同时也能被别的源到达。
  for (const [uid, depth] of budget) {
    const current = record.get(uid);
    record.set(uid, { remaining: Math.max(current?.remaining ?? depth, depth), parentUid: null });
  }

  // 父链不可能成环：只有当父节点剩余深度严格大于子节点时才会成为其父节点，
  // 沿着父链走 remaining 单调递减，因此 rootCache 那类防御在这里并不需要。
  const parentOf = new Map<string, string | null>();
  for (const [uid, item] of record) parentOf.set(uid, item.parentUid);

  const childUids = new Map<string, string[]>();
  const roots: string[] = [];
  for (const uid of record.keys()) {
    const parent = parentOf.get(uid) ?? null;
    if (parent && record.has(parent)) childUids.set(parent, [...(childUids.get(parent) || []), uid]);
    else { parentOf.set(uid, null); roots.push(uid); }
  }
  roots.sort();
  for (const list of childUids.values()) list.sort();

  const depthMap = new Map<string, number>();
  const remainingMap = new Map<string, number>();
  const sourceMap = new Map<string, string>();
  const walk: Array<{ uid: string; depth: number; root: string }> = roots.map((uid) => ({ uid, depth: 0, root: uid }));
  for (let i = 0; i < walk.length; i++) {
    const item = walk[i];
    if (depthMap.has(item.uid)) continue;
    const rootRemaining = record.get(item.root)?.remaining ?? 0;
    depthMap.set(item.uid, item.depth);
    sourceMap.set(item.uid, item.root);
    remainingMap.set(item.uid, Math.max(0, rootRemaining - item.depth));
    for (const child of childUids.get(item.uid) || []) walk.push({ uid: child, depth: item.depth + 1, root: item.root });
  }

  const edgeNodes = [...new Set(pairs.flatMap(([from, to]) => [from, to]))].sort();
  const selfLoops = new Set(pairs.filter(([from, to]) => from === to).map(([from]) => from));
  const { component, sizes } = stronglyConnected(adjacency, edgeNodes);
  const cycleSet = new Set<string>();
  for (const uid of edgeNodes) {
    const id = component.get(uid);
    if (id === undefined) continue;
    if (sizes[id] > 1 || selfLoops.has(uid)) cycleSet.add(uid);
  }

  const edgeStates = new Map<string, DependencyEdgeState>();
  let activeEdges = 0, cappedEdges = 0, idleEdges = 0, loopEdges = 0;
  for (const [from, to] of pairs) {
    const remaining = remainingMap.get(from);
    const status: DependencyEdgeStatus = remaining === undefined ? "idle" : remaining > 0 ? "active" : "capped";
    const loop = cycleSet.has(from) && cycleSet.has(to) && component.get(from) === component.get(to);
    if (status === "active") activeEdges++;
    else if (status === "capped") cappedEdges++;
    else idleEdges++;
    if (loop) loopEdges++;
    edgeStates.set(edgeStateKey(from, to), {
      fromUid: from, toUid: to, status, loop, skeleton: (parentOf.get(to) ?? null) === from,
    });
  }

  const nodes: DependencyTreeNode[] = [...depthMap.keys()]
    .sort((a, b) => depthMap.get(a)! - depthMap.get(b)! || a.localeCompare(b))
    .map((uid) => ({
      uid,
      depth: depthMap.get(uid)!,
      remaining: remainingMap.get(uid)!,
      sourceUid: sourceMap.get(uid)!,
      parentUid: parentOf.get(uid) ?? null,
      childUids: childUids.get(uid) || [],
      role: roles.get(uid) || "orphan",
      inCycle: cycleSet.has(uid),
    }));
  const byUid = new Map(nodes.map((node) => [node.uid, node]));

  const loose: string[] = [], fixedOnly: string[] = [];
  for (const entry of entries) {
    if (depthMap.has(entry.uid)) continue;
    if (fixed.has(entry.uid)) fixedOnly.push(entry.uid);
    else loose.push(entry.uid);
  }

  const depthCounts: number[] = [];
  for (const depth of depthMap.values()) depthCounts[depth] = (depthCounts[depth] || 0) + 1;
  const maxDepth = depthCounts.length ? depthCounts.length - 1 : 0;
  const cycleUids = entries.map((entry) => entry.uid).filter((uid) => cycleSet.has(uid));

  return {
    roots, nodes, byUid, roles, edgeStates,
    reachable: new Set(depthMap.keys()),
    loose, fixedOnly, cycleUids, cycleSet,
    stats: {
      sourceCount: budget.size, fixedCount: fixed.size, reachableCount: depthMap.size,
      looseCount: loose.length, fixedOnlyCount: fixedOnly.length, maxDepth,
      activeEdges, cappedEdges, idleEdges, loopEdges, cycleCount: cycleUids.length,
      depthCounts: Array.from({ length: maxDepth + 1 }, (_, depth) => depthCounts[depth] || 0),
    },
  };
}

/** 默认只展开覆盖到目标节点数为止的前几层，避免大树一次性铺开。 */
export function defaultTreeDepthLimit(tree: DependencyTree, target = 60) {
  let cumulative = 0;
  for (let depth = 0; depth <= tree.stats.maxDepth; depth++) {
    cumulative += tree.stats.depthCounts[depth] || 0;
    if (cumulative >= target || depth >= tree.stats.maxDepth) return Math.max(1, depth);
  }
  return Math.max(1, tree.stats.maxDepth);
}

/** 从导入源到该条目的树内路径；未被展开时返回空数组。 */
export function dependencyPath(tree: DependencyTree, uid: string): string[] {
  const node = tree.byUid.get(uid);
  if (!node) return [];
  const path = [uid];
  const guard = new Set(path);
  let current = node.parentUid;
  while (current && !guard.has(current)) {
    guard.add(current);
    path.unshift(current);
    current = tree.byUid.get(current)?.parentUid ?? null;
  }
  return path;
}

/** 树内后代数量，用于折叠提示与概览。 */
export function dependencyDescendants(tree: DependencyTree, uid: string): number {
  const node = tree.byUid.get(uid);
  if (!node) return 0;
  let total = 0;
  const stack = [...node.childUids];
  const seen = new Set<string>();
  while (stack.length) {
    const current = stack.pop()!;
    if (seen.has(current)) continue;
    seen.add(current);
    total++;
    stack.push(...(tree.byUid.get(current)?.childUids || []));
  }
  return total;
}

export type DependencyTreeLevel = { depth: number; y: number; count: number; label: string };
export type DependencyTreeBand = { y: number; count: number; label: string; kind: "fixed" | "loose" };
export type DependencyTreeLayout = {
  positions: Record<string, TreePoint>;
  levels: DependencyTreeLevel[];
  bands: DependencyTreeBand[];
  bounds: { left: number; top: number; right: number; bottom: number };
  /** 因角色筛选、层级上限或折叠而未上图的树内节点数。 */
  hidden: number;
  visible: number;
  /** 是否还有被层级上限或折叠藏起来的更深层级。 */
  hasDeeper: boolean;
};

export type DependencyTreeLayoutOptions = {
  /** 允许上图的条目集合（角色筛选后的结果）。 */
  allowed?: Set<string> | null;
  depthLimit?: number;
  collapsed?: Set<string> | null;
  showLoose?: boolean;
};

const COLUMN_GAP = 122;
const LEVEL_GAP = 162;
const BAND_COLUMNS = 12;
const BAND_ROW_GAP = 104;
const BAND_GAP = 110;

/**
 * 分层树布局：层级决定纵坐标，同层节点按后序遍历取槽位，父节点居中于子节点。
 * 未覆盖条目单独成带，按固定列数换行，避免个别大书把画布拉成一条细线。
 */
export function layoutDependencyTree(tree: DependencyTree, options: DependencyTreeLayoutOptions = {}): DependencyTreeLayout {
  const allowed = options.allowed ?? null;
  const collapsed = options.collapsed ?? new Set<string>();
  const depthLimit = Math.max(0, Math.floor(options.depthLimit ?? Number.MAX_SAFE_INTEGER));
  const visible = new Set<string>();
  let hidden = 0;
  // tree.nodes 已按层级升序排列，父节点必然先于子节点被判定。
  for (const node of tree.nodes) {
    if (allowed && !allowed.has(node.uid)) continue;
    if (node.depth > depthLimit) { hidden++; continue; }
    if (node.parentUid && (!visible.has(node.parentUid) || collapsed.has(node.parentUid))) { hidden++; continue; }
    visible.add(node.uid);
  }
  const childrenOf = new Map<string, string[]>();
  const parentOf = new Map<string, string | null>();
  for (const uid of visible) {
    const node = tree.byUid.get(uid)!;
    childrenOf.set(uid, node.childUids.filter((child) => visible.has(child)));
    parentOf.set(uid, node.parentUid && visible.has(node.parentUid) ? node.parentUid : null);
  }

  const x = new Map<string, number>();
  const rootList = [...visible].filter((uid) => !parentOf.get(uid)).sort();
  let cursor = 0;
  const stack: string[] = [...rootList].reverse();
  const expanded = new Set<string>();
  const childXs = new Map<string, number[]>();
  while (stack.length) {
    const uid = stack[stack.length - 1];
    const kids = childrenOf.get(uid) || [];
    if (kids.length && !expanded.has(uid)) {
      expanded.add(uid);
      for (let i = kids.length - 1; i >= 0; i--) stack.push(kids[i]);
      continue;
    }
    stack.pop();
    const slot = kids.length
      ? (Math.min(...(childXs.get(uid) || [0])) + Math.max(...(childXs.get(uid) || [0]))) / 2
      : cursor++ * COLUMN_GAP;
    x.set(uid, slot);
    const parent = parentOf.get(uid);
    if (parent) childXs.set(parent, [...(childXs.get(parent) || []), slot]);
  }

  const positions: Record<string, TreePoint> = {};
  const levelCounts = new Map<number, number>();
  for (const uid of visible) {
    const depth = tree.byUid.get(uid)!.depth;
    levelCounts.set(depth, (levelCounts.get(depth) || 0) + 1);
    positions[uid] = { x: x.get(uid) ?? 0, y: depth * LEVEL_GAP };
  }

  const allowLoose = (uid: string) => !allowed || allowed.has(uid);
  const bands: DependencyTreeBand[] = [];
  // 未覆盖带接在真正画出来的最深一层之后，避免浅树（例如深度 0）与层级导引线重叠。
  let deepestDrawn = -1;
  for (const uid of visible) deepestDrawn = Math.max(deepestDrawn, tree.byUid.get(uid)!.depth);
  let baseY = (deepestDrawn + 1) * LEVEL_GAP + BAND_GAP;
  if (options.showLoose) {
    const groups: Array<{ items: string[]; label: string; kind: "fixed" | "loose" }> = [
      { items: tree.fixedOnly.filter(allowLoose), label: "固定导入 · 未进入依赖展开", kind: "fixed" },
      { items: tree.loose.filter(allowLoose), label: "未被任何导入源覆盖", kind: "loose" },
    ];
    for (const group of groups) {
      if (!group.items.length) continue;
      bands.push({ y: baseY, count: group.items.length, label: group.label, kind: group.kind });
      group.items.forEach((uid, i) => {
        const row = Math.floor(i / BAND_COLUMNS), column = i % BAND_COLUMNS;
        const inRow = Math.min(BAND_COLUMNS, group.items.length - row * BAND_COLUMNS);
        positions[uid] = { x: (column - (inRow - 1) / 2) * COLUMN_GAP, y: baseY + row * BAND_ROW_GAP };
      });
      const rows = Math.ceil(group.items.length / BAND_COLUMNS);
      baseY += rows * BAND_ROW_GAP + BAND_GAP;
    }
  }

  const points = Object.values(positions);
  const bounds = points.length
    ? {
      left: Math.min(...points.map((point) => point.x)),
      top: Math.min(...points.map((point) => point.y)),
      right: Math.max(...points.map((point) => point.x)),
      bottom: Math.max(...points.map((point) => point.y)),
    }
    : { left: 0, top: 0, right: 0, bottom: 0 };

  const levels: DependencyTreeLevel[] = [...levelCounts.keys()].sort((a, b) => a - b).map((depth) => ({
    depth, y: depth * LEVEL_GAP, count: levelCounts.get(depth)!,
    label: depth === 0 ? "导入源" : `第 ${depth} 层`,
  }));

  const maxShown = levels.length ? levels[levels.length - 1].depth : -1;
  return {
    positions, levels, bands, bounds,
    hidden,
    visible: visible.size,
    hasDeeper: tree.stats.maxDepth > maxShown && hidden > 0,
  };
}
