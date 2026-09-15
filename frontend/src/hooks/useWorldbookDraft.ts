import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useApi } from "./useApi";
import type {
  WorldBookCategoryDTO, WorldBookConfigurationDraft, WorldBookDetail,
  WorldBookDependencyEdgeDTO, WorldBookPolicyDraft, WorldBookRootDTO,
  WorldBookScopePreviewDTO,
} from "../types";

/**
 * 统一草稿：分类、角色关联、起点规则、依赖边与 AI 建议**共用同一份草稿**，
 * 走同一条校验/预览/撤销/保存路径，并由 `PUT /configuration` 一次原子写入。
 *
 * 这不是「把多次旧保存请求串起来」——只有一个 draft 对象、一次提交；
 * 保存失败或版本冲突（409）时草稿原样保留，不会因为重新加载而丢失。
 */
export interface WorldBookDraft {
  categories: WorldBookCategoryDTO[];
  entry_moves: Record<string, string>;
  entry_updates: Record<string, { category_id?: string; character_id?: string }>;
  scope_mode: "legacy" | "selective";
  roots: WorldBookRootDTO[];
  requires_edges: WorldBookDependencyEdgeDTO[];
  related_edges: WorldBookDependencyEdgeDTO[];
  /** AI 构建结果：与手写草稿在同一次写入中生效，应用后清空 */
  proposal: WorldBookConfigurationDraft["proposal"];
}

/**
 * 旧格式（v2）等价映射：固定导入 → always + none，导入源 → always + legacy_depth。
 * 只有用户显式预览并保存后，这本书才会真正改用 v3 按需规则；映射本身不写盘。
 */
export const rootsFromV2 = (detail: WorldBookDetail): WorldBookRootDTO[] => [
  ...(detail.import_config?.fixed_entry_uids || []).map((uid) => ({
    entry_uid: uid, activation: "always" as const, expansion: "none" as const,
  })),
  ...(detail.import_config?.dependency_sources || []).map((item) => ({
    entry_uid: item.entry_uid, activation: "always" as const,
    expansion: "legacy_depth" as const, max_depth: item.max_depth,
  })),
];

export const draftFrom = (detail: WorldBookDetail): WorldBookDraft => ({
  categories: detail.categories ? [...detail.categories] : [],
  entry_moves: {},
  entry_updates: {},
  scope_mode: detail.scope_mode || "legacy",
  // v3 书直接读规则；v2 书按等价映射把旧 fixed / sources 呈现为 always 起点
  roots: detail.dependency_rules?.roots
    ? detail.dependency_rules.roots.map((root) => ({ ...root }))
    : rootsFromV2(detail),
  requires_edges: detail.dependency_edges ? [...detail.dependency_edges] : [],
  related_edges: detail.related_edges ? [...detail.related_edges] : [],
  proposal: null,
});

/** 高级图谱用的 v2 形态视图：由统一草稿投影而来，不引入第二份草稿。 */
export const policyFromDraft = (draft: WorldBookDraft): WorldBookPolicyDraft => ({
  fixed_entry_uids: draft.roots.filter((root) => root.activation === "always" && root.expansion === "none")
    .map((root) => root.entry_uid),
  dependency_sources: draft.roots.filter((root) => root.expansion === "legacy_depth")
    .map((root) => ({ entry_uid: root.entry_uid, max_depth: root.max_depth ?? 1 })),
  dependency_edges: draft.requires_edges,
  scope_mode: draft.scope_mode,
});

/**
 * 反向投影：高级图谱按 v2 形态改动后写回统一草稿。
 *
 * 关键点：只替换「always + none」与「legacy_depth」这两类起点，
 * AI 生成的条件起点（roster_any / manual / requires_closure）原样保留，
 * 不会因为用高级视图改一条边就被静默清掉。
 */
export const patchFromPolicy = (
  policy: WorldBookPolicyDraft, draft: WorldBookDraft,
): Partial<WorldBookDraft> => ({
  roots: [
    ...draft.roots.filter((root) => !(root.activation === "always"
      && (root.expansion === "none" || root.expansion === "legacy_depth"))),
    ...policy.fixed_entry_uids.map((uid) => ({
      entry_uid: uid, activation: "always" as const, expansion: "none" as const,
    })),
    ...policy.dependency_sources.map((item) => ({
      entry_uid: item.entry_uid, activation: "always" as const,
      expansion: "legacy_depth" as const, max_depth: item.max_depth,
    })),
  ],
  requires_edges: policy.dependency_edges,
  scope_mode: policy.scope_mode,
});

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

export function useWorldbookDraft(detail: WorldBookDetail | null) {
  const api = useApi();
  const [draft, setDraft] = useState<WorldBookDraft | null>(() => (detail ? draftFrom(detail) : null));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [savedAt, setSavedAt] = useState(0);

  const baseline = useMemo(() => (detail ? draftFrom(detail) : null), [detail]);
  // 只有换书或保存成功后重新加载才重置草稿；切换视图、切 Tab 都不会丢。
  const bookId = detail?.id || "";
  const revision = detail?.import_config?.revision ?? 0;
  useEffect(() => { setDraft(detail ? draftFrom(detail) : null); setError(""); setConflict(false); },
    [bookId, revision]);

  const dirty = !!draft && !!baseline && !same(draft, baseline);

  const patch = useCallback((changes: Partial<WorldBookDraft>) => {
    setDraft((current) => (current ? { ...current, ...changes } : current));
  }, []);

  /** 撤销：回到服务端已保存的版本（不是回到上一次编辑）。 */
  const undo = useCallback(() => {
    setDraft(baseline ? { ...baseline } : null);
    setError("");
    setConflict(false);
  }, [baseline]);

  const save = useCallback(async (): Promise<boolean> => {
    if (!detail || !draft || saving) return false;
    setSaving(true); setError(""); setConflict(false);
    try {
      await api.putWorldbookConfiguration(detail.id, {
        ...draft,
        expected_revision: detail.import_config?.revision,
      });
      setSavedAt(Date.now());
      return true;
    } catch (e) {
      const message = e instanceof Error ? e.message : "保存失败";
      // 冲突与失败都保留草稿：用户可以重新加载对照，或改完再存。
      if (/409|已变更/.test(message)) setConflict(true);
      setError(message);
      return false;
    } finally {
      setSaving(false);
    }
  }, [api, detail, draft, saving]);

  return { draft, setDraft, patch, dirty, saving, error, conflict, savedAt, save, undo, baseline };
}

/** 预览：防抖 + 过时请求保护（只接受最后一次发出的响应）。 */
export function useScopePreview(
  bookId: string, detailUpdatedAt: number | undefined,
  draft: WorldBookDraft | null, roster: string[], manual: string[], enabled = true,
) {
  const api = useApi();
  const [preview, setPreview] = useState<WorldBookScopePreviewDTO | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);

  useEffect(() => {
    if (!enabled || !bookId || !draft) { setPreview(null); return; }
    const seq = ++sequence.current;
    setLoading(true);
    const timer = setTimeout(() => {
      api.previewWorldbookScope(bookId, roster, {
        roots: draft.roots,
        requires_edges: draft.requires_edges,
        related_edges: draft.related_edges,
        scope_mode: draft.scope_mode,
        entry_updates: draft.entry_updates,
        entry_moves: draft.entry_moves,
        categories: draft.categories,
        // 尚未保存的 AI 建议也参与预览：预览就是「保存后会长成什么样」
        proposal: draft.proposal,
      } as WorldBookConfigurationDraft, { manual_entry_uids: manual })
        .then((value) => { if (seq === sequence.current) { setPreview(value); setError(""); } })
        .catch((e) => {
          if (seq !== sequence.current) return;   // 过时响应直接丢弃
          setPreview(null);
          setError(e instanceof Error ? e.message : "预览失败");
        })
        .finally(() => { if (seq === sequence.current) setLoading(false); });
    }, 180);
    return () => { clearTimeout(timer); };
  }, [api, bookId, detailUpdatedAt, draft, roster, manual, enabled]);

  return { preview, loading, error };
}

/**
 * 会话向导用的预览：只有阵容 + 手动追加 + 是否全量兼容，没有草稿。
 * 与 `useScopePreview` 共用同一套防抖与过时响应保护，避免用户连续勾选时
 * 旧响应后到把新结果覆盖掉。
 */
export function useRosterScopePreview(
  bookId: string, roster: string[], manual: string[], fullScope: boolean, enabled = true,
) {
  const api = useApi();
  const [preview, setPreview] = useState<WorldBookScopePreviewDTO | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  const manualKey = manual.join("\u0000");
  const rosterKey = roster.join("\u0000");

  useEffect(() => {
    if (!enabled || !bookId) { setPreview(null); setError(""); return; }
    const seq = ++sequence.current;
    setLoading(true);
    const timer = setTimeout(() => {
      api.previewWorldbookScope(bookId, rosterKey ? rosterKey.split("\u0000") : [], undefined,
        { manual_entry_uids: manualKey ? manualKey.split("\u0000") : [], full_scope: fullScope })
        .then((value) => { if (seq === sequence.current) { setPreview(value); setError(""); } })
        .catch((e) => {
          if (seq !== sequence.current) return;   // 过时响应直接丢弃
          setPreview(null);
          setError(e instanceof Error ? e.message : "候选范围预览失败");
        })
        .finally(() => { if (seq === sequence.current) setLoading(false); });
    }, 180);
    return () => { clearTimeout(timer); };
  }, [api, bookId, rosterKey, manualKey, fullScope, enabled]);

  return { preview, loading, error };
}
