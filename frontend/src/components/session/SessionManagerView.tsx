/**
 * 会话大厅 — 游戏主菜单式的会话管理界面
 *
 * 承担全部会话级管理：列表/搜索/批量删除、新建向导、会话详情
 * （世界书绑定、角色阵容、重命名/导出/导入/删除）、进入对话。
 * 对话页因此不再承担会话列表，保持干净。
 */
import { useState, useEffect, useMemo, useCallback } from "react";
import { useAppStore } from "../../stores/appStore";
import { useApi } from "../../hooks/useApi";
import type { PlotInfo, WorldBookSummary, Session } from "../../types";
import CreateSessionWizard from "./CreateSessionWizard";

interface CharItem {
  id: string;
  name: string;
}

const AVATAR_URL = (name: string) => `/api/characters/${encodeURIComponent(name)}/avatar`;

function formatDate(ts: number): string {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function SessionManagerView() {
  const { sessions, activeSessionId, chatMode, setSessions, setActiveSession, setCurrentView, setIndexSessionId, setChatMode, setCombatContext } =
    useAppStore();
  const api = useApi();

  // ── 视图状态 ──
  const [tab, setTab] = useState<"story" | "free">(chatMode);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(activeSessionId);
  const [wizardOpen, setWizardOpen] = useState(false);

  // ── 批量管理 ──
  const [batchMode, setBatchMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);

  // ── 数据 ──
  const [plots, setPlots] = useState<PlotInfo[]>([]);
  const [books, setBooks] = useState<WorldBookSummary[]>([]);
  const [characters, setCharacters] = useState<CharItem[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerSearch, setPickerSearch] = useState("");

  // ── 详情操作状态 ──
  const [renaming, setRenaming] = useState(false);
  const [renameDraft, setRenameDraft] = useState("");
  const [busyAction, setBusyAction] = useState<string | null>(null);

  // 加载剧情/世界书/角色库
  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([api.listPlots(), api.listWorldbooks(), api.getCharacters()]).then(([p, b, c]) => {
      if (cancelled) return;
      if (p.status === "fulfilled") setPlots(p.value || []);
      if (b.status === "fulfilled") setBooks(b.value?.books || []);
      if (c.status === "fulfilled") setCharacters(c.value || []);
    });
    return () => { cancelled = true; };
  }, [api]);

  const filteredSessions = useMemo(() => {
    let list = sessions.filter((s) => s.mode === tab);
    const q = search.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (s) =>
          (s.name || "").toLowerCase().includes(q) ||
          (s.plot_id || "").toLowerCase().includes(q) ||
          (s.characters || []).some((c: any) => String(c).toLowerCase().includes(q))
      );
    }
    return [...list].sort((a, b) => b.created_at - a.created_at);
  }, [sessions, tab, search]);

  const selected = sessions.find((s) => s.id === selectedId) || null;
  const plotName = (plotId: string | null) => plots.find((p) => p.id === plotId)?.name || plotId || "";
  const bookName = (bookId: string | null | undefined) => books.find((b) => b.id === bookId)?.name || "";

  // ── 会话操作 ──

  const enterSession = useCallback((id: string) => {
    const s = sessions.find((x) => x.id === id);
    setActiveSession(id);
    if (s) setChatMode(s.mode);
    setCurrentView("chat");
  }, [sessions, setActiveSession, setChatMode, setCurrentView]);

  /** 进入进行中战斗（全屏沉浸战场） */
  const enterCombat = useCallback((id: string) => {
    const s = sessions.find((x) => x.id === id);
    setActiveSession(id);
    if (s) setChatMode(s.mode);
    setCombatContext({ sessionId: id, testId: null, state: null, uiMode: "VIEWING", selectedCardIndex: null, selectedUnitId: null });
    setCurrentView("combat");
  }, [sessions, setActiveSession, setChatMode, setCombatContext, setCurrentView]);

  /** 战斗演练：无会话的测试战场（沿用 CombatView 设置屏） */
  const enterPractice = useCallback(() => {
    setCombatContext({ sessionId: null, testId: null, state: null, uiMode: "VIEWING", selectedCardIndex: null, selectedUnitId: null });
    setCurrentView("combat");
  }, [setCombatContext, setCurrentView]);

  const handleCreated = useCallback((session: Session) => {
    setSessions([...sessions, session]);
    setSelectedId(session.id);
    enterSession(session.id);
  }, [sessions, setSessions, enterSession]);

  const handleRename = async () => {
    if (!selected || !renameDraft.trim()) { setRenaming(false); return; }
    setBusyAction("rename");
    try {
      await api.renameSession(selected.id, renameDraft.trim());
      setSessions(sessions.map((s) => (s.id === selected.id ? { ...s, name: renameDraft.trim() } : s)));
      setRenaming(false);
    } catch (err: any) {
      alert("重命名失败: " + (err?.message || "未知错误"));
    } finally {
      setBusyAction(null);
    }
  };

  const handleDelete = async (id: string) => {
    const s = sessions.find((x) => x.id === id);
    if (!confirm(`确定删除会话「${s?.name || "未命名"}」？此操作不可恢复。`)) return;
    setBusyAction("delete");
    try {
      await api.deleteSession(id);
      useAppStore.getState().clearSessionStream(id);
      const next = sessions.filter((x) => x.id !== id);
      setSessions(next);
      if (selectedId === id) setSelectedId(next[0]?.id || null);
      if (activeSessionId === id) setActiveSession(null);
      try { localStorage.removeItem(`ark_chat_${s?.mode || "free"}_${id}`); } catch {}
    } catch (err: any) {
      alert("删除失败: " + (err?.message || "未知错误"));
    } finally {
      setBusyAction(null);
    }
  };

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!confirm(`确定删除选中的 ${selectedIds.size} 个会话？此操作不可恢复。`)) return;
    setBatchDeleting(true);
    try {
      for (const id of selectedIds) {
        await api.deleteSession(id);
        useAppStore.getState().clearSessionStream(id);
        try { localStorage.removeItem(`ark_chat_${tab}_${id}`); } catch {}
      }
      const next = sessions.filter((s) => !selectedIds.has(s.id));
      setSessions(next);
      if (selectedId && selectedIds.has(selectedId)) setSelectedId(next[0]?.id || null);
      if (activeSessionId && selectedIds.has(activeSessionId)) setActiveSession(null);
      setSelectedIds(new Set());
      setBatchMode(false);
    } catch (err: any) {
      alert("批量删除失败: " + (err?.message || "未知错误"));
    } finally {
      setBatchDeleting(false);
    }
  };

  const handleImport = async (file: File) => {
    try {
      const imported = await api.importSession(file);
      const fresh = await api.listSessions();
      setSessions(fresh);
      const id = imported?.session_id || imported?.id;
      if (id) { setSelectedId(id); setActiveSession(id); }
      alert("存档导入成功");
    } catch (err: any) {
      alert("导入失败: " + (err?.message || "未知错误"));
    }
  };

  // ── 世界书绑定 ──

  const bindBook = async (bookId: string | null) => {
    if (!selected) return;
    setBusyAction(bookId ? `bind-${bookId}` : "unbind");
    try {
      // 解绑时需传当前绑定的真实 book id（bound=false 回落全局默认）
      const res = await api.bindWorldbook(bookId || selected.worldbook_id || "", selected.id, !!bookId);
      setSessions(sessions.map((s) => (s.id === selected.id ? { ...s, worldbook_id: res.worldbook_id } : s)));
    } catch (err: any) {
      alert("绑定失败: " + (err?.message || "未知错误"));
    } finally {
      setBusyAction(null);
    }
  };

  // ── 角色阵容 ──

  const addCharacter = async (name: string) => {
    if (!selected) return;
    setBusyAction(`add-${name}`);
    try {
      await api.loadCharacter(selected.id, name);
      const fresh = await api.getSession(selected.id);
      setSessions(sessions.map((s) => (s.id === selected.id ? { ...s, characters: fresh.characters || s.characters } : s)));
    } catch (err: any) {
      alert("加载角色失败: " + (err?.message || "未知错误"));
    } finally {
      setBusyAction(null);
    }
  };

  const removeCharacter = async (name: string) => {
    if (!selected) return;
    if (!confirm(`将角色「${name}」移出本会话场景？`)) return;
    setBusyAction(`remove-${name}`);
    try {
      await api.unloadCharacter(selected.id, name);
      const fresh = await api.getSession(selected.id);
      setSessions(sessions.map((s) => (s.id === selected.id ? { ...s, characters: fresh.characters || s.characters } : s)));
    } catch (err: any) {
      alert("移出角色失败: " + (err?.message || "未知错误"));
    } finally {
      setBusyAction(null);
    }
  };

  const filteredPickerChars = useMemo(() => {
    const q = pickerSearch.trim().toLowerCase();
    return q
      ? characters.filter((c) => c.name.toLowerCase().includes(q) || c.id.toLowerCase().includes(q))
      : characters;
  }, [characters, pickerSearch]);

  const tabCounts = useMemo(() => ({
    story: sessions.filter((s) => s.mode === "story").length,
    free: sessions.filter((s) => s.mode === "free").length,
  }), [sessions]);

  const roster = useMemo(() => {
    const raw = selected?.characters || [];
    return raw.map((c: any) => (typeof c === "string" ? c : c.name || c.id || ""));
  }, [selected]);

  return (
    <div className="h-full flex flex-col session-manager-view">
      {/* ═══ 英雄横幅（预留壁纸位：覆盖 --session-hero-wallpaper 即可） ═══ */}
      <header className="session-hero px-6 md:px-10 py-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="session-hero-title text-2xl md:text-3xl">会话大厅</h1>
          <p className="session-hero-sub text-[11px] mt-1.5">ARKNIGHTS TAVERN · 选择或创建你的故事</p>
        </div>
        <div className="flex items-center gap-2 md:gap-3">
          <div className="hidden md:flex items-center gap-2">
            <span className="badge badge-story">剧情 {tabCounts.story}</span>
            <span className="badge badge-free">自由 {tabCounts.free}</span>
          </div>
          <label className="btn btn-ghost text-xs cursor-pointer" title="导入会话存档（zip）">
            📂 导入存档
            <input
              type="file"
              accept=".zip"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) { void handleImport(f); e.target.value = ""; }
              }}
            />
          </label>
          <button
            onClick={enterPractice}
            className="btn btn-ghost text-xs"
            title="战斗演练：不入会话的测试战场"
          >
            ⚔ 战斗演练
          </button>
          <button onClick={() => setWizardOpen(true)} className="btn btn-hero px-5 py-2 text-sm">
            ＋ 新建会话
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* ═══ 左侧：会话列表 ═══ */}
        <aside className="w-80 xl:w-96 border-r border-gray-700/60 flex flex-col shrink-0">
          <div className="px-4 pt-4 pb-2 space-y-2 shrink-0">
            {/* 模式 Tab */}
            <div className="flex gap-1 p-1 rounded-lg bg-gray-800/80 border border-gray-700/70">
              {(["story", "free"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => { setTab(m); setSearch(""); setSelectedIds(new Set()); }}
                  className={`flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                    tab === m
                      ? m === "story"
                        ? "bg-amber-600/30 text-amber-300 border border-amber-500/40"
                        : "bg-purple-600/30 text-purple-300 border border-purple-500/40"
                      : "text-gray-500 hover:text-gray-300"
                  }`}
                >
                  {m === "story" ? "📖 剧情" : "🕊️ 自由"}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <input
                className="input text-xs py-1.5"
                placeholder="搜索会话 / 剧情 / 角色..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <button
                onClick={() => { setBatchMode((v) => !v); setSelectedIds(new Set()); }}
                className={`text-xs px-2.5 py-1.5 rounded-md border transition-colors shrink-0 ${
                  batchMode
                    ? "border-red-500/40 bg-red-600/15 text-red-300"
                    : "border-gray-700 bg-gray-800 text-gray-500 hover:text-gray-300"
                }`}
                title="批量管理"
              >
                ☑
              </button>
            </div>
            {/* 批量操作栏 */}
            {batchMode && (
              <div className="flex items-center justify-between px-2 py-1.5 rounded-lg bg-red-900/20 border border-red-800/40">
                <span className="text-[11px] text-red-300">
                  已选 {selectedIds.size} 个
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setSelectedIds(new Set(filteredSessions.map((s) => s.id)))}
                    className="text-[11px] text-gray-400 hover:text-gray-200"
                  >
                    全选
                  </button>
                  <button
                    onClick={handleBatchDelete}
                    disabled={selectedIds.size === 0 || batchDeleting}
                    className="text-[11px] px-2 py-0.5 rounded bg-red-700/80 hover:bg-red-600 text-white disabled:opacity-50"
                  >
                    {batchDeleting ? "删除中..." : "删除"}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* 卡片列表 */}
          <div className="flex-1 overflow-y-auto px-3 pb-4 space-y-2 lobby-scroll">
            {filteredSessions.length === 0 && (
              <div className="lobby-empty p-6 text-center">
                <p className="text-sm text-gray-500 mb-3">{search ? "未找到匹配的会话" : tab === "story" ? "还没有剧情会话" : "还没有自由会话"}</p>
                <button onClick={() => setWizardOpen(true)} className="btn-hero btn text-xs px-4 py-1.5">
                  ＋ 新建{tab === "story" ? "剧情" : "自由"}会话
                </button>
              </div>
            )}
            {filteredSessions.map((s) => (
              <div
                key={s.id}
                className={`session-card p-3.5 ${selectedId === s.id ? "selected" : ""} ${activeSessionId === s.id && selectedId !== s.id ? "active-session" : ""}`}
                onClick={() => setSelectedId(s.id)}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      {batchMode && (
                        <input
                          type="checkbox"
                          className="checkbox"
                          checked={selectedIds.has(s.id)}
                          onChange={(e) => {
                            e.stopPropagation();
                            setSelectedIds((prev) => {
                              const next = new Set(prev);
                              if (next.has(s.id)) next.delete(s.id);
                              else next.add(s.id);
                              return next;
                            });
                          }}
                          onClick={(e) => e.stopPropagation()}
                        />
                      )}
                      <span className="text-sm font-medium text-gray-100 truncate">{s.name || "未命名会话"}</span>
                      {activeSessionId === s.id && (
                        <span className="badge badge-narrative shrink-0" title="当前对话中的会话">● 进行中</span>
                      )}
                      {s.in_combat && (
                        <span className="badge badge-tactical shrink-0 animate-pulse">⚔ 战斗中</span>
                      )}
                    </div>
                    <div className="text-[10px] text-gray-600 mt-0.5">{formatDate(s.created_at)}</div>
                  </div>
                  {!batchMode && (
                    <div className="flex items-center gap-1.5 shrink-0">
                      {s.in_combat && (
                        <button
                          onClick={(e) => { e.stopPropagation(); enterCombat(s.id); }}
                          className="btn text-[11px] px-3 py-1 bg-red-700/80 hover:bg-red-600 text-white animate-pulse"
                          title="进入战斗（全屏战场）"
                        >
                          ⚔ 战斗
                        </button>
                      )}
                      <button
                        onClick={(e) => { e.stopPropagation(); enterSession(s.id); }}
                        className="btn-hero btn text-[11px] px-3 py-1 shrink-0"
                        title="进入对话"
                      >
                        进入
                      </button>
                    </div>
                  )}
                </div>

                <div className="flex flex-wrap gap-1.5 mt-2">
                  <span className={`badge ${s.mode === "story" ? "badge-story" : "badge-free"}`}>
                    {s.mode === "story" ? "📖 剧情" : "🕊️ 自由"}
                  </span>
                  <span className={`badge ${s.combat_mode === "tactical" ? "badge-tactical" : "badge-narrative"}`}>
                    {s.combat_mode === "tactical" ? "⚔ 战术" : "📜 纯剧情"}
                  </span>
                  {s.plot_id && <span className="badge badge-plot">🗺 {plotName(s.plot_id)}</span>}
                  {s.worldbook_id && <span className="badge badge-wb">📖 世界书</span>}
                </div>

                {(s.characters?.length > 0) && (
                  <div className="flex items-center justify-between mt-2.5">
                    <div className="flex items-center">
                      {s.characters.slice(0, 5).map((c: any) => {
                        const name = typeof c === "string" ? c : c.name || c.id || "";
                        return (
                          <img
                            key={name}
                            src={AVATAR_URL(name)}
                            alt={name}
                            title={name}
                            className="char-avatar sm -ml-1.5 first:ml-0 border-gray-900"
                            onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
                          />
                        );
                      })}
                      {s.characters.length > 5 && (
                        <span className="text-[10px] text-gray-500 ml-1.5">+{s.characters.length - 5}</span>
                      )}
                    </div>
                    <div className="text-[10px] text-gray-600">
                      {s.narration_count ?? 0} 轮{s.total_usage?.total_tokens ? ` · ${(s.total_usage.total_tokens / 1000).toFixed(1)}k tokens` : ""}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </aside>

        {/* ═══ 右侧：会话详情与管理 ═══ */}
        <section className="flex-1 overflow-y-auto lobby-scroll p-6">
          {!selected ? (
            <div className="h-full flex flex-col items-center justify-center lobby-empty m-4">
              <div className="text-4xl mb-3">🗺️</div>
              <p className="text-gray-400 text-sm mb-1">选择一个会话查看详情</p>
              <p className="text-gray-600 text-xs mb-4">或在左侧新建一个故事</p>
              <button onClick={() => setWizardOpen(true)} className="btn-hero btn text-sm px-5 py-2">
                ＋ 新建会话
              </button>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto space-y-5">
              {/* 标题 + 主操作 */}
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="min-w-0">
                  {renaming ? (
                    <div className="flex items-center gap-2">
                      <input
                        className="input text-lg py-1 w-64"
                        value={renameDraft}
                        onChange={(e) => setRenameDraft(e.target.value)}
                        onBlur={() => void handleRename()}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") { e.preventDefault(); void handleRename(); }
                          if (e.key === "Escape") setRenaming(false);
                        }}
                        autoFocus
                      />
                    </div>
                  ) : (
                    <h2
                      className="text-xl font-bold text-gray-100 truncate cursor-text"
                      onDoubleClick={() => { setRenameDraft(selected.name || ""); setRenaming(true); }}
                      title="双击重命名"
                    >
                      {selected.name || "未命名会话"}
                    </h2>
                  )}
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    <span className={`badge ${selected.mode === "story" ? "badge-story" : "badge-free"}`}>
                      {selected.mode === "story" ? "📖 剧情模式" : "🕊️ 自由模式"}
                    </span>
                    <span className={`badge ${selected.combat_mode === "tactical" ? "badge-tactical" : "badge-narrative"}`}>
                      {selected.combat_mode === "tactical" ? "⚔️ 战术模式" : "📜 纯剧情"}
                    </span>
                    {selected.plot_id && <span className="badge badge-plot">🗺 {plotName(selected.plot_id)}</span>}
                    {selected.in_combat && <span className="badge badge-tactical animate-pulse">⚔ 战斗中</span>}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {selected.in_combat && (
                    <button
                      onClick={() => enterCombat(selected.id)}
                      className="btn px-5 py-2 text-sm bg-red-700/80 hover:bg-red-600 text-white animate-pulse"
                    >
                      ⚔ 进入战斗
                    </button>
                  )}
                  <button onClick={() => enterSession(selected.id)} className="btn-hero btn px-6 py-2 text-sm">
                    ▶ 进入对话
                  </button>
                </div>
              </div>

              {/* 统计网格 */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
                <div className="stat-cell px-3 py-2.5">
                  <div className="text-[10px] text-gray-500">创建时间</div>
                  <div className="text-xs text-gray-200 mt-0.5">{formatDate(selected.created_at)}</div>
                </div>
                <div className="stat-cell px-3 py-2.5">
                  <div className="text-[10px] text-gray-500">叙述轮数</div>
                  <div className="text-xs text-gray-200 mt-0.5">{selected.narration_count ?? 0} 轮</div>
                </div>
                <div className="stat-cell px-3 py-2.5">
                  <div className="text-[10px] text-gray-500">Token 用量</div>
                  <div className="text-xs text-gray-200 mt-0.5">
                    {selected.total_usage?.total_tokens ? `${(selected.total_usage.total_tokens / 1000).toFixed(1)}k` : "—"}
                  </div>
                </div>
                <div className="stat-cell px-3 py-2.5">
                  <div className="text-[10px] text-gray-500">场景角色</div>
                  <div className="text-xs text-gray-200 mt-0.5">{roster.length} 名</div>
                </div>
              </div>

              {/* 世界书绑定 */}
              <div className="detail-section p-4">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-semibold text-gray-300">📖 世界书绑定</h3>
                  <span className="text-[10px] text-gray-600">未绑定时回落到全局默认书</span>
                </div>
                <div className="space-y-1.5 max-h-56 overflow-y-auto lobby-scroll pr-1">
                  <button
                    onClick={() => void bindBook(null)}
                    disabled={!!busyAction}
                    className={`w-full text-left px-3 py-2 rounded-lg text-xs transition-colors border ${
                      !selected.worldbook_id
                        ? "border-amber-500/50 bg-amber-600/15 text-amber-300"
                        : "border-gray-700 bg-gray-800/50 text-gray-400 hover:bg-gray-700/50"
                    }`}
                  >
                    不绑定（回落全局默认）
                  </button>
                  {books.map((b) => (
                    <button
                      key={b.id}
                      onClick={() => void bindBook(b.id)}
                      disabled={!!busyAction}
                      className={`w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-xs transition-colors border ${
                        selected.worldbook_id === b.id
                          ? "border-emerald-500/50 bg-emerald-600/10 text-emerald-300"
                          : "border-gray-700 bg-gray-800/50 text-gray-400 hover:bg-gray-700/50"
                      }`}
                    >
                      <span className="flex items-center gap-2 min-w-0">
                        <span className="truncate">{b.name}</span>
                        {b.is_default && <span className="badge badge-wb shrink-0">默认</span>}
                      </span>
                      <span className="text-[10px] text-gray-600 shrink-0">
                        {b.entry_count} 条目{busyAction === `bind-${b.id}` ? " · 绑定中..." : ""}
                      </span>
                    </button>
                  ))}
                  {books.length === 0 && (
                    <p className="text-[11px] text-gray-600 py-2">暂无世界书，可前往「世界书」页面创建或导入</p>
                  )}
                </div>
              </div>

              {/* 角色阵容 */}
              <div className="detail-section p-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-gray-300">👥 角色阵容</h3>
                  <button
                    onClick={() => { setPickerOpen(true); setPickerSearch(""); }}
                    className="text-xs px-3 py-1.5 rounded-lg bg-blue-600/25 text-blue-300 border border-blue-500/30 hover:bg-blue-600/40 transition-colors"
                  >
                    ＋ 添加角色
                  </button>
                </div>
                {roster.length === 0 ? (
                  <p className="text-[11px] text-gray-600 py-3 text-center">
                    场景中还没有角色{busyAction?.startsWith("add-") ? "，正在加载..." : ""}
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {roster.map((name) => (
                      <div
                        key={name}
                        className="flex items-center gap-2 pl-1.5 pr-2 py-1.5 rounded-full bg-gray-800/80 border border-gray-700"
                      >
                        <img
                          src={AVATAR_URL(name)}
                          alt={name}
                          className="char-avatar sm"
                          onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
                        />
                        <span className="text-xs text-gray-200 max-w-32 truncate">{name}</span>
                        {selected.active_character === name && (
                          <span className="badge badge-narrative shrink-0">当前</span>
                        )}
                        <button
                          onClick={() => void removeCharacter(name)}
                          disabled={!!busyAction}
                          className="text-gray-600 hover:text-red-400 text-sm leading-none px-0.5 transition-colors"
                          title="移出场景"
                        >
                          ✕
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                <p className="text-[10px] text-gray-600 mt-2.5">
                  提示：在对话页的「角色面板」中可切换当前发言角色、编辑人设覆盖。
                </p>
              </div>

              {/* 危险区 / 工具 */}
              <div className="detail-section p-4">
                <h3 className="text-sm font-semibold text-gray-300 mb-3">🛠 会话工具</h3>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => { setRenameDraft(selected.name || ""); setRenaming(true); }}
                    className="text-xs px-3 py-1.5 rounded-lg bg-gray-700/60 text-gray-300 hover:bg-gray-700 transition-colors"
                  >
                    ✎ 重命名
                  </button>
                  <button
                    onClick={() => { void api.exportSession(selected.id); }}
                    className="text-xs px-3 py-1.5 rounded-lg bg-gray-700/60 text-gray-300 hover:bg-gray-700 transition-colors"
                  >
                    💾 导出存档
                  </button>
                  {selected.mode === "story" && (
                    <button
                      onClick={() => { setIndexSessionId(selected.id); setCurrentView("index"); }}
                      className="text-xs px-3 py-1.5 rounded-lg bg-gray-700/60 text-gray-300 hover:bg-gray-700 transition-colors"
                    >
                      🔗 索引配置
                    </button>
                  )}
                  <button
                    onClick={() => void handleDelete(selected.id)}
                    disabled={busyAction === "delete"}
                    className="text-xs px-3 py-1.5 rounded-lg bg-red-700/30 text-red-300 border border-red-700/40 hover:bg-red-700/50 transition-colors"
                  >
                    {busyAction === "delete" ? "删除中..." : "🗑 删除会话"}
                  </button>
                </div>
              </div>
            </div>
          )}
        </section>
      </div>

      {/* 新建向导 */}
      <CreateSessionWizard open={wizardOpen} onClose={() => setWizardOpen(false)} onCreated={handleCreated} />

      {/* 添加角色选择器 */}
      {pickerOpen && selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setPickerOpen(false)}>
          <div
            className="bg-gray-800 border border-gray-700 rounded-xl w-[560px] max-h-[640px] flex flex-col shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700">
              <h2 className="text-base font-semibold">添加角色入队</h2>
              <button onClick={() => setPickerOpen(false)} className="text-gray-500 hover:text-gray-300 text-lg leading-none">✕</button>
            </div>
            <div className="px-5 pt-3 pb-2">
              <input
                className="input text-sm"
                placeholder="搜索角色..."
                value={pickerSearch}
                onChange={(e) => setPickerSearch(e.target.value)}
                autoFocus
              />
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-2 lobby-scroll">
              {filteredPickerChars.length === 0 && (
                <p className="text-gray-500 text-sm text-center py-8">
                  {pickerSearch ? "未找到匹配角色" : "暂无可用角色，请先在「资产」页面导入角色卡"}
                </p>
              )}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 pb-3">
                {filteredPickerChars
                  .filter((c) => !roster.includes(c.name))
                  .map((c) => (
                    <div
                      key={c.id}
                      className={`char-tile p-2.5 flex items-center gap-2 ${busyAction === `add-${c.name}` ? "opacity-60" : ""}`}
                      onClick={() => void addCharacter(c.name)}
                      title="点击加入本会话"
                    >
                      <img
                        src={AVATAR_URL(c.name)}
                        alt={c.name}
                        className="char-avatar sm"
                        onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
                      />
                      <div className="min-w-0">
                        <div className="text-xs text-gray-200 truncate">{c.name}</div>
                        <div className="text-[10px] text-gray-600 truncate">{busyAction === `add-${c.name}` ? "加载中..." : "点击入队"}</div>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
