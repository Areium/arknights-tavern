import type { WorldBookCategoryDTO } from "../types";

export function categoryDescendants(categories: WorldBookCategoryDTO[], id: string): Set<string> {
  const result = new Set([id]);
  const queue = [id];
  for (let i = 0; i < queue.length; i++) {
    for (const category of categories) {
      if (category.parent_id === queue[i] && !result.has(category.id)) {
        result.add(category.id);
        queue.push(category.id);
      }
    }
  }
  return result;
}

export function flattenCategoryTree(categories: WorldBookCategoryDTO[]) {
  const children = new Map<string | null, WorldBookCategoryDTO[]>();
  for (const category of categories) {
    const key = category.parent_id || null;
    children.set(key, [...(children.get(key) || []), category]);
  }
  for (const list of children.values()) list.sort((a, b) => a.sort_order - b.sort_order || a.id.localeCompare(b.id));
  const stack = (children.get(null) || []).map((category) => ({ category, level: 0 })).reverse();
  const result: Array<{ category: WorldBookCategoryDTO; level: number }> = [];
  const seen = new Set<string>();
  while (stack.length) {
    const row = stack.pop()!;
    if (seen.has(row.category.id)) continue;
    seen.add(row.category.id);
    result.push(row);
    stack.push(...(children.get(row.category.id) || []).map((category) => ({ category, level: row.level + 1 })).reverse());
  }
  return result;
}
