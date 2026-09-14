/**
 * 世界书节点的批量操作：全部是对导入策略草稿的纯函数变换，不写盘、不改书。
 *
 * 调用方（WorldBookScopeManager）拿到新草稿后照常走「保存策略」，
 * 因此批量操作与单点编辑共用同一条校验 / 修订号路径。
 */
import type { WorldBookDetail, WorldBookPolicyDraft } from "../types";
import type { GraphPoint, WorldBookGraphNode } from "./worldbookGraph";
import { categoryDescendants } from "./worldbookScope";

export type EdgeDraft = WorldBookPolicyDraft["dependency_edges"][number];
export type BatchRect = { left: number; top: number; right: number; bottom: number };

const edgeKey = (from: string, to: string) => JSON.stringify([from, to]);

/** 分类（含子分类）下的全部条目 UID；`unclassified` 同样适用。 */
export function categoryEntryUids(detail: WorldBookDetail, categoryId: string): string[] {
  if (!categoryId) return [];
  const scope = categoryDescendants(detail.categories || [], categoryId);
  return (detail.entries || [])
    .filter((entry) => scope.has(entry.category_id || "unclassified"))
    .map((entry) => entry.uid);
}

/** 只保留书中真实存在的条目，并去掉重复与空值。 */
export function knownUids(detail: WorldBookDetail, uids: string[]): string[] {
  const known = new Set((detail.entries || []).map((entry) => entry.uid));
  return [...new Set(uids.filter((uid) => typeof uid === "string" && known.has(uid)))];
}

/** 框选：中心点落在矩形内的条目节点。 */
export function pickedInRect(
  nodes: WorldBookGraphNode[],
  positions: Record<string, GraphPoint>,
  rect: BatchRect,
): string[] {
  const left = Math.min(rect.left, rect.right), right = Math.max(rect.left, rect.right);
  const top = Math.min(rect.top, rect.bottom), bottom = Math.max(rect.top, rect.bottom);
  return nodes
    .filter((node) => node.kind === "entry" && positions[node.id])
    .filter((node) => {
      const point = positions[node.id];
      return point.x >= left && point.x <= right && point.y >= top && point.y <= bottom;
    })
    .map((node) => node.refId);
}

export function batchFixed(policy: WorldBookPolicyDraft, detail: WorldBookDetail, uids: string[], on: boolean): WorldBookPolicyDraft {
  const targets = knownUids(detail, uids);
  if (!targets.length) return policy;
  if (!on) {
    const drop = new Set(targets);
    return { ...policy, fixed_entry_uids: policy.fixed_entry_uids.filter((uid) => !drop.has(uid)) };
  }
  const existing = new Set(policy.fixed_entry_uids);
  const added = targets.filter((uid) => !existing.has(uid));
  return added.length ? { ...policy, fixed_entry_uids: [...policy.fixed_entry_uids, ...added] } : policy;
}

/** 批量设为 / 取消导入源；maxDepth 为 null 表示取消。 */
export function batchSource(policy: WorldBookPolicyDraft, detail: WorldBookDetail, uids: string[], maxDepth: number | null): WorldBookPolicyDraft {
  const targets = knownUids(detail, uids);
  if (!targets.length) return policy;
  const drop = new Set(targets);
  const rest = policy.dependency_sources.filter((item) => !drop.has(item.entry_uid));
  if (maxDepth === null) {
    return rest.length === policy.dependency_sources.length ? policy : { ...policy, dependency_sources: rest };
  }
  const depth = Math.max(0, Math.min(32, Math.floor(maxDepth)));
  const next = [...rest, ...targets.map((uid) => ({ entry_uid: uid, max_depth: depth }))];
  // 顺序按 UID 稳定，避免每次批量操作都产生无意义的草稿差异。
  next.sort((a, b) => a.entry_uid.localeCompare(b.entry_uid));
  return { ...policy, dependency_sources: next };
}

/** 批量建立有向依赖：direction=to 表示 uids → target，from 表示 target → uids。 */
export function batchAddEdges(policy: WorldBookPolicyDraft, detail: WorldBookDetail, uids: string[], target: string, direction: "to" | "from"):
  { policy: WorldBookPolicyDraft; added: EdgeDraft[]; skipped: number } {
  const target_uid = typeof target === "string" ? target.trim() : "";
  const known = new Set((detail.entries || []).map((entry) => entry.uid));
  if (!known.has(target_uid)) return { policy, added: [], skipped: 0 };
  const existing = new Set(policy.dependency_edges.map((edge) => edgeKey(edge.from_uid, edge.to_uid)));
  const added: EdgeDraft[] = [];
  let skipped = 0;
  for (const uid of knownUids(detail, uids)) {
    if (uid === target_uid) { skipped++; continue; }   // 自环由后端拒绝，这里直接跳过
    const edge = direction === "to" ? { from_uid: uid, to_uid: target_uid } : { from_uid: target_uid, to_uid: uid };
    const key = edgeKey(edge.from_uid, edge.to_uid);
    if (existing.has(key)) { skipped++; continue; }
    existing.add(key);
    added.push(edge);
  }
  return added.length ? { policy: { ...policy, dependency_edges: [...policy.dependency_edges, ...added] }, added, skipped }
    : { policy, added, skipped };
}

/** 批量清除依赖边：删除所有一端落在 uids 里的边。 */
export function batchRemoveEdges(policy: WorldBookPolicyDraft, detail: WorldBookDetail, uids: string[]):
  { policy: WorldBookPolicyDraft; removed: number } {
  const drop = new Set(knownUids(detail, uids));
  if (!drop.size) return { policy, removed: 0 };
  const kept = policy.dependency_edges.filter((edge) => !drop.has(edge.from_uid) && !drop.has(edge.to_uid));
  const removed = policy.dependency_edges.length - kept.length;
  return removed ? { policy: { ...policy, dependency_edges: kept }, removed } : { policy, removed: 0 };
}

/** 批量移入分类：产出 taxonomy 接口需要的 entry_moves。 */
export function batchMove(detail: WorldBookDetail, uids: string[], categoryId: string): Record<string, string> {
  const known = new Set((detail.categories || []).map((category) => category.id));
  if (!categoryId || !known.has(categoryId)) return {};
  const moves: Record<string, string> = {};
  for (const uid of knownUids(detail, uids)) moves[uid] = categoryId;
  return moves;
}
