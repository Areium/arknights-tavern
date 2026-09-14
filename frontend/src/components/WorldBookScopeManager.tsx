import { Fragment, useEffect, useId, useMemo, useState } from "react";
import { useApi } from "../hooks/useApi";
import { useAppStore } from "../stores/appStore";
import type { WorldBookCategoryDTO, WorldBookClassificationDTO, WorldBookDetail, WorldBookEntryDTO, WorldBookPolicyDraft, WorldBookScopePreviewDTO } from "../types";
import { categoryDescendants, flattenCategoryTree } from "../utils/worldbookScope";
import { buildWorldBookGraph, categoryNodeId, dependencyEdgeId, entryNodeId, type WorldBookGraphView, type WorldBookGraphNode } from "../utils/worldbookGraph";
import {
  DEPENDENCY_ROLES, ROLE_GLYPHS, ROLE_HINTS, ROLE_LABELS, defaultTreeDepthLimit, dependencyDescendants, dependencyPath,
  type DependencyRole,
} from "../utils/worldbookDependency";
import WorldBookGraphCanvas, { type GraphColoring } from "./WorldBookGraphCanvas";
import {
  batchAddEdges, batchFixed, batchMove, batchRemoveEdges, batchSource, categoryEntryUids, knownUids,
} from "../utils/worldbookBatch";
import WorldBookGraphIcon from "./WorldBookGraphIcon";
import WorldBookScopePreview from "./WorldBookScopePreview";
import "../styles/worldbook-graph.css";

const KINDS = { worldview: "世界观", character: "角色", other: "其他" };
/** 自动分类的线索名 → 界面文案（与后端 worldbook_classify 的信号名对应）。 */
const SIGNALS: Record<string, string> = { "uid-prefix": "uid 前缀", group: "group 字段", "name-suffix": "名称后缀" };
const classificationName = (value: WorldBookClassificationDTO, id: string) =>
  value.categories.find((category) => category.id === id)?.name
  || value.proposal.find((category) => category.id === id)?.name || id;
const MIME = "application/x-worldbook-entry";
const policyFrom = (detail: WorldBookDetail): WorldBookPolicyDraft => ({
  fixed_entry_uids: detail.import_config?.fixed_entry_uids || [],
  dependency_sources: detail.import_config?.dependency_sources || [],
  dependency_edges: detail.dependency_edges || [],
  scope_mode: detail.scope_mode || "legacy",
});

export default function WorldBookScopeManager({ detail, onChanged, view = "dependencies", onCategoryChange, onEditEntry, onDirtyChange }: {
  detail: WorldBookDetail;
  onChanged: () => void | Promise<void>;
  view?: WorldBookGraphView;
  onCategoryChange?: (id: string) => void;
  onEditEntry?: (entry: WorldBookEntryDTO) => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const api = useApi();
  const store = useAppStore();
  const controlId = useId();
  const [policy, setPolicy] = useState(() => policyFrom(detail));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [selection, setSelection] = useState<{ kind: "entry" | "category"; id: string } | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [categoryDraft, setCategoryDraft] = useState<WorldBookCategoryDTO | null>(null);
  const [deleteTarget, setDeleteTarget] = useState("unclassified");
  const [assignment, setAssignment] = useState({ category_id: "unclassified", character_id: "" });
  const [characters, setCharacters] = useState<Array<{ id: string; name?: string; title?: string }> | null>(null);
  const [edgeTo, setEdgeTo] = useState("");
  const [linkFrom, setLinkFrom] = useState<string[] | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [batchDepth, setBatchDepth] = useState(1);
  const [batchTarget, setBatchTarget] = useState("");
  const [batchCategory, setBatchCategory] = useState("unclassified");
  const [rowMenu, setRowMenu] = useState<string | null>(null);
  const [batchNote, setBatchNote] = useState("");
  const [depth, setDepth] = useState(1);
  const [roster, setRoster] = useState<string[]>([]);
  const [preview, setPreview] = useState<WorldBookScopePreviewDTO | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [libraryOpen, setLibraryOpen] = useState(true);
  const [panel, setPanel] = useState<"inspector" | "preview" | "classify" | null>(null);
  const [connectedOnly, setConnectedOnly] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [dropActive, setDropActive] = useState(false);
  const [coloring, setColoring] = useState<GraphColoring>("role");
  const [roleFilter, setRoleFilter] = useState<DependencyRole[]>([]);
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [treeDepth, setTreeDepth] = useState<number | null>(null);
  const [showLoose, setShowLoose] = useState(false);
  const [classification, setClassification] = useState<WorldBookClassificationDTO | null>(null);
  const [classifyError, setClassifyError] = useState("");

  const categories = detail.categories || [];
  const rows = useMemo(() => flattenCategoryTree(categories), [categories]);
  const byUid = useMemo(() => new Map(detail.entries.map((entry) => [entry.uid, entry])), [detail.entries]);
  const focusedUid = selection?.kind === "entry" ? selection.id : "";
  const focused = byUid.get(focusedUid);
  const selectedId = selection ? selection.kind === "entry" ? entryNodeId(selection.id) : categoryNodeId(selection.id) : null;
  const dirty = JSON.stringify(policy) !== JSON.stringify(policyFrom(detail));
  const fixed = new Set(policy.fixed_entry_uids);
  const source = policy.dependency_sources.find((item) => item.entry_uid === focusedUid);
  const selectedRelation = policy.dependency_edges.find((edge) => dependencyEdgeId(edge.from_uid, edge.to_uid) === selectedEdge);
  const label = (uid: string) => byUid.get(uid)?.name || uid;
  const selectedCategories = useMemo(() => categoryId ? categoryDescendants(categories, categoryId) : null, [categories, categoryId]);
  const isDependency = view !== "taxonomy";
  const treeView = view === "tree";
  const graph = useMemo(() => buildWorldBookGraph(detail, policy, {
    view, categoryId, query, connectedOnly: isDependency && connectedOnly, focusedUid,
    roles: isDependency && roleFilter.length ? roleFilter : undefined,
  }), [detail, policy, view, categoryId, query, connectedOnly, focusedUid, roleFilter, isDependency]);
  const model = graph.tree;
  const role = focused ? model?.roles.get(focused.uid) || "orphan" : null;
  const pickedSet = useMemo(() => new Set(picked), [picked]);
  const treeNode = focused ? model?.byUid.get(focused.uid) : undefined;
  const treeDepthLimit = treeDepth ?? (model ? defaultTreeDepthLimit(model) : 0);
  const treeOptions = useMemo(() => (treeView && model
    ? { depthLimit: treeDepthLimit, collapsed, showLoose }
    : null), [treeView, model, treeDepthLimit, collapsed, showLoose]);
  const toggleRole = (value: DependencyRole) => setRoleFilter((current) =>
    current.includes(value) ? current.filter((item) => item !== value) : [...current, value]);
  const toggleCollapse = (uid: string) => setCollapsed((current) => {
    const next = new Set(current);
    if (next.has(uid)) next.delete(uid); else next.add(uid);
    return next;
  });
  const filtered = detail.entries.filter((entry) =>
    (!selectedCategories || selectedCategories.has(entry.category_id || "unclassified")) &&
    // 角色筛选只属于依赖视图；切回分类结构时不参与过滤，也不会把目录清空。
    (!isDependency || !roleFilter.length || roleFilter.includes(model?.roles.get(entry.uid) || "orphan")) &&
    (!query.trim() || [entry.name, entry.uid, entry.character_id, categories.find((category) => category.id === entry.category_id)?.name,
      ...(entry.trigger_keys || [])].join(" ").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())));
  const editingDescendants = categoryDraft ? categoryDescendants(categories, categoryDraft.id) : new Set<string>();
  const assignmentKind = categories.find((category) => category.id === assignment.category_id)?.scope_type;

  useEffect(() => { setPolicy(policyFrom(detail)); }, [detail]);
  useEffect(() => {
    setCategoryId(""); setSelection(null); setCategoryDraft(null); setError("");
    setRoster([]); setEdgeTo(""); setLinkFrom(null); setPanel(null); setSelectedEdge(null);
    setQuery(""); setConnectedOnly(false); setRoleFilter([]); setCollapsed(new Set()); setTreeDepth(null); setShowLoose(false);
    setClassification(null); setClassifyError("");
    setPicked([]); setBatchNote(""); setLinkFrom(null); setRowMenu(null); setBatchTarget("");
  }, [detail.id]);
  useEffect(() => {
    setSelection(null); setSelectedEdge(null); setCategoryDraft(null); setLinkFrom(null); setPanel(null);
    setCollapsed(new Set()); setTreeDepth(null); setRowMenu(null); setBatchNote("");
    setColoring(view === "taxonomy" ? "kind" : "role");
  }, [view]);
  useEffect(() => {
    setAssignment({ category_id: focused?.category_id || "unclassified", character_id: focused?.character_id || "" });
    setEdgeTo(""); setDepth(1);
  }, [focused]);
  // 书重新加载后（条目被删/被改动），把批量选择与批量目标里的陈旧 UID 清掉。
  useEffect(() => {
    setPicked((current) => {
      const next = current.filter((uid) => byUid.has(uid));
      return next.length === current.length ? current : next;
    });
    setBatchTarget((current) => (current && !byUid.has(current) ? "" : current));
  }, [byUid]);
  // 分类行菜单：点空白处或 Esc 关闭，避免菜单一直挂在目录上。
  useEffect(() => {
    if (!rowMenu) return;
    const close = (event: MouseEvent) => {
      if (!(event.target as Element).closest(".wbg-tree-row")) setRowMenu(null);
    };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setRowMenu(null); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", escape); };
  }, [rowMenu]);
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const prevent = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", prevent);
    return () => window.removeEventListener("beforeunload", prevent);
  }, [dirty]);
  useEffect(() => {
    let cancelled = false;
    api.getCharacters().then((items) => { if (!cancelled) setCharacters(items || []); })
      .catch(() => { if (!cancelled) setCharacters(null); });
    return () => { cancelled = true; };
  }, [api]);
  useEffect(() => {
    if (!isDependency) return;
    let cancelled = false;
    setPreview(null); setPreviewError("");
    const timer = setTimeout(() => {
      api.previewWorldbookScope(detail.id, roster, policy)
        .then((value) => { if (!cancelled) setPreview(value); })
        .catch((e) => { if (!cancelled) setPreviewError(e.message || "预览失败"); });
    }, 180);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [api, detail.id, detail.updated_at, roster, policy, view]);

  const run = async (action: () => Promise<unknown>, savingPolicy = false) => {
    if (busy) return false;
    if (!savingPolicy && dirty && !window.confirm("此操作会重新加载配置并丢弃未保存的导入策略，继续吗？")) return false;
    setBusy(true); setError("");
    try { await action(); await onChanged(); return true; }
    catch (e) { setError(e instanceof Error ? e.message : "操作失败"); return false; }
    finally { setBusy(false); }
  };
  const filterCategory = (id: string) => { setCategoryId(id); onCategoryChange?.(id); };
  const dragUid = (event: React.DragEvent) => {
    if (busy) return "";
    try {
      const data = JSON.parse(event.dataTransfer.getData(MIME));
      return data.book_id === detail.id && byUid.has(data.uid) ? data.uid as string : "";
    } catch { return ""; }
  };
  const addFixed = (uid: string) => {
    if (busy || !byUid.has(uid) || fixed.has(uid)) return;
    setPolicy((current) => ({ ...current, fixed_entry_uids: [...current.fixed_entry_uids, uid] }));
  };
  const removeFixed = (uid: string) => setPolicy((current) => ({ ...current, fixed_entry_uids: current.fixed_entry_uids.filter((id) => id !== uid) }));
  const setSource = (uid: string, maxDepth: number | null) => {
    setPolicy((current) => ({ ...current, dependency_sources: [
      ...current.dependency_sources.filter((item) => item.entry_uid !== uid),
      ...(maxDepth === null ? [] : [{ entry_uid: uid, max_depth: maxDepth }]),
    ] }));
  };
  const addEdge = (from: string, to: string) => {
    if (busy || !byUid.has(from) || !byUid.has(to)) return false;
    if (from === to) { setError("不能让条目依赖自身，请选择另一个节点。"); return false; }
    if (policy.dependency_edges.some((edge) => edge.from_uid === from && edge.to_uid === to)) {
      setError("这条依赖已经存在。"); return false;
    }
    setError("");
    setPolicy((current) => ({ ...current, dependency_edges: [...current.dependency_edges, { from_uid: from, to_uid: to }] }));
    setLinkFrom(null); setEdgeTo("");
    return true;
  };
  /** 批量连线：为整批来源（或整批目标）一次建立依赖，重复与自环直接跳过。 */
  const addEdgesFrom = (fromUids: string[], to: string) => {
    if (busy || !byUid.has(to)) return;
    const { policy: next, added, skipped } = batchAddEdges(policy, detail, fromUids, to, "to");
    if (!added.length) { setError(`没有新增依赖：${skipped} 条已存在或指向自身。`); }
    else { setError(""); setPolicy(next); }
    setBatchNote(added.length ? `已为 ${added.length} 个条目建立依赖${skipped ? `，跳过 ${skipped} 条（已存在或自环）` : ""}。` : "");
    setLinkFrom(null); setEdgeTo("");
  };
  const removeEdge = (from: string, to: string) => {
    setPolicy((current) => ({ ...current, dependency_edges: current.dependency_edges.filter((edge) => edge.from_uid !== from || edge.to_uid !== to) }));
    setSelectedEdge(null);
  };
  const inspectEntry = (uid: string) => {
    setSelection({ kind: "entry", id: uid }); setSelectedEdge(null); setCategoryDraft(null); setPanel("inspector");
  };
  const inspectCategory = (id: string) => {
    const category = categories.find((item) => item.id === id);
    setSelection({ kind: "category", id }); setSelectedEdge(null); setPanel("inspector");
    setCategoryDraft(category && category.id !== "unclassified" ? { ...category } : null);
    setDeleteTarget("unclassified");
    setRowMenu(null);
  };
  const selectNode = (node: WorldBookGraphNode, additive = false) => {
    if (linkFrom) {
      if (node.kind !== "entry") { setError("依赖的目标必须是条目节点，分类只用于组织条目。"); return; }
      addEdgesFrom(linkFrom, node.refId);
      return;
    }
    if (additive && node.kind === "entry") {
      // Ctrl / Shift 点击：只增删批量选择，不抢走属性栏的主选择。
      setPicked((current) => current.includes(node.refId)
        ? current.filter((uid) => uid !== node.refId) : [...current, node.refId]);
      setBatchNote("");
      return;
    }
    if (node.kind === "entry") inspectEntry(node.refId);
    else inspectCategory(node.refId);
  };
  const pickMany = (uids: string[], additive: boolean) => {
    setBatchNote("");
    setPicked((current) => (additive ? [...new Set([...current, ...knownUids(detail, uids)])] : knownUids(detail, uids)));
  };
  const pickCategory = (categoryId: string) => {
    const uids = categoryEntryUids(detail, categoryId);
    setPicked(uids); setBatchNote(`已选中「${categoryName(categoryId)}」下的 ${uids.length} 个条目。`);
    setRowMenu(null);
  };
  const categoryName = (categoryId: string) => categories.find((category) => category.id === categoryId)?.name || categoryId;
  /** 整类设为导入源 / 固定导入：一次改动整棵子树下的条目。 */
  const sourceCategory = (categoryId: string) => {
    const uids = categoryEntryUids(detail, categoryId);
    if (!uids.length) { setBatchNote(`「${categoryName(categoryId)}」下没有条目。`); setRowMenu(null); return; }
    setPolicy(batchSource(policy, detail, uids, batchDepth));
    setBatchNote(`已将「${categoryName(categoryId)}」下的 ${uids.length} 个条目设为导入源（深度 ${batchDepth}）。`);
    setRowMenu(null);
  };
  const fixedCategory = (categoryId: string) => {
    const uids = categoryEntryUids(detail, categoryId);
    if (!uids.length) { setBatchNote(`「${categoryName(categoryId)}」下没有条目。`); setRowMenu(null); return; }
    setPolicy(batchFixed(policy, detail, uids, true));
    setBatchNote(`已将「${categoryName(categoryId)}」下的 ${uids.length} 个条目设为固定导入。`);
    setRowMenu(null);
  };
  // ── 批量操作：全部只改策略草稿，照常走「保存策略」落盘 ──
  const runBatchFixed = (on: boolean) => {
    const next = batchFixed(policy, detail, picked, on);
    setPolicy(next);
    setBatchNote(next === policy ? "所选条目已处于该状态。" : on ? `已将 ${picked.length} 个条目设为固定导入。` : `已取消 ${picked.length} 个条目的固定导入。`);
  };
  const runBatchSource = (maxDepth: number | null) => {
    const next = batchSource(policy, detail, picked, maxDepth);
    setPolicy(next);
    setBatchNote(maxDepth === null ? `已取消 ${picked.length} 个条目的导入源。` : `已将 ${picked.length} 个条目设为导入源（深度 ${maxDepth}）。`);
  };
  const runBatchLink = (direction: "to" | "from") => {
    if (!batchTarget) { setError("请先选择批量依赖的目标条目。"); return; }
    const { policy: next, added, skipped } = batchAddEdges(policy, detail, picked, batchTarget, direction);
    if (!added.length) { setError(`没有新增依赖：${skipped} 条已存在或指向自身。`); return; }
    setError(""); setPolicy(next);
    setBatchNote(direction === "to"
      ? `已建立 ${added.length} 条依赖：所选 → ${label(batchTarget)}。`
      : `已建立 ${added.length} 条依赖：${label(batchTarget)} → 所选。`);
  };
  const runBatchUnlink = (uids: string[], scope: string) => {
    const { policy: next, removed } = batchRemoveEdges(policy, detail, uids);
    setPolicy(next);
    setBatchNote(removed ? `已清除 ${scope} 的 ${removed} 条依赖边。` : `${scope}没有可清除的依赖边。`);
  };
  const runBatchMove = async () => {
    const moves = batchMove(detail, picked, batchCategory);
    if (!Object.keys(moves).length) return;
    if (await run(() => api.updateWorldbookTaxonomy(detail.id, categories, moves, detail.import_config?.revision))) {
      setBatchNote(`已将 ${Object.keys(moves).length} 个条目移入「${categories.find((category) => category.id === batchCategory)?.name || batchCategory}」。`);
      setPicked([]);
    }
  };
  const startBatchLink = (uids: string[], origin: string) => {
    const targets = knownUids(detail, uids);
    if (!targets.length) { setError("没有可连线的条目。"); return; }
    setLinkFrom(targets); setError("");
    setPanel(null); setRowMenu(null);
    setBatchNote(`已进入连线模式（${origin}）：在图中点击目标条目即可建立依赖。`);
  };
  const newCategory = () => {
    const parentId = categoryId && categoryId !== "unclassified" ? categoryId : null;
    setCategoryDraft({ id: "cat-" + crypto.randomUUID(), parent_id: parentId, name: "",
      scope_type: categories.find((category) => category.id === parentId)?.scope_type || "other", sort_order: categories.length * 10 });
    setSelection(null); setSelectedEdge(null); setPanel("inspector");
  };
  const editEntry = () => {
    if (!focused) return;
    if (onEditEntry) onEditEntry(focused);
    else if (!dirty || window.confirm("导入策略尚未保存，离开图谱会丢弃草稿。继续编辑正文吗？")) {
      store.setWorldbookEntryJump({ bookId: detail.id, entryUid: focused.uid });
      store.setWorldbookJumpId(detail.id); store.setCurrentView("worldbook");
    }
  };
  const saveCategory = async () => {
    if (!categoryDraft || !categoryDraft.name.trim() || !Number.isInteger(categoryDraft.sort_order)) return;
    const next = categories.filter((category) => category.id !== categoryDraft.id).map((category) =>
      editingDescendants.has(category.id) ? { ...category, scope_type: categoryDraft.scope_type } : category);
    next.push(categoryDraft);
    if (await run(() => api.updateWorldbookTaxonomy(detail.id, next, {}, detail.import_config?.revision))) {
      setSelection({ kind: "category", id: categoryDraft.id }); setCategoryDraft(null); setPanel(null);
    }
  };
  const deleteCategory = async () => {
    if (!categoryDraft || editingDescendants.has(deleteTarget)) return;
    const moved = detail.entries.filter((entry) => editingDescendants.has(entry.category_id || ""));
    if (!window.confirm("删除该分类及子分类，并将 " + moved.length + " 个条目移入所选目标？条目内容不会删除。")) return;
    if (await run(() => api.updateWorldbookTaxonomy(detail.id, categories.filter((category) => !editingDescendants.has(category.id)),
      Object.fromEntries(moved.map((entry) => [entry.uid, deleteTarget])), detail.import_config?.revision))) {
      setCategoryDraft(null); setSelection(null); setPanel(null);
      if (editingDescendants.has(categoryId)) filterCategory("");
    }
  };
  const openDependencies = () => {
    store.setWorldbookScopeJumpId(detail.id); store.setContentHubTab("worldbook-deps"); store.setCurrentView("content");
  };
  const openClassification = async () => {
    if (panel === "classify") { setPanel(null); return; }
    setPanel("classify"); setSelection(null); setSelectedEdge(null); setCategoryDraft(null);
    setClassification(null); setClassifyError("");
    try { setClassification(await api.previewWorldbookClassification(detail.id)); }
    catch (e) { setClassifyError(e instanceof Error ? e.message : "读取分类线索失败"); }
  };
  const applyClassification = async () => {
    if (!classification?.matched) return;
    // 应用会重新加载书，草稿里的导入策略会丢失，交给 run 统一确认。
    if (await run(() => api.applyWorldbookClassification(detail.id, detail.import_config?.revision))) setPanel(null);
  };

  return <section className={"wbg-workbench" + (expanded ? " wbg-expanded" : "")} aria-label={view === "taxonomy" ? "世界书分类工作台" : treeView ? "世界书依赖树工作台" : "世界书依赖工作台"}>
    <header className="wbg-header">
      <div className="wbg-heading"><WorldBookGraphIcon name="graph" size={22} /><div>
        <h3>{view === "taxonomy" ? "分类与角色关联" : treeView ? "世界书依赖树" : "世界书依赖图谱"}</h3>
        <p>{view === "taxonomy" ? "分类组织内容，条目关联角色"
          : treeView ? "按导入源与遍历深度分层展开；虚线边代表不会展开的依赖"
            : "A → B 表示 A 依赖 B，分类连线不参与依赖展开"}</p>
      </div></div>
      <div className="wbg-header-actions">
        {isDependency && <>
          <select className="wbg-field wbg-mode-select" aria-label="载入模式" disabled={busy} value={policy.scope_mode}
            onChange={(event) => setPolicy((current) => ({ ...current, scope_mode: event.target.value as WorldBookPolicyDraft["scope_mode"] }))}>
            <option value="selective">按需载入</option><option value="legacy">全量兼容</option>
          </select>
          <button className="wbg-button wbg-button-quiet" disabled={busy || !dirty} onClick={() => { setPolicy(policyFrom(detail)); setError(""); }}>撤销草稿</button>
          <button className="wbg-button wbg-button-primary" disabled={busy || !dirty || !preview || !!previewError}
            onClick={() => void run(() => api.updateWorldbookImportConfig(detail.id, { ...policy, expected_revision: detail.import_config?.revision }), true)}>
            {busy ? "保存中…" : dirty ? "保存策略" : "已保存"}
          </button>
        </>}
        <button className="wbg-icon-button" aria-label={expanded ? "收起图谱工作台" : "展开图谱工作台"} title={expanded ? "收起图谱工作台" : "展开图谱工作台"} onClick={() => setExpanded(!expanded)}>
          <WorldBookGraphIcon name={expanded ? "close" : "fit"} />
        </button>
      </div>
    </header>
    <div className="wbg-toolbar">
      <button className={"wbg-button wbg-button-quiet" + (libraryOpen ? " is-active" : "")} aria-expanded={libraryOpen} onClick={() => {
        if (panel) { setPanel(null); setLibraryOpen(true); } else setLibraryOpen(!libraryOpen);
      }}><WorldBookGraphIcon name="panel" />节点目录</button>
      <div className="wbg-breadcrumb"><button onClick={() => filterCategory("")}>全部分类</button>{categoryId && <><span>/</span><span>{categories.find((category) => category.id === categoryId)?.name || categoryId}</span></>}</div>
      {view === "taxonomy"
        ? <>
          <button className={"wbg-button wbg-button-quiet" + (panel === "classify" ? " is-active" : "")} aria-expanded={panel === "classify"}
            title="按条目自带的 uid 前缀 / group / 名称后缀推断分类，先预览再决定是否应用" onClick={() => void openClassification()}>
            <WorldBookGraphIcon name="tag" />自动分类
          </button>
          <button className="wbg-button wbg-button-quiet" disabled={busy} onClick={newCategory}>＋ 新建分类</button>
        </>
        : <label className="wbg-checkbox-label"><input type="checkbox" checked={connectedOnly} onChange={(event) => setConnectedOnly(event.target.checked)} />仅已配置</label>}
      <div className="wbg-toolbar-spacer" />
      {isDependency ? <>
        <span className={"wbg-save-state" + (dirty ? " is-dirty" : "")}>{dirty ? "有未保存修改" : "策略已同步"}</span>
        <button className={"wbg-button" + (panel === "preview" ? " is-active" : "")} onClick={() => setPanel(panel === "preview" ? null : "preview")} aria-expanded={panel === "preview"}><WorldBookGraphIcon name="preview" />导入预览{preview && <span className="wbg-count">{preview.entry_count}</span>}</button>
      </> : <button className="wbg-button wbg-button-quiet" onClick={openDependencies}>打开内容中心 · 依赖图谱 →</button>}
    </div>
    {isDependency && <div className="wbg-toolbar wbg-toolbar-sub">
      <div className="wbg-seg" role="group" aria-label="节点着色依据">
        <button aria-pressed={coloring === "kind"} title="按分类类型着色：世界观 / 角色 / 其他" onClick={() => setColoring("kind")}>按类型</button>
        <button aria-pressed={coloring === "role"} title="按依赖角色着色：导入源 / 固定导入 / 中转 / 叶子 / 未配置" onClick={() => setColoring("role")}>按角色</button>
      </div>
      <div className="wbg-role-filter" role="group" aria-label="按依赖角色筛选节点">
        <button className="wbg-role-chip" aria-pressed={!roleFilter.length} title="显示全部角色" onClick={() => setRoleFilter([])}>全部 <b>{detail.entries.length}</b></button>
        {DEPENDENCY_ROLES.map((item) => <button key={item} className="wbg-role-chip" data-wbg-role={item} aria-pressed={roleFilter.includes(item)} title={ROLE_HINTS[item]}
          onClick={() => toggleRole(item)}><i />{ROLE_LABELS[item]} <b>{graph.roles[item]}</b></button>)}
      </div>
      {treeView && <>
        <label className="wbg-form-label wbg-inline-field">展开层级
          <input className="wbg-field wbg-depth" type="number" aria-label="依赖树展开层级" min={0} max={model?.stats.maxDepth ?? 0} step={1} disabled={!model}
            value={treeDepthLimit} onChange={(event) => setTreeDepth(Math.max(0, Math.min(model?.stats.maxDepth ?? 0, Number(event.target.value) || 0)))} />
          <small>/ {model?.stats.maxDepth ?? 0}</small>
        </label>
        <button className="wbg-button wbg-button-quiet" disabled={!model || treeDepthLimit >= (model?.stats.maxDepth ?? 0)} onClick={() => setTreeDepth(model?.stats.maxDepth ?? 0)}>全部展开</button>
        <button className="wbg-button wbg-button-quiet" disabled={!collapsed.size} onClick={() => setCollapsed(new Set())}>重置折叠</button>
        <label className="wbg-checkbox-label" title="把固定导入但未展开的条目、以及未被任何导入源覆盖的条目放到树的底部">
          <input type="checkbox" checked={showLoose} onChange={(event) => setShowLoose(event.target.checked)} />未覆盖条目 <b>{model ? model.stats.looseCount + model.stats.fixedOnlyCount : 0}</b>
        </label>
      </>}
      <div className="wbg-toolbar-spacer" />
      <div className="wbg-dep-stats" aria-label="依赖统计">
        <span>源 <b>{model?.stats.sourceCount ?? 0}</b></span>
        <span>固定 <b>{model?.stats.fixedCount ?? 0}</b></span>
        <span>已覆盖 <b>{model?.stats.reachableCount ?? 0}</b></span>
        {!!model?.stats.looseCount && <span className="is-warn">未覆盖 <b>{model.stats.looseCount}</b></span>}
        {!!model?.stats.cycleCount && <span className="is-warn" title="位于依赖环内的条目；遍历按剩余深度去重，不会死循环">依赖环 <b>{model.stats.cycleCount}</b></span>}
        {!!model?.stats.cappedEdges && <span className="is-warn" title="上游已进入候选范围但遍历深度用尽，这些依赖不会展开">超深度边 <b>{model.stats.cappedEdges}</b></span>}
        {!!model?.stats.idleEdges && <span title="上游未进入候选范围，这些依赖不会展开">未启用边 <b>{model.stats.idleEdges}</b></span>}
      </div>
    </div>}
    {error && <div role="alert" className="wbg-notice wbg-error"><span>{error}</span><button onClick={() => { if (!dirty || window.confirm("重新加载会丢弃未保存策略，继续吗？")) void onChanged(); }}>重新加载</button><button aria-label="关闭错误提示" onClick={() => setError("")}>×</button></div>}
    {!!picked.length && <div className="wbg-toolbar wbg-batch-bar" aria-label="批量操作">
      <span className="wbg-batch-count"><WorldBookGraphIcon name="tag" size={13} />已选 <b>{picked.length}</b> 个条目</span>
      {isDependency ? <>
        <button className="wbg-button wbg-button-quiet" disabled={busy} onClick={() => runBatchFixed(true)}>固定导入</button>
        <button className="wbg-button wbg-button-quiet" disabled={busy} onClick={() => runBatchFixed(false)}>取消固定</button>
        <div className="wbg-batch-group">
          <label className="wbg-form-label wbg-inline-field">导入源深度
            <input className="wbg-field wbg-depth" type="number" aria-label="批量导入源深度" min={0} max={32} step={1} value={batchDepth}
              onChange={(event) => setBatchDepth(Math.max(0, Math.min(32, Number(event.target.value) || 0)))} />
          </label>
          <button className="wbg-button wbg-button-quiet" disabled={busy} onClick={() => runBatchSource(batchDepth)}>设为导入源</button>
          <button className="wbg-button wbg-button-quiet" disabled={busy} onClick={() => runBatchSource(null)}>取消导入源</button>
        </div>
        <div className="wbg-batch-group">
          <label className="wbg-form-label wbg-inline-field">依赖目标
            <select className="wbg-field wbg-batch-target" aria-label="批量依赖目标" value={batchTarget} onChange={(event) => setBatchTarget(event.target.value)}>
              <option value="">选择条目</option>
              {detail.entries.filter((entry) => !pickedSet.has(entry.uid))
                .map((entry) => <option key={entry.uid} value={entry.uid}>{entry.name || entry.uid}</option>)}
            </select>
          </label>
          <button className="wbg-button wbg-button-quiet" disabled={busy || !batchTarget} onClick={() => runBatchLink("to")}>所选 → 目标</button>
          <button className="wbg-button wbg-button-quiet" disabled={busy || !batchTarget} onClick={() => runBatchLink("from")}>目标 → 所选</button>
          <button className="wbg-button wbg-button-quiet" disabled={busy} onClick={() => startBatchLink(picked, "所选条目")}>在图中点选目标</button>
        </div>
        <button className="wbg-button wbg-button-quiet" disabled={busy} onClick={() => runBatchUnlink(picked, "所选条目")}>清空所选依赖</button>
      </> : <>
        <label className="wbg-form-label wbg-inline-field">归属分类
          <select className="wbg-field wbg-batch-target" aria-label="批量归属分类" value={batchCategory} onChange={(event) => setBatchCategory(event.target.value)}>
            {rows.map(({ category, level }) => <option key={category.id} value={category.id}>{"　".repeat(level)}{category.name}</option>)}
          </select>
        </label>
        <button className="wbg-button wbg-button-quiet" disabled={busy} onClick={() => void runBatchMove()}>批量移入该分类</button>
      </>}
      <div className="wbg-toolbar-spacer" />
      <button className="wbg-button wbg-button-quiet" onClick={() => { setPicked([]); setBatchNote(""); }}>清除选择</button>
    </div>}
    {batchNote && <div className="wbg-notice wbg-batch-notice" role="status">
      <span>{batchNote}</span>
      <button aria-label="关闭批量操作提示" onClick={() => setBatchNote("")}>×</button>
    </div>}
    {previewError && isDependency && <div role="alert" className="wbg-notice wbg-error">预览未通过：{previewError}</div>}
    <div className="wbg-body">
      {libraryOpen && <aside className="wbg-library" aria-label="节点目录">
        <div className="wbg-panel-heading"><span>节点目录</span><button className="wbg-icon-button" aria-label="收起节点目录" onClick={() => setLibraryOpen(false)}><WorldBookGraphIcon name="close" /></button></div>
        <label className="wbg-search"><WorldBookGraphIcon name="search" /><input placeholder="搜索名称、UID、关键词" aria-label="搜索条目节点" value={query} onChange={(event) => setQuery(event.target.value)} />{query && <button aria-label="清空节点搜索" onClick={() => setQuery("")}>×</button>}</label>
        <div className="wbg-library-scroll">
          <div className="wbg-section-label">分类树 <span>{categories.length}</span></div>
          <nav className="wbg-category-tree" aria-label="分类树">
            {rows.map(({ category, level }) => <div key={category.id}
              className={"wbg-tree-row" + (categoryId === category.id ? " is-active" : "") + (rowMenu === category.id ? " is-open" : "")}
              style={{ paddingLeft: 10 + Math.min(level, 8) * 13 }}>
              <button className="wbg-tree-main" title={category.name + " · " + KINDS[category.scope_type]}
                onClick={() => { filterCategory(category.id); inspectCategory(category.id); }}>
                <i className="wbg-type-dot" data-wbg-kind={category.scope_type} /><span>{category.name}</span>
                <small>{detail.entries.filter((entry) => (entry.category_id || "unclassified") === category.id).length}</small>
              </button>
              <button className="wbg-tree-more" aria-label={`${category.name} 的分类批量操作`} aria-expanded={rowMenu === category.id}
                title="分类批量操作"
                onClick={() => setRowMenu(rowMenu === category.id ? null : category.id)}>⋯</button>
              {rowMenu === category.id && <div className="wbg-row-menu" role="menu" aria-label={`${category.name} 的分类操作`}>
                <button role="menuitem" onClick={() => pickCategory(category.id)}>
                  选中该分类下 {categoryEntryUids(detail, category.id).length} 个条目
                </button>
                {isDependency && <>
                  <button role="menuitem" onClick={() => sourceCategory(category.id)}>整类设为导入源（深度 {batchDepth}）</button>
                  <button role="menuitem" onClick={() => fixedCategory(category.id)}>整类固定导入</button>
                  <button role="menuitem" onClick={() => startBatchLink(categoryEntryUids(detail, category.id), `分类「${category.name}」`)}>整类连线到图中目标</button>
                  <button role="menuitem" onClick={() => runBatchUnlink(categoryEntryUids(detail, category.id), `分类「${category.name}」`)}>清空整类依赖</button>
                </>}
                <button role="menuitem" onClick={() => { filterCategory(category.id); inspectCategory(category.id); }}>聚焦并编辑该分类</button>
              </div>}
            </div>)}
          </nav>
          <div className="wbg-section-label">条目节点 <span>{filtered.length}</span></div>
          <div className="wbg-entry-list">
            {filtered.slice(0, 200).map((entry) => <button key={entry.uid} draggable={!busy}
              className={"wbg-entry-row" + (focusedUid === entry.uid ? " is-active" : "") + (!entry.enabled ? " is-disabled" : "")}
              title={entry.name + " · " + entry.uid} onClick={() => inspectEntry(entry.uid)}
              onDragStart={(event) => { event.dataTransfer.setData(MIME, JSON.stringify({ book_id: detail.id, uid: entry.uid })); event.dataTransfer.effectAllowed = "copy"; }}>
              <i className="wbg-entry-dot" data-wbg-kind={categories.find((category) => category.id === entry.category_id)?.scope_type || "other"} />
              <span><strong>{entry.name || entry.uid}</strong><small>{!entry.enabled ? "已停用" : entry.character_id || entry.uid}</small></span>
              {isDependency && <em className="wbg-role-tag" data-wbg-role={model?.roles.get(entry.uid) || "orphan"}
                title={ROLE_LABELS[model?.roles.get(entry.uid) || "orphan"]}>{ROLE_GLYPHS[model?.roles.get(entry.uid) || "orphan"]}</em>}
              {fixed.has(entry.uid) && <WorldBookGraphIcon name="pin" size={13} />}
            </button>)}
            {!filtered.length && <p className="wbg-help">没有匹配条目，试试其他关键词或清空角色筛选。</p>}
            {filtered.length > 200 && <p className="wbg-help">显示前 200 条，请通过搜索定位更多条目。</p>}
          </div>
        </div>
        <p className="wbg-library-foot">{view === "taxonomy" ? "选中分类或条目，在侧栏编辑归属。"
          : treeView ? "依赖树只画条目：层级来自遍历深度，分类仍可用上方分类树筛选。" : "拖入底栏可固定导入；也可在节点侧栏设置。"}</p>
      </aside>}
      <main className="wbg-stage">
        <WorldBookGraphCanvas graph={graph} view={view} selectedId={selectedId} selectedEdgeId={selectedEdge} linkFromUids={linkFrom} pickedIds={picked} busy={busy}
          coloring={coloring} tree={treeOptions} onToggleCollapse={toggleCollapse}
          onSelectNode={selectNode} onPickMany={pickMany}
          onSelectEdge={(id) => { setSelectedEdge(id); setSelection(null); setCategoryDraft(null); setPanel("inspector"); }}
          onLinkStart={(uid) => { setLinkFrom([uid]); setError(""); setBatchNote(""); }} onCancelLink={() => setLinkFrom(null)}
          onClear={() => { setSelection(null); setSelectedEdge(null); setCategoryDraft(null); if (panel === "inspector") setPanel(null); }}
          onDropEntry={(event) => { event.preventDefault(); const uid = dragUid(event); if (uid) inspectEntry(uid); }} />
      </main>
      {panel && <aside className="wbg-inspector" aria-label={panel === "preview" ? "导入预览面板" : panel === "classify" ? "自动分类面板" : "节点属性"}>
        <div className="wbg-panel-heading"><span>{panel === "preview" ? "导入预览" : panel === "classify" ? "自动分类" : selectedRelation ? "依赖关系" : categoryDraft ? "分类属性" : focused ? "条目属性" : "分类概览"}</span>
          <button className="wbg-icon-button" aria-label="关闭属性面板" onClick={() => setPanel(null)}><WorldBookGraphIcon name="close" /></button>
        </div>
        <div className="wbg-inspector-scroll">
          {panel === "classify" ? <>
            <div className="wbg-inspector-section"><p className="wbg-eyebrow">AUTO CLASSIFY</p><h4>按条目自带的类别分类</h4>
              <p className="wbg-help">只认 uid 前缀、group 字段与名称后缀三类显式线索，识别不出就保持未分类，不按名字或正文猜测。应用只改分类与角色关联，不改载入模式、固定导入与依赖策略。</p>
            </div>
            {classifyError && <div role="alert" className="wbg-notice wbg-error"><span>{classifyError}</span><button onClick={() => void openClassification()}>重试</button></div>}
            {!classification && !classifyError && <p className="wbg-help" role="status">正在读取条目的分类线索…</p>}
            {classification && (classification.matched === 0 ? <p className="wbg-help">{classification.reason || "没有可用的分类线索，已保持原样。"}</p> : <>
              <div className="wbg-metric-row">
                <span>可归类 <b>{classification.matched}</b></span>
                <span>无线索 <b>{classification.unmatched_count}</b></span>
                <span>角色关联 <b>{classification.character_links}</b></span>
                <span>线索冲突 <b>{classification.conflicts.length}</b></span>
              </div>
              <div className="wbg-inspector-section">
                <h5>将写入的分类</h5>
                <div className="wbg-classify-list">
                  {classification.categories.map((category) => <div key={category.id}>
                    <i data-wbg-kind={category.scope_type} />
                    <span>{category.parent_id ? "↳ " : ""}{category.name}<small>{KINDS[category.scope_type]}</small></span>
                    <b>{category.count}</b>
                  </div>)}
                </div>
                <p className="wbg-help">共 {classification.categories.length} 个分类；条目归属会按上表替换。</p>
              </div>
              {!!Object.keys(classification.signals).length && <p className="wbg-help">线索来源：
                {Object.entries(classification.signals).map(([signal, count]) => `${SIGNALS[signal] || signal} ${count} 条`).join(" · ")}</p>}
              {!!classification.unmatched_count && <details className="wbg-details"><summary>未识别条目 <span>{classification.unmatched_count}</span></summary>
                <div className="wbg-tree-path">{classification.unmatched.map((uid) => <button key={uid} className="wbg-text-button" onClick={() => inspectEntry(uid)}>{label(uid)}</button>)}</div>
                <p className="wbg-help">这些条目保持各自原有分类（默认未分类），正文不受影响。</p>
              </details>}
              {!!classification.conflicts.length && <details className="wbg-details"><summary>线索冲突 <span>{classification.conflicts.length}</span></summary>
                {classification.conflicts.map((item) => <p key={item.uid} className="wbg-help">{label(item.uid)}：
                  {Object.entries(item.votes).map(([signal, categoryId]) => `${SIGNALS[signal] || signal} → ${classificationName(classification, categoryId)}`).join("；")}</p>)}
                <p className="wbg-help">结论按 uid 前缀 &gt; group 字段 &gt; 名称后缀 取值；冲突条目可以人工复核。</p>
              </details>}
              <button className="wbg-button wbg-button-primary" disabled={busy} onClick={() => void applyClassification()}>
                <WorldBookGraphIcon name="tag" />应用分类（{classification.matched} 条）
              </button>
              <p className="wbg-help">应用会写入分类树与条目归属并刷新页面；载入模式与依赖策略保持不变。</p>
            </>)}
          </> : panel === "preview" ? <>
            <div className="wbg-inspector-section"><p className="wbg-eyebrow">IMPORT SCOPE</p><h4>载入前，先看候选范围</h4><p className="wbg-help">预览不会修改会话。世界观、入队角色、固定条目与依赖展开合并后去重。</p></div>
            <details className="wbg-details"><summary>预览阵容 <span>{roster.length} 位</span></summary><div className="wbg-roster-list">
              {characters?.map((character) => <label key={character.id} className="wbg-checkbox-label"><input type="checkbox" checked={roster.includes(character.id)}
                onChange={(event) => setRoster((current) => event.target.checked ? [...current, character.id] : current.filter((id) => id !== character.id))} />{character.name || character.title || character.id}</label>)}
              {characters?.length === 0 && <p className="wbg-help">暂无可用角色。</p>}{characters === null && <p className="wbg-help">角色目录暂不可用，仍可预览固定条目与依赖。</p>}
            </div></details>
            {preview ? <div className="wbg-preview-content"><WorldBookScopePreview value={preview} /></div> : <p className="wbg-help" role="status">{previewError || "正在计算候选范围…"}</p>}
            <details className="wbg-details" open><summary>导入源 <span>{policy.dependency_sources.length} 个</span></summary>
              {policy.dependency_sources.map((item) => <div className="wbg-source-row" key={item.entry_uid}>
                <button className="wbg-text-button" onClick={() => inspectEntry(item.entry_uid)}>{label(item.entry_uid)}</button>
                <label>深度 <input className="wbg-field wbg-depth" type="number" min={0} max={32} step={1} disabled={busy} aria-label={label(item.entry_uid) + " 的遍历深度"} value={item.max_depth} onChange={(event) => setSource(item.entry_uid, Number(event.target.value))} /></label>
                <button className="wbg-icon-button" aria-label={"移除导入源 " + label(item.entry_uid)} disabled={busy} onClick={() => setSource(item.entry_uid, null)}>×</button>
              </div>)}
              {!policy.dependency_sources.length && <p className="wbg-help">选中条目后，可以将其设为导入源。</p>}
            </details>
            <p className="wbg-help">保存策略影响后续新建会话；已有会话保留候选快照，调整阵容或重新绑定时才重算。</p>
          </> : selectedRelation ? <>
            <div className="wbg-inspector-section"><p className="wbg-eyebrow">DIRECTED RELATION</p><h4>{label(selectedRelation.from_uid)}</h4><div className="wbg-relation-direction">↓ 依赖</div><h4>{label(selectedRelation.to_uid)}</h4></div>
            <p className="wbg-help">仅当遍历深度覆盖这条边时，目标条目才会由该导入源展开。固定条目不隐式展开。</p>
            <button className="wbg-button wbg-danger" disabled={busy} onClick={() => removeEdge(selectedRelation.from_uid, selectedRelation.to_uid)}>删除依赖边</button>
            <p className="wbg-help">只修改策略草稿，不会删除条目内容。</p>
          </> : <>
            {categoryDraft && view === "taxonomy" && <fieldset disabled={busy} className="wbg-form">
              <p className="wbg-eyebrow">CATEGORY</p><h4>{categories.some((category) => category.id === categoryDraft.id) ? categoryDraft.name : "新建分类"}</h4>
              <label className="wbg-form-label">名称<input className="wbg-field" value={categoryDraft.name} placeholder="例如：罗德岛 / 地区设定" onChange={(event) => setCategoryDraft({ ...categoryDraft, name: event.target.value })} /></label>
              <label className="wbg-form-label">父分类<select className="wbg-field" value={categoryDraft.parent_id || ""} onChange={(event) => {
                const parent = categories.find((category) => category.id === event.target.value);
                setCategoryDraft({ ...categoryDraft, parent_id: parent?.id || null, scope_type: parent?.scope_type || categoryDraft.scope_type });
              }}><option value="">根分类</option>{rows.filter(({ category }) => category.id !== "unclassified" && !editingDescendants.has(category.id)).map(({ category, level }) => <option key={category.id} value={category.id}>{"　".repeat(level)}{category.name}</option>)}</select></label>
              <div className="wbg-form-pair"><label className="wbg-form-label">类型<select className="wbg-field" value={categoryDraft.scope_type} disabled={!!categoryDraft.parent_id} onChange={(event) => setCategoryDraft({ ...categoryDraft, scope_type: event.target.value as WorldBookCategoryDTO["scope_type"] })}>
                {Object.entries(KINDS).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label>
                <label className="wbg-form-label">排序<input className="wbg-field" type="number" step={1} value={categoryDraft.sort_order} onChange={(event) => setCategoryDraft({ ...categoryDraft, sort_order: Number(event.target.value) })} /></label></div>
              {categoryDraft.parent_id && <p className="wbg-help">子分类沿用父分类的类型。</p>}
              <button className="wbg-button wbg-button-primary" disabled={!categoryDraft.name.trim() || !Number.isInteger(categoryDraft.sort_order)} onClick={() => void saveCategory()}>保存分类</button>
              {categories.some((category) => category.id === categoryDraft.id) && <details className="wbg-details wbg-delete-section"><summary>删除分类…</summary>
                <p className="wbg-help">包含子分类。条目内容保留，并移动到下方分类。</p>
                <label className="wbg-form-label">条目移至<select className="wbg-field" value={deleteTarget} onChange={(event) => setDeleteTarget(event.target.value)}>
                  {rows.filter(({ category }) => !editingDescendants.has(category.id)).map(({ category }) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
                <button className="wbg-button wbg-danger" onClick={() => void deleteCategory()}>删除分类及子分类</button>
              </details>}
            </fieldset>}
            {selection?.kind === "category" && <>
              {(isDependency || !categoryDraft) && <div className="wbg-inspector-section"><p className="wbg-eyebrow">CATEGORY</p><h4>{categories.find((category) => category.id === selection.id)?.name}</h4><p className="wbg-help">{selection.id === "unclassified" ? "未分类是永久保留的归档分类，不能删除。" : "分类用于组织与筛选；分类连线不会自动形成条目依赖。"}</p></div>}
              <button className="wbg-button" onClick={() => filterCategory(selection.id)}>聚焦此分类</button>
              <div className="wbg-inspector-section">
                <h5>分类批量操作</h5>
                <p className="wbg-help">该分类及子分类共 {categoryEntryUids(detail, selection.id).length} 个条目；操作只改策略草稿，随后照常点「保存策略」。</p>
                <button className="wbg-button" onClick={() => pickCategory(selection.id)}>
                  <WorldBookGraphIcon name="tag" size={13} />选中这些条目（{categoryEntryUids(detail, selection.id).length}）
                </button>
                {isDependency && <>
                  <div className="wbg-form-pair">
                    <button className="wbg-button" disabled={busy} onClick={() => sourceCategory(selection.id)}>整类设为导入源</button>
                    <button className="wbg-button" disabled={busy} onClick={() => fixedCategory(selection.id)}>整类固定导入</button>
                  </div>
                  <label className="wbg-form-label">整类依赖目标
                    <select className="wbg-field" aria-label="整类依赖目标" value={batchTarget} onChange={(event) => setBatchTarget(event.target.value)}>
                      <option value="">选择一个条目</option>
                      {detail.entries.map((entry) => <option key={entry.uid} value={entry.uid}>{entry.name || entry.uid}</option>)}
                    </select>
                  </label>
                  <div className="wbg-form-pair">
                    <button className="wbg-button" disabled={busy || !batchTarget}
                      onClick={() => { const uids = categoryEntryUids(detail, selection.id); const { policy: next, added, skipped } = batchAddEdges(policy, detail, uids, batchTarget, "to");
                        if (added.length) { setPolicy(next); setBatchNote(`已建立 ${added.length} 条依赖：分类「${categoryName(selection.id)}」→ ${label(batchTarget)}${skipped ? `，跳过 ${skipped} 条` : ""}。`); }
                        else setBatchNote(`没有新增依赖：${skipped} 条已存在或指向自身。`); }}>整类 → 目标</button>
                    <button className="wbg-button" disabled={busy || !batchTarget}
                      onClick={() => { const uids = categoryEntryUids(detail, selection.id); const { policy: next, added, skipped } = batchAddEdges(policy, detail, uids, batchTarget, "from");
                        if (added.length) { setPolicy(next); setBatchNote(`已建立 ${added.length} 条依赖：${label(batchTarget)} → 分类「${categoryName(selection.id)}」${skipped ? `，跳过 ${skipped} 条` : ""}。`); }
                        else setBatchNote(`没有新增依赖：${skipped} 条已存在或指向自身。`); }}>目标 → 整类</button>
                  </div>
                  <button className="wbg-button wbg-button-quiet" disabled={busy} onClick={() => startBatchLink(categoryEntryUids(detail, selection.id), `分类「${categoryName(selection.id)}」`)}>在图中点选目标连线</button>
                  <button className="wbg-button wbg-button-quiet" disabled={busy} onClick={() => runBatchUnlink(categoryEntryUids(detail, selection.id), `分类「${categoryName(selection.id)}」`)}>清空整类依赖</button>
                </>}
              </div>
              {isDependency && <p className="wbg-help">切换顶部「分类结构」可编辑分类名称、父级与条目归属。</p>}
            </>}
            {focused && <>
              <div className="wbg-inspector-section"><span className="wbg-kind-label" data-wbg-kind={categories.find((category) => category.id === focused.category_id)?.scope_type || "other"}>{KINDS[categories.find((category) => category.id === focused.category_id)?.scope_type || "other"]}</span>
                <h4>{focused.name || focused.uid}</h4><p className="wbg-uid">{focused.uid}</p>
                {!focused.enabled && <p className="wbg-warning">此条目已停用，不参与实际注入。</p>}
                <p className="wbg-entry-excerpt">{focused.content?.slice(0, 180) || "暂无正文"}</p>
              </div>
              {isDependency && <div className="wbg-inspector-section wbg-role-panel">
                <div className="wbg-section-heading"><h5>节点分类</h5>
                  <span className="wbg-role-pill" data-wbg-role={role || "orphan"}>{ROLE_GLYPHS[role || "orphan"]} {ROLE_LABELS[role || "orphan"]}</span>
                </div>
                <p className="wbg-help">{ROLE_HINTS[role || "orphan"]}。</p>
                {treeNode && model ? <>
                  <div className="wbg-metric-row">
                    <span>层级 <b>{treeNode.depth}</b></span>
                    <span>剩余深度 <b>{treeNode.remaining}</b></span>
                    <span>下游节点 <b>{dependencyDescendants(model, treeNode.uid)}</b></span>
                    <span>直接下游 <b>{treeNode.childUids.length}</b></span>
                  </div>
                  <div className="wbg-tree-path" aria-label="依赖树路径">
                    <span className="wbg-tree-path-label">起点 {label(treeNode.sourceUid)}</span>
                    {dependencyPath(model, treeNode.uid).map((uid, index) => <Fragment key={uid}>
                      {index > 0 && <span className="wbg-path-arrow" aria-hidden="true">→</span>}
                      <button className={"wbg-text-button" + (uid === treeNode.uid ? " is-current" : "")} onClick={() => inspectEntry(uid)}>{label(uid)}</button>
                    </Fragment>)}
                  </div>
                  {treeNode.inCycle && <p className="wbg-warning">位于依赖环内：遍历按「已访问节点的最佳剩余深度」终止，不会死循环；树上只保留第一次到达的路径。</p>}
                </> : null}
                {!treeNode && <p className="wbg-help">{fixed.has(focused.uid)
                  ? "固定导入：会作为注入候选，但不沿依赖展开。"
                  : role === "orphan" ? "未参与固定导入、导入源或依赖边；仍可能由世界观或入队角色来源进入候选。"
                    : "已参与依赖配置，但当前策略下不会被任何导入源展开：检查上游遍历深度，或把它设为导入源。"}</p>}
              </div>}
              {isDependency && <fieldset disabled={busy} className="wbg-form">
                <button role="switch" aria-checked={fixed.has(focused.uid)} className="wbg-policy-switch" onClick={() => fixed.has(focused.uid) ? removeFixed(focused.uid) : addFixed(focused.uid)}>
                  <WorldBookGraphIcon name="pin" /><span><strong>固定导入</strong><small>始终作为候选，不自动展开依赖</small></span><i className={fixed.has(focused.uid) ? "is-on" : ""} />
                </button>
                <button role="switch" aria-checked={!!source} className="wbg-policy-switch" onClick={() => setSource(focused.uid, source ? null : depth)}>
                  <WorldBookGraphIcon name="graph" /><span><strong>{source ? "已设为导入源" : "设为导入源"}</strong><small>沿出边按指定深度展开</small></span><i className={source ? "is-on" : ""} />
                </button>
                <label className="wbg-form-label">遍历深度 <input aria-label="遍历深度" className="wbg-field" type="number" step={1} min={0} max={32} value={source?.max_depth ?? depth} onChange={(event) => source ? setSource(focused.uid, Number(event.target.value)) : setDepth(Number(event.target.value))} /><small>0 只包含源节点，最大 32 层。</small></label>
                <div className="wbg-inspector-section">
                  <div className="wbg-section-heading"><h5>依赖关系</h5><button className="wbg-text-button" onClick={() => { setLinkFrom([focused.uid]); setError(""); setBatchNote(""); }}>＋ 在图中连线</button></div>
                  <label className="wbg-form-label">依赖目标<select className="wbg-field" aria-label="依赖目标节点" value={edgeTo} onChange={(event) => setEdgeTo(event.target.value)}><option value="">选择一个条目</option>
                    {detail.entries.filter((entry) => entry.uid !== focused.uid).map((entry) => <option key={entry.uid} value={entry.uid}>{entry.name || entry.uid}</option>)}</select></label>
                  <button className="wbg-button" disabled={!edgeTo} onClick={() => addEdge(focused.uid, edgeTo)}><WorldBookGraphIcon name="link" />添加依赖</button>
                  <div className="wbg-relation-list">
                    {policy.dependency_edges.filter((edge) => edge.from_uid === focused.uid || edge.to_uid === focused.uid).map((edge) => <div key={dependencyEdgeId(edge.from_uid, edge.to_uid)}>
                      <span>{edge.from_uid === focused.uid ? "→" : "←"}</span><button className="wbg-text-button" onClick={() => inspectEntry(edge.from_uid === focused.uid ? edge.to_uid : edge.from_uid)}>{label(edge.from_uid === focused.uid ? edge.to_uid : edge.from_uid)}</button>
                      <button className="wbg-icon-button" aria-label={"删除边 " + label(edge.from_uid) + " → " + label(edge.to_uid)} onClick={() => removeEdge(edge.from_uid, edge.to_uid)}>×</button>
                    </div>)}
                  </div>
                </div>
              </fieldset>}
              {view === "taxonomy" && <fieldset disabled={busy} className="wbg-form">
                <label className="wbg-form-label">归属分类<select className="wbg-field" value={assignment.category_id} onChange={(event) => {
                  const category = categories.find((item) => item.id === event.target.value);
                  setAssignment({ category_id: event.target.value, character_id: category?.scope_type === "character" ? assignment.character_id : "" });
                }}>{rows.map(({ category, level }) => <option key={category.id} value={category.id}>{"　".repeat(level)}{category.name}</option>)}</select></label>
                {assignmentKind === "character" && <label className="wbg-form-label">关联角色<input className="wbg-field" list={controlId + "-characters"} placeholder="角色目录名" value={assignment.character_id} onChange={(event) => setAssignment({ ...assignment, character_id: event.target.value })} />
                  <datalist id={controlId + "-characters"}>{characters?.map((character) => <option key={character.id} value={character.id}>{character.name || character.title || character.id}</option>)}</datalist>
                  {characters && assignment.character_id && !characters.some((character) => character.id === assignment.character_id) && <small className="wbg-warning">角色不存在：保留关联值，但不能自动入队载入。</small>}
                </label>}
                <button className="wbg-button wbg-button-primary" onClick={() => void run(() => api.updateWorldbookEntry(detail.id, focused.uid, assignment))}>保存归属</button>
              </fieldset>}
              <button className="wbg-button wbg-button-quiet" onClick={editEntry}>编辑条目正文 ↗</button>
            </>}
          </>}
        </div>
      </aside>}
    </div>
    {isDependency ? <div className={"wbg-import-tray" + (dropActive ? " is-drop-active" : "")} aria-label="固定导入区"
      onDragOver={(event) => { event.preventDefault(); setDropActive(true); }} onDragLeave={() => setDropActive(false)}
      onDrop={(event) => { event.preventDefault(); setDropActive(false); addFixed(dragUid(event)); }}>
      <div className="wbg-tray-heading"><WorldBookGraphIcon name="pin" /><span>固定导入</span><b>{fixed.size}</b></div>
      <div className="wbg-tray-chips">{policy.fixed_entry_uids.map((uid) => <span key={uid} className="wbg-fixed-chip"><button onClick={() => inspectEntry(uid)}>{label(uid)}</button><button aria-label={"移除固定导入 " + label(uid)} disabled={busy} onClick={() => removeFixed(uid)}>×</button></span>)}
        {!fixed.size && <span className="wbg-tray-empty">将条目拖到这里，或在节点属性中开启固定导入</span>}
      </div>
      <button className="wbg-button wbg-button-quiet" disabled={busy || !focusedUid || fixed.has(focusedUid)} onClick={() => addFixed(focusedUid)}>＋ 固定选中条目</button>
    </div> : <footer className="wbg-taxonomy-foot">分类调整不会自动改变旧书的载入模式。完成后，可在依赖图谱中预览并启用按需载入。</footer>}
  </section>;
}
