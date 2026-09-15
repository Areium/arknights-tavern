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
  /** 人工拒绝过的建议：再次应用同一份 AI 结果时不得复活 */
  rejected: WorldBookDependencyEdgeDTO[];
  /** AI 构建结果：与手写草稿在同一次写入中生效，应用后清空 */
  proposal: WorldBookConfigurationDraft["proposal"];
  /**
   * 是否显式改用 v3 按需载入规则。
   *
   * v2 书默认 false：改分类 / 改角色关联**不会**顺手把书切成按需载入
   * （预装书 fixed/sources 都是空的，隐式启用会把候选清成空集）。
   * 只有用户点「启用按需载入」才置为 true，并且保存前会用预览展示迁移结果。
   */
  adopt_v3: boolean;
}

/**
 * 旧格式（v2）等价映射：固定导入 → always + none，导入源 → always + legacy_depth。
 *
 * 这里**只**映射 v2 自己表达过的两类来源，用来在高级图谱里呈现/编辑旧策略；
 * 世界观与角色分类的等价映射由服务端 `equivalent_v3_rules()` 在显式迁移时补齐，
 * 前端不再自己造一份（否则两边口径容易漂移）。
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
  rejected: (detail.dependency_rules?.rejected || []).map((edge) => ({ ...edge })),
  proposal: null,
  adopt_v3: !!detail.dependency_rules?.roots,
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

  /**
   * 显式改用按需载入（v3）。
   *
   * 这是一个**独立的、可撤销的**动作：只把开关打上，真正的迁移映射由服务端在
   * 预览与保存时按同一套 `equivalent_v3_rules()` 计算，因此预览就是保存后的样子。
   */
  const adoptV3 = useCallback(() => {
    setDraft((current) => (current ? { ...current, adopt_v3: true } : current));
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
        ...buildSaveBody(draft, baseline),
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
  }, [api, detail, draft, saving, baseline]);

  return { draft, setDraft, patch, adoptV3, dirty, saving, error, conflict, savedAt, save, undo, baseline };
}

/**
 * 组装保存请求体 —— 这里决定「哪些改动会真的写进这本书」。
 *
 * 关键规则（审核反证 P1-3）：**v2 书的普通编辑不能顺手改变载入范围**。
 * 旧实现无条件把草稿里的 `roots` 一起发出去，服务端据此把书切到按需载入，
 * 而预装书的 fixed/sources 都是空的 → 保存一次候选就被清成空集。
 * 现在只有两种情况下才提交策略字段：
 *   1. 用户显式选择改用按需载入（`adopt_v3`）；
 *   2. 用户真的动过对应的策略字段（与已保存版本逐项比对）。
 */
export const buildSaveBody = (
  draft: WorldBookDraft, baseline: WorldBookDraft | null,
): WorldBookConfigurationDraft => {
  const body: WorldBookConfigurationDraft = {
    adopt_v3: draft.adopt_v3,
    categories: draft.categories,
    entry_moves: draft.entry_moves,
    entry_updates: draft.entry_updates,
    scope_mode: draft.scope_mode,
  };
  if (draft.adopt_v3) {
    body.roots = draft.roots;
    body.requires_edges = draft.requires_edges;
    body.related_edges = draft.related_edges;
  } else {
    if (!same(draft.roots, baseline?.roots)) body.roots = draft.roots;
    if (!same(draft.requires_edges, baseline?.requires_edges)) body.requires_edges = draft.requires_edges;
    if (!same(draft.related_edges, baseline?.related_edges)) body.related_edges = draft.related_edges;
  }
  if (draft.rejected.length) body.rejected = draft.rejected;
  if (draft.proposal) body.proposal = draft.proposal;
  return body;
};

/**
 * 预览：防抖 + 过时请求保护（只接受最后一次发出的响应）。
 *
 * 依赖项刻意用**语义键**（序列化后的请求体 + 用分隔符拼起来的阵容/手动追加），
 * 而不是数组 / 对象的引用：审核反证 P2-15 —— 调用方每次渲染都传一个新的 `[]`，
 * 旧实现把它当依赖，于是 `setPreview` 触发重渲染 → 又发一次请求，
 * 空闲时形成 180ms 一次的请求循环。
 */
export function useScopePreview(
  bookId: string, detailUpdatedAt: number | undefined,
  draft: WorldBookDraft | null, roster: string[], manual: string[], enabled = true,
) {
  const api = useApi();
  const [preview, setPreview] = useState<WorldBookScopePreviewDTO | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);

  // 预览用完整草稿（baseline=null）：看到的就是「按这份草稿保存后」的结果。
  const body = useMemo(() => (draft ? buildSaveBody(draft, null) : null), [draft]);
  const bodyKey = body ? JSON.stringify(body) : "";
  const rosterKey = roster.join("\u0000");
  const manualKey = manual.join("\u0000");
  // 请求体用 ref 取最新值：依赖项只认语义键，避免「内容没变但引用变了」重发请求。
  const bodyRef = useRef<WorldBookConfigurationDraft | null>(null);
  bodyRef.current = body;

  useEffect(() => {
    const seq = ++sequence.current;
    if (!enabled || !bookId || !bodyKey) { setPreview(null); setLoading(false); return; }
    setLoading(true);
    const timer = setTimeout(() => {
      api.previewWorldbookScope(bookId, rosterKey ? rosterKey.split("\u0000") : [],
        bodyRef.current as WorldBookConfigurationDraft,
        { manual_entry_uids: manualKey ? manualKey.split("\u0000") : [] })
        .then((value) => { if (seq === sequence.current) { setPreview(value); setError(""); } })
        .catch((e) => {
          if (seq !== sequence.current) return;   // 过时响应直接丢弃
          setPreview(null);
          setError(e instanceof Error ? e.message : "预览失败");
        })
        .finally(() => { if (seq === sequence.current) setLoading(false); });
    }, 180);
    return () => { clearTimeout(timer); sequence.current++; };
  }, [api, bookId, detailUpdatedAt, bodyKey, rosterKey, manualKey, enabled]);

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
    const seq = ++sequence.current;
    if (!enabled || !bookId) { setPreview(null); setLoading(false); setError(""); return; }
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
    return () => { clearTimeout(timer); sequence.current++; };
  }, [api, bookId, rosterKey, manualKey, fullScope, enabled]);

  return { preview, loading, error };
}
