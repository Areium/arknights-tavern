/**
 * 新建会话向导 — 游戏式分步创建：
 * 模式&战斗模式 → 剧情（可选） → 世界书（可选） → 角色入队（可选） → 命名创建
 *
 * 阵容步骤展示的是**服务端真实解析结果**：候选统计、载入树与选用原因都来自
 * `POST /scope-preview`，前端不自己再走一遍遍历。创建会话本身不调用任何 LLM。
 */
import { useState, useEffect, useMemo } from "react";
import { useAppStore } from "../../stores/appStore";
import { useApi } from "../../hooks/useApi";
import { useDialogMinimize } from "../../hooks/useDialogMinimize";
import { useRosterScopePreview } from "../../hooks/useWorldbookDraft";
import type { PlotInfo, WorldBookSummary, Session } from "../../types";
import WorldBookScopePreview from "../WorldBookScopePreview";

interface CharItem {
  id: string;
  name: string;
  title?: string;
}

/** 角色显示名（/api/characters 返回 title/name，兼容两者） */
const charName = (c: CharItem) => c.name || c.title || c.id;
/** 角色加载键：目录名（slug），后端按目录加载 */
const charKey = (c: CharItem) => c.id || charName(c);

const REASON_LABELS: Record<string, string> = {
  always: "基础设定", roster: "角色入队", requires: "必要依赖", manual: "手动追加",
  full_scope: "全量兼容", worldview: "世界观", fixed: "固定导入", dependency: "依赖展开",
  legacy: "旧书兼容",
};
const reasonLabel = (reason: string) => REASON_LABELS[reason]
  || (reason.startsWith("roster:") ? `角色入队（${reason.slice(7)}）` : reason);

interface CreateSessionWizardProps {
  open: boolean;
  onClose: () => void;
  /** 创建成功后回调（父组件负责刷新 store 并跳转） */
  onCreated: (session: Session) => void;
}

const STEP_LABELS: Record<string, string> = {
  mode: "模式选择",
  identity: "玩家身份",
  plot: "选择剧情",
  worldbook: "绑定世界书",
  roster: "角色入队",
  finish: "命名创建",
};

export default function CreateSessionWizard({ open, onClose, onCreated }: CreateSessionWizardProps) {
  const chatMode = useAppStore((s) => s.chatMode);
  const { setCurrentView } = useAppStore();
  const api = useApi();

  // ── 向导状态 ──
  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<"story" | "free">(chatMode);
  const [combatMode, setCombatMode] = useState<"narrative" | "tactical">("narrative");
  const [identity, setIdentity] = useState("博士");
  const [plotId, setPlotId] = useState("");
  const [worldbookId, setWorldbookId] = useState<string | null>(null);
  const [roster, setRoster] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  // 手动追加只作用于本会话；全量兼容也是显式选择，不写回世界书规则
  const [manualUids, setManualUids] = useState<string[]>([]);
  const [fullScope, setFullScope] = useState(false);
  const [manualQuery, setManualQuery] = useState("");
  const [rosterNote, setRosterNote] = useState("");

  // ── 数据 ──
  const [plots, setPlots] = useState<PlotInfo[]>([]);
  const [books, setBooks] = useState<WorldBookSummary[]>([]);
  const [characters, setCharacters] = useState<CharItem[]>([]);
  const [identities, setIdentities] = useState<{ id: string; name: string; summary: string; tags: string[] }[]>([]);
  const [loading, setLoading] = useState(false);
  const [plotSearch, setPlotSearch] = useState("");
  const [charSearch, setCharSearch] = useState("");
  const [identitySearch, setIdentitySearch] = useState("");

  // 最小化：已填内容（步骤/身份/剧情/阵容/名称）保留，与关闭独立
  const dialog = useDialogMinimize("create-session-wizard", "新建会话", open);

  const steps = useMemo(
    () => (mode === "story" ? ["mode", "identity", "plot", "worldbook", "roster", "finish"] : ["mode", "identity", "worldbook", "roster", "finish"]),
    [mode]
  );

  const filteredPlots = useMemo(() => {
    const q = plotSearch.trim().toLowerCase();
    return q ? plots.filter((p) => p.name.toLowerCase().includes(q) || p.id.toLowerCase().includes(q)) : plots;
  }, [plots, plotSearch]);

  const filteredChars = useMemo(() => {
    const q = charSearch.trim().toLowerCase();
    return q ? characters.filter((c) => charName(c).toLowerCase().includes(q) || c.id.toLowerCase().includes(q)) : characters;
  }, [characters, charSearch]);

  const filteredIdentities = useMemo(() => {
    const q = identitySearch.trim().toLowerCase();
    if (!q) return identities;
    return identities.filter((i) =>
      (i.name || "").toLowerCase().includes(q) ||
      (i.summary || "").toLowerCase().includes(q) ||
      (i.tags || []).some((t) => t.toLowerCase().includes(q))
    );
  }, [identities, identitySearch]);

  // 打开时重置并加载数据
  useEffect(() => {
    if (!open) return;
    setStep(0);
    setMode(chatMode);
    setCombatMode("narrative");
    setIdentity("博士");
    setPlotId("");
    setWorldbookId(null);
    setRoster([]);
    setName("");
    setError("");
    setManualUids([]);
    setFullScope(false);
    setManualQuery("");
    setRosterNote("");
    setLoading(true);
    let cancelled = false;
    Promise.allSettled([
      api.listPlots(),
      api.listWorldbooks(),
      api.getCharacters(),
      api.getPlayerIdentities(),
    ]).then(([p, b, c, i]) => {
      if (cancelled) return;
      if (p.status === "fulfilled") setPlots(p.value || []);
      if (b.status === "fulfilled") setBooks(b.value?.books || []);
      if (c.status === "fulfilled") setCharacters(c.value || []);
      if (i.status === "fulfilled") setIdentities(i.value || []);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [open, api, chatMode]);

  // 阵容变化后重新解析候选范围：防抖 + 过时响应保护（旧响应不会覆盖新结果）
  const { preview: scopePreview, loading: scopeLoading, error: scopeError } = useRosterScopePreview(
    worldbookId || "", roster.filter((key) => key !== identity), manualUids, fullScope,
    open && !!worldbookId,
  );

  if (!open) return null;

  const current = steps[step];
  const isLast = step === steps.length - 1;

  const toggleRoster = (name: string) => {
    setRoster((prev) => (prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]));
  };

  const goNext = () => {
    setError("");
    if (isLast) {
      void handleCreate();
      return;
    }
    setStep((s) => s + 1);
  };

  const handleCreate = async () => {
    setCreating(true);
    setError("");
    try {
      // 世界书绑定、角色入队与候选条目范围由服务端一次完成，首轮不会全量载入。
      // 带上预览指纹：预览已过期时宁可报错，也不静默用一套不同的范围创建会话。
      const session = await api.createSession(
        mode, name.trim(), mode === "story" ? plotId : "", combatMode,
        identity || "博士", worldbookId || "", roster, manualUids,
        scopePreview?.draft_hash || "", fullScope,
      );
      onCreated(session);
    } catch (err: any) {
      setError(err?.message || "创建失败");
      setCreating(false);
    }
  };

  return (
    <div className={`wizard-overlay ${dialog.minimizedClass}`} onClick={onClose}>
      <div
        ref={dialog.containerRef}
        tabIndex={-1}
        className="wizard-panel outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700/70 shrink-0">
          <div>
            <h2 className="text-lg font-bold text-amber-300">新建会话</h2>
            <p className="text-[11px] text-gray-500 mt-0.5">按步骤配置你的故事开端</p>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={dialog.minimize}
              className="text-gray-500 hover:text-gray-300 text-xl leading-none px-2"
              title="最小化（保留已填内容）"
              aria-label="最小化对话框"
            >
              —
            </button>
            <button
              onClick={onClose}
              className="text-gray-500 hover:text-gray-300 text-xl leading-none px-2"
              title="关闭"
              aria-label="关闭对话框"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Steps indicator */}
        <div className="flex items-center gap-2 px-6 py-3 border-b border-gray-700/50 shrink-0">
          {steps.map((s, i) => (
            <div key={s} className="flex items-center gap-2">
              <div className={`step-dot ${i === step ? "active" : i < step ? "done" : ""}`}>
                {i < step ? "✓" : i + 1}
              </div>
              <span className={`step-label ${i === step ? "active" : i < step ? "done" : ""} hidden sm:inline`}>
                {STEP_LABELS[s]}
              </span>
              {i < steps.length - 1 && <div className="w-6 h-px bg-gray-700" />}
            </div>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 lobby-scroll">
          {loading && (
            <div className="flex items-center justify-center py-16 text-gray-500 text-sm">加载中...</div>
          )}

          {!loading && current === "mode" && (
            <div className="space-y-4">
              <p className="text-xs text-gray-400">选择会话模式与战斗模式（创建后不可更改）</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div
                  className={`pick-card p-4 ${mode === "story" ? "selected" : ""}`}
                  onClick={() => { setMode("story"); setPlotId(""); }}
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-xl">📖</span>
                    <span className="font-semibold text-amber-300">剧情模式</span>
                  </div>
                  <p className="text-xs text-gray-400 leading-relaxed">
                    LLM 驱动的完整叙事：绑定主线剧情、任务推进、场景切换与自动叙述。
                  </p>
                </div>
                <div
                  className={`pick-card p-4 ${mode === "free" ? "selected" : ""}`}
                  onClick={() => setMode("free")}
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-xl">🕊️</span>
                    <span className="font-semibold text-purple-300">自由模式</span>
                  </div>
                  <p className="text-xs text-gray-400 leading-relaxed">
                    开放沙盒角色扮演：不绑定剧情，自由选择角色与场景。
                  </p>
                </div>
              </div>

              <div>
                <p className="text-xs text-gray-400 mb-2">战斗模式</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div
                    className={`pick-card p-3 ${combatMode === "narrative" ? "selected" : ""}`}
                    onClick={() => setCombatMode("narrative")}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm">📜</span>
                      <span className="text-sm font-medium text-blue-300">纯剧情叙述</span>
                    </div>
                    <p className="text-[11px] text-gray-500">战斗由叙述呈现，不进入战术回合制。</p>
                  </div>
                  <div
                    className={`pick-card p-3 ${combatMode === "tactical" ? "selected" : ""}`}
                    onClick={() => setCombatMode("tactical")}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm">⚔️</span>
                      <span className="text-sm font-medium text-orange-300">战术模式</span>
                    </div>
                    <p className="text-[11px] text-gray-500">对话中触发战斗时进入 7×7 回合制战术战斗。</p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {!loading && current === "identity" && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs text-gray-400">
                  选择你的玩家身份 — 你将以该角色身份参与对话（默认：博士）
                </p>
                <button
                  onClick={() => { setCurrentView("characters"); onClose(); }}
                  className="text-[11px] px-2 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
                >
                  管理玩家身份
                </button>
              </div>
              {/* 默认身份：博士 */}
              <div
                className={`pick-card p-3 flex items-center gap-3 ${identity === "博士" ? "selected" : ""}`}
                onClick={() => setIdentity("博士")}
              >
                <img
                  src="/api/characters/博士/avatar"
                  alt="博士"
                  className="char-avatar"
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
                />
                <div className="min-w-0">
                  <div className="text-sm font-medium text-gray-200">
                    博士
                    <span className="badge badge-narrative ml-2">默认玩家身份</span>
                  </div>
                  <div className="text-[10px] text-gray-500 mt-0.5 truncate">
                    罗德岛战术指挥官 · 失忆的战场决策者
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-between">
                <p className="text-[11px] text-gray-500">或从已创建的玩家身份中选择</p>
                <input
                  className="input text-xs w-48"
                  placeholder="搜索身份..."
                  value={identitySearch}
                  onChange={(e) => setIdentitySearch(e.target.value)}
                />
              </div>
              {identities.length === 0 ? (
                <p className="text-sm text-gray-500 text-center py-6">
                  暂无自定义玩家身份，可点击右上角「管理玩家身份」创建。
                </p>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 max-h-72 overflow-y-auto lobby-scroll pr-1">
                  {filteredIdentities.map((i) => {
                    const selected = identity === i.id;
                    return (
                      <div
                        key={i.id}
                        className={`char-tile p-2.5 flex flex-col items-center gap-1.5 ${selected ? "selected" : ""}`}
                        onClick={() => setIdentity(i.id)}
                        title={selected ? `以「${i.name}」身份参与对话` : `选择「${i.name}」作为你的身份`}
                      >
                        <div className="relative w-full flex justify-center">
                          <img
                            src={`/api/characters/${encodeURIComponent(i.id)}/avatar`}
                            alt={i.name}
                            className="char-avatar"
                            onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
                          />
                          {selected && (
                            <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-amber-500 text-black text-[10px] font-bold flex items-center justify-center shadow">
                              ✓
                            </span>
                          )}
                        </div>
                        <span className={`text-xs truncate w-full text-center ${selected ? "text-amber-300 font-medium" : "text-gray-200"}`}>
                          {i.name || i.id}
                        </span>
                        {selected && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-amber-600/30 text-amber-300">
                            我的身份
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {!loading && current === "plot" && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs text-gray-400">选择要绑定的剧情（可选）</p>
                <input
                  className="input text-xs w-48"
                  placeholder="搜索剧情..."
                  value={plotSearch}
                  onChange={(e) => setPlotSearch(e.target.value)}
                />
              </div>
              <div
                className={`pick-card p-3 ${plotId === "" ? "selected" : ""}`}
                onClick={() => { setPlotId(""); setRoster([]); }}
              >
                <span className="text-sm text-gray-300 font-medium">不绑定</span>
                <span className="text-[11px] text-gray-500 ml-2">自由探索，不加载任何剧情</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-72 overflow-y-auto lobby-scroll pr-1">
                {filteredPlots.map((p) => (
                  <div
                    key={p.id}
                    className={`pick-card p-3 ${plotId === p.id ? "selected" : ""}`}
                    onClick={() => { setPlotId(p.id); setRoster((p.initial_characters || []).filter((name) => name !== identity && characters.some((c) => charKey(c) === name))); }}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-gray-200 truncate">{p.name}</span>
                      <span className={`badge ${p.category === "main" ? "badge-plot" : "badge-story"}`}>
                        {p.category === "main" ? "主线" : p.category}
                      </span>
                    </div>
                    <div className="text-[10px] text-gray-600 mt-1">{p.id}</div>
                  </div>
                ))}
                {filteredPlots.length === 0 && (
                  <p className="text-gray-500 text-sm col-span-2 text-center py-6">暂无可用剧情</p>
                )}
              </div>
            </div>
          )}

          {!loading && current === "worldbook" && (
            <div className="space-y-3">
              <p className="text-xs text-gray-400">为会话绑定一本世界书（可选）— 关键词触发式设定注入</p>
              <div
                className={`pick-card p-3 ${worldbookId === null ? "selected" : ""}`}
                onClick={() => setWorldbookId(null)}
              >
                <span className="text-sm text-gray-300 font-medium">不绑定</span>
                <span className="text-[11px] text-gray-500 ml-2">不使用世界书注入</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-72 overflow-y-auto lobby-scroll pr-1">
                {books.map((b) => (
                  <div
                    key={b.id}
                    className={`pick-card p-3 ${worldbookId === b.id ? "selected" : ""}`}
                    onClick={() => setWorldbookId(b.id)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-gray-200 truncate">{b.name}</span>
                      {b.is_default && <span className="badge badge-wb">默认</span>}
                    </div>
                    <div className="text-[10px] text-gray-600 mt-1">
                      {b.entry_count} 条目 · 预算 {b.budget_tokens} tokens · {b.source_format}
                    </div>
                  </div>
                ))}
                {books.length === 0 && (
                  <p className="text-gray-500 text-sm col-span-2 text-center py-6">暂无世界书，可前往「世界书」页面创建</p>
                )}
              </div>
            </div>
          )}

          {!loading && current === "roster" && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs text-gray-400">
                  选择入队角色（可选）{roster.length > 0 && <span className="text-amber-300"> — 已选 {roster.length} 名</span>}
                </p>
                <input
                  className="input text-xs w-48"
                  placeholder="搜索角色..."
                  value={charSearch}
                  onChange={(e) => setCharSearch(e.target.value)}
                />
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 max-h-72 overflow-y-auto lobby-scroll pr-1">
                {filteredChars.map((c) => {
                  const key = charKey(c);
                  const selected = roster.includes(key);
                  return (
                    <div
                      key={c.id}
                      className={`char-tile p-2.5 flex flex-col items-center gap-1.5 ${selected ? "selected" : ""}`}
                      onClick={() => toggleRoster(key)}
                      title={selected ? `已入队：${charName(c)}` : `点击将 ${charName(c)} 入队`}
                    >
                      <div className="relative w-full flex justify-center">
                        <img
                          src={`/api/characters/${encodeURIComponent(key)}/avatar`}
                          alt={charName(c)}
                          className="char-avatar"
                          onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
                        />
                        {selected && (
                          <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-amber-500 text-black text-[10px] font-bold flex items-center justify-center shadow">
                            ✓
                          </span>
                        )}
                      </div>
                      <span className={`text-xs truncate w-full text-center ${selected ? "text-amber-300 font-medium" : "text-gray-200"}`}>
                        {charName(c)}
                      </span>
                      {selected && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-amber-600/30 text-amber-300">
                          已入队
                        </span>
                      )}
                    </div>
                  );
                })}
                {filteredChars.length === 0 && (
                  <p className="text-gray-500 text-sm col-span-full text-center py-6">暂无可用角色，可前往「资产」页面导入角色卡</p>
                )}
              </div>

              {!worldbookId && <p className="text-[11px] text-gray-500">
                未绑定世界书：阵容不会影响设定载入。上一步可以选一本世界书。
              </p>}

              {worldbookId && <div className="wbg-card space-y-3" aria-label="候选范围">
                <div className="wbg-card-head">
                  <div>
                    <h4>这次会载入什么</h4>
                    <p className="wbg-help">来自服务端按当前阵容的真实解析，前端不再自己走一遍遍历。</p>
                  </div>
                  {scopeLoading && <span className="wbg-chip">重新计算…</span>}
                </div>

                {scopeError && <div role="alert" className="wbg-notice wbg-error"><span>候选范围预览失败：{scopeError}</span></div>}

                {scopePreview && <>
                  <div className="wbg-config-metrics">
                    <span>候选条目 <b>{scopePreview.entry_count}</b></span>
                    <span>全书可用 <b>{scopePreview.full_entry_count}</b></span>
                    <span>估算 token <b>{scopePreview.resolved_estimated_tokens.toLocaleString()}</b></span>
                    <span>未选中 <b>{scopePreview.unselected_count ?? 0}</b></span>
                  </div>

                  {!!scopePreview.active_roots?.length && <p className="wbg-help">
                    激活起点：{scopePreview.active_roots.map((root) => root.entry_uid).join("、")}
                    （{scopePreview.active_roots.length} 个）
                  </p>}

                  {!!scopePreview.display_tree?.length && <details className="wbg-details">
                    <summary>载入树 <span>{scopePreview.display_tree.length}</span></summary>
                    <ul className="wbg-tree-list">{scopePreview.display_tree.slice(0, 80).map((node) => <li key={node.uid}
                      style={{ paddingLeft: 8 + Math.min(node.depth, 8) * 14 }}>
                      <span className={node.is_root ? "wbg-tree-root" : ""}>{node.name || node.uid}</span>
                      <small>{(scopePreview.selection_reasons?.[node.uid] || []).map(reasonLabel).join("、")}</small>
                    </li>)}</ul>
                    {scopePreview.display_tree.length > 80 && <p className="wbg-help">仅显示前 80 个节点。</p>}
                  </details>}

                  {!!scopePreview.source_expansions?.length && <details className="wbg-details">
                    <summary>旧格式导入源展开 <span>{scopePreview.source_expansions.length}</span></summary>
                    {scopePreview.source_expansions.map((source) => <p key={source.entry_uid} className="wbg-help">
                      {source.name || source.entry_uid} · 深度 {source.max_depth} · 展开 {source.entries.length} 条
                    </p>)}
                  </details>}

                  <details className="wbg-details">
                    <summary>为什么载入 / 为什么不载入</summary>
                    <p className="wbg-help">
                      条目没被选中不是错误：按需载入下，只有被起点激活或依赖补齐的条目才会进入候选。
                      可用「手动追加」把个别条目只加进本次会话。
                    </p>
                    {!!scopePreview.unselected_entries?.length && <ul className="wbg-build-issues">
                      {scopePreview.unselected_entries.slice(0, 40).map((entry) => <li key={entry.uid}>
                        <b>未载入</b><span>{entry.name || entry.uid}</span>
                      </li>)}
                    </ul>}
                  </details>
                </>}

                {/* 手动追加：只作用于本会话，可逐条取消 */}
                <div className="wbg-action-row">
                  <div>
                    <strong>手动追加条目（只作用于本会话）</strong>
                    <small>不会写回世界书规则；取消追加只影响这次创建。</small>
                  </div>
                </div>
                <div className="wbg-action-controls">
                  <input className="input text-xs flex-1" list="wizard-entry-targets" placeholder="搜索条目名称或 UID"
                    aria-label="手动追加条目" value={manualQuery} onChange={(e) => setManualQuery(e.target.value)} />
                  <datalist id="wizard-entry-targets">
                    {(scopePreview?.unselected_entries || []).slice(0, 300).map((entry) => <option key={entry.uid} value={entry.uid}>
                      {entry.name || entry.uid}
                    </option>)}
                  </datalist>
                  <button className="btn px-3 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-200"
                    disabled={!manualQuery.trim()} onClick={() => {
                      const uid = manualQuery.trim();
                      setManualQuery("");
                      if (manualUids.includes(uid)) { setRosterNote("这个条目已经在手动追加列表里。"); return; }
                      const known = scopePreview?.entry_names?.[uid]
                        || scopePreview?.unselected_entries?.some((entry) => entry.uid === uid);
                      if (!known) { setRosterNote(`没有找到条目「${uid}」。请从下拉建议里选择，或核对 UID。`); return; }
                      setManualUids((current) => [...current, uid]);
                      setRosterNote(`已手动追加「${scopePreview?.entry_names?.[uid] || uid}」，仅本次会话生效。`);
                    }}>追加</button>
                </div>
                {!!manualUids.length && <div className="wbg-roster-chips">
                  {manualUids.map((uid) => <span key={uid} className="wbg-fixed-chip">
                    <span>{scopePreview?.entry_names?.[uid] || uid}</span>
                    <button aria-label={`取消追加 ${uid}`} onClick={() => {
                      const reasons = scopePreview?.selection_reasons?.[uid] || [];
                      const alsoRequired = reasons.some((reason) => reason !== "manual");
                      setManualUids((current) => current.filter((item) => item !== uid));
                      setRosterNote(alsoRequired
                        ? `已取消手动追加「${uid}」，但它仍会因${reasons.map(reasonLabel).join("、")}被载入 —— 必要关系要用的条目不会因为取消追加而消失。`
                        : `已取消手动追加「${uid}」。`);
                    }}>×</button>
                  </span>)}
                </div>}
                {rosterNote && <p className="wbg-help" role="status">{rosterNote}</p>}

                <div className="wbg-action-row">
                  <div>
                    <strong>本次会话全量兼容</strong>
                    <small>显式选择：这次载入全部启用条目。只影响本会话，不改这本书的规则。</small>
                  </div>
                  <button className="wbg-button" aria-pressed={fullScope} onClick={() => {
                    setFullScope(!fullScope);
                    setRosterNote(fullScope ? "已关闭全量兼容，回到按需载入。" : "已开启全量兼容：本次会话会载入全部启用条目。");
                  }}>{fullScope ? "已开启 · 点击关闭" : "开启全量兼容"}</button>
                </div>

                {!!scopePreview?.warnings?.length && <div className="space-y-1">
                  {scopePreview.warnings.map((warning) => <p key={warning} className="text-[11px] text-amber-300">{warning}</p>)}
                </div>}
              </div>}
            </div>
          )}

          {!loading && current === "finish" && (
            <div className="space-y-4">
              <div>
                <p className="text-xs text-gray-400 mb-1.5">会话名称</p>
                <input
                  className="input text-sm"
                  placeholder={mode === "story" && plotId ? (plots.find((p) => p.id === plotId)?.name || "未命名会话") : "未命名会话"}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoFocus
                />
              </div>
              <div className="detail-section p-4 space-y-2">
                <p className="text-[11px] text-gray-500 tracking-wider">配置预览</p>
                <div className="flex flex-wrap gap-2">
                  <span className={`badge ${mode === "story" ? "badge-story" : "badge-free"}`}>
                    {mode === "story" ? "📖 剧情模式" : "🕊️ 自由模式"}
                  </span>
                  <span className="badge badge-narrative">🎭 玩家身份：{identity || "博士"}</span>
                  <span className={`badge ${combatMode === "tactical" ? "badge-tactical" : "badge-narrative"}`}>
                    {combatMode === "tactical" ? "⚔️ 战术模式" : "📜 纯剧情"}
                  </span>
                  {mode === "story" && plotId && (
                    <span className="badge badge-plot">🗺 {plots.find((p) => p.id === plotId)?.name || plotId}</span>
                  )}
                  {worldbookId && (
                    <span className="badge badge-wb">📖 {books.find((b) => b.id === worldbookId)?.name || worldbookId}</span>
                  )}
                  {roster.length > 0 && (
                    <>
                      <span className="badge badge-narrative">👥 已入队 {roster.length} 名</span>
                      <p className="text-[11px] text-gray-400 w-full mt-1">
                        角色：{roster.map((k) => {
                          const c = characters.find((x) => charKey(x) === k);
                          return c ? charName(c) : k;
                        }).join("、")}
                      </p>
                    </>
                  )}
                  {!!manualUids.length && (
                    <span className="badge badge-wb">✋ 手动追加 {manualUids.length} 条（仅本会话）</span>
                  )}
                  {fullScope && <span className="badge badge-tactical">📚 本次会话全量兼容</span>}
                </div>
              </div>
              {worldbookId ? scopePreview ? <WorldBookScopePreview value={scopePreview} /> : <p className="text-xs text-gray-400">{scopeError || "计算导入范围中…"}</p> : <p className="text-xs text-gray-400">未绑定世界书：此次会话不会载入世界书条目。</p>}
              {error && <p className="text-xs text-red-400">{error}</p>}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-700/70 shrink-0">
          <button
            onClick={onClose}
            className="text-xs text-gray-500 hover:text-gray-300 px-3 py-1.5 rounded transition-colors"
          >
            取消
          </button>
          <div className="flex items-center gap-2">
            {step > 0 && (
              <button
                onClick={() => setStep((s) => s - 1)}
                disabled={creating}
                className="text-xs px-4 py-2 rounded-lg bg-gray-700/60 text-gray-300 hover:bg-gray-700 transition-colors"
              >
                上一步
              </button>
            )}
            <button
              onClick={goNext}
              disabled={creating}
              className={`btn px-6 py-2 text-sm ${isLast ? "btn-hero" : "bg-blue-600 hover:bg-blue-500 text-white"}`}
            >
              {creating ? "创建中..." : isLast ? "创建并进入" : "下一步"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
