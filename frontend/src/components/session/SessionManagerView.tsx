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
import { useCombatResume } from "../../hooks/useCombatResume";
import type { PlotInfo, WorldBookSummary, Session, CombatResumeTestDTO, CombatResumeSummaryDTO } from "../../types";
import CreateSessionWizard from "./CreateSessionWizard";
import { useDialogMinimize } from "../../hooks/useDialogMinimize";

interface CharItem {
  id: string;
  name: string;
  title?: string;
}

/** 角色显示名（/api/characters 返回 title/name，兼容两者） */
const charName = (c: CharItem) => c.name || c.title || c.id;
/** 角色加载键：目录名（slug），后端按目录加载 */
const charKey = (c: CharItem) => c.id || charName(c);

const AVATAR_URL = (name: string) => `/api/characters/${encodeURIComponent(name)}/avatar`;

function formatDate(ts: number): string {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** 「继续战斗」按钮提示：把挂起存档摘要摊开，避免点进去才发现不是想续的那一场 */
function resumeHint(r?: CombatResumeSummaryDTO | null): string {
  if (!r) return "继续这场已挂起的战斗";
  const when = r.suspended_at ? new Date(r.suspended_at * 1000) : null;
  const stamp = when
    ? `${when.getMonth() + 1}-${String(when.getDate()).padStart(2, "0")} ${String(when.getHours()).padStart(2, "0")}:${String(when.getMinutes()).padStart(2, "0")}`
    : "";
  return [
    "继续战斗：" + (r.encounter_id || "未知节点"),
    `第 ${r.round_num} 回合`,
    `存活 ${r.player_alive}`,
    r.pending_waves > 0 ? `余 ${r.pending_waves} 波` : "",
    stamp ? `挂起于 ${stamp}` : "",
  ].filter(Boolean).join(" · ");
}

export default function SessionManagerView() {
  const { sessions, activeSessionId, chatMode, setSessions, setActiveSession, setCurrentView, setIndexSessionId, setChatMode, setCombatContext, setContentHubTab, setWorldbookScopeJumpId } =
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
  const [identities, setIdentities] = useState<{ id: string; name: string; summary: string; tags: string[] }[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerSearch, setPickerSearch] = useState("");

  // ── 详情操作状态 ──
  const [renaming, setRenaming] = useState(false);
  const [renameDraft, setRenameDraft] = useState("");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [identityPickerOpen, setIdentityPickerOpen] = useState(false);
  const [identitySearch, setIdentitySearch] = useState("");

  // 加载剧情/世界书/角色库/玩家身份
  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([api.listPlots(), api.listWorldbooks(), api.getCharacters(), api.getPlayerIdentities()]).then(([p, b, c, i]) => {
      if (cancelled) return;
      if (p.status === "fulfilled") setPlots(p.value || []);
      if (b.status === "fulfilled") setBooks(b.value?.books || []);
      if (c.status === "fulfilled") setCharacters(c.value || []);
      if (i.status === "fulfilled") setIdentities(i.value || []);
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

  // 两个选择器各自独立的最小化状态（保留搜索词与滚动位置）
  const pickerDialog = useDialogMinimize("session-character-picker", "添加角色入队", pickerOpen && !!selected);
  const identityPickerDialog = useDialogMinimize("session-identity-picker", "选择玩家身份", identityPickerOpen && !!selected);

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

  /** 继续战斗：恢复挂起的战斗（战斗页「临时返回」留下的存档）并进入战场 */
  const { resumeSession, resumeTest, busyKey } = useCombatResume();

  // 挂起的战斗测试（无会话，只存在于挂起存档里）：入口紧挨「战斗演练」，
  // 否则用户临时返回后就再也找不到上次的试打。
  const [testResumes, setTestResumes] = useState<CombatResumeTestDTO[]>([]);
  useEffect(() => {
    let cancelled = false;
    api.listCombatResumes()
      .then((res) => { if (!cancelled) setTestResumes(res?.tests || []); })
      .catch(() => { if (!cancelled) setTestResumes([]); });
    return () => { cancelled = true; };
  }, [api]);

  const handleResumeTest = useCallback(async (testId: string) => {
    const ok = await resumeTest(testId);
    if (ok) setTestResumes((prev) => prev.filter((t) => t.test_id !== testId));
  }, [resumeTest]);

  const handleDiscardTest = useCallback(async (testId: string) => {
    if (!window.confirm("丢弃这场战斗测试的存档？此操作不可恢复。")) return;
    try {
      await api.combatTestDiscardSuspend(testId);
      setTestResumes((prev) => prev.filter((t) => t.test_id !== testId));
    } catch (e: any) {
      alert("丢弃失败：" + (e?.message || "未知错误"));
    }
  }, [api]);

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

  // ── 玩家身份 ──

  const setIdentity = async (identity: string) => {
    if (!selected) return;
    setBusyAction("set-identity");
    try {
      await api.setPlayerIdentity(selected.id, identity);
      setSessions(sessions.map((s) => (s.id === selected.id ? { ...s, player_identity: identity } : s)));
      setIdentityPickerOpen(false);
    } catch (err: any) {
      alert("设置玩家身份失败: " + (err?.message || "未知错误"));
    } finally {
      setBusyAction(null);
    }
  };

  // ── 世界书绑定 ──

  const bindBook = async (bookId: string | null) => {
    if (!selected) return;
    setBusyAction(bookId ? `bind-${bookId}` : "unbind");
    try {
      // 解绑时需传当前绑定的真实 book id（bound=false 回落全局默认）
      const res = await api.bindWorldbook(bookId || selected.worldbook_id || "", selected.id, !!bookId);
      setSessions(sessions.map((s) => (s.id === selected.id ? { ...s, worldbook_id: res.worldbook_id, worldbook_scope: res.worldbook_scope } : s)));
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
      ? characters.filter((c) => charName(c).toLowerCase().includes(q) || c.id.toLowerCase().includes(q))
      : characters;
  }, [characters, pickerSearch]);

  const filteredIdentities = useMemo(() => {
    const q = identitySearch.trim().toLowerCase();
    if (!q) return identities;
    return identities.filter((i) =>
      (i.name || "").toLowerCase().includes(q) ||
      (i.summary || "").toLowerCase().includes(q) ||
      (i.tags || []).some((t) => t.toLowerCase().includes(q))
    );
  }, [identities, identitySearch]);

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

      {/* ═══ 挂起的战斗演练（战斗页「临时返回」留下的存档，无会话归属） ═══ */}
      {testResumes.length > 0 && (
        <div className="px-6 md:px-10 py-2 border-b border-gray-700/60 bg-gray-850/40 flex items-center gap-2 flex-wrap">
          <span className="text-[11px] text-amber-200 font-display tracking-wider">⏸ 挂起的战斗演练</span>
          {testResumes.map((t) => (
            <span
              key={t.test_id}
              className="flex items-center gap-2 text-[11px] bg-gray-800/60 border border-gray-700/60 rounded-lg pl-2.5 pr-1 py-1"
            >
              <span className="text-gray-300">{t.encounter_id || "未知节点"}</span>
              <span className="text-gray-500">
                第 {t.round_num} 回合 · 存活 {t.player_alive}
                {t.pending_waves > 0 ? ` · 余 ${t.pending_waves} 波` : ""}
              </span>
              <button
                onClick={() => void handleResumeTest(t.test_id)}
                disabled={busyKey === `test:${t.test_id}`}
                className="px-2 py-0.5 rounded bg-gray-800/60 hover:bg-gray-700 text-emerald-200 disabled:opacity-40 transition-colors"
              >
                {busyKey === `test:${t.test_id}` ? "恢复中…" : "▶ 继续"}
              </button>
              <button
                onClick={() => void handleDiscardTest(t.test_id)}
                className="px-1.5 py-0.5 rounded text-gray-500 hover:text-red-400 transition-colors"
                title="丢弃这场测试的存档"
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}

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
                      {!s.in_combat && s.combat_resumable && (
                        <span className="badge badge-tactical shrink-0" title="战斗已挂起，可继续">⏸ 已挂起</span>
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
                      {!s.in_combat && s.combat_resumable && (
                        <button
                          onClick={(e) => { e.stopPropagation(); void resumeSession(s.id); }}
                          disabled={busyKey === `session:${s.id}`}
                          className="btn text-[11px] px-3 py-1 bg-gray-800/60 hover:bg-gray-700 text-emerald-200 disabled:opacity-40"
                          title={resumeHint(s.combat_resume)}
                        >
                          {busyKey === `session:${s.id}` ? "恢复中…" : "▶ 继续战斗"}
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
                    {!selected.in_combat && selected.combat_resumable && (
                      <span className="badge badge-tactical">⏸ 战斗已挂起</span>
                    )}
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
                  {!selected.in_combat && selected.combat_resumable && (
                    <button
                      onClick={() => void resumeSession(selected.id)}
                      disabled={busyKey === `session:${selected.id}`}
                      className="btn px-5 py-2 text-sm bg-gray-800/60 hover:bg-gray-700 text-emerald-200 disabled:opacity-40"
                      title={resumeHint(selected.combat_resume)}
                    >
                      {busyKey === `session:${selected.id}` ? "恢复中…" : "▶ 继续战斗"}
                    </button>
                  )}
                  <button onClick={() => enterSession(selected.id)} className="btn-hero btn px-6 py-2 text-sm">
                    ▶ 进入对话
                  </button>
                </div>
              </div>

              {/* 统计网格 */}
              <div className="grid grid-cols-2 md:grid-cols-5 gap-2.5">
                <div className="stat-cell px-3 py-2.5">
                  <div className="text-[10px] text-gray-500">创建时间</div>
                  <div className="text-xs text-gray-200 mt-0.5">{formatDate(selected.created_at)}</div>
                </div>
                <div
                  className="stat-cell px-3 py-2.5 cursor-pointer hover:bg-gray-800/60 transition-colors"
                  onClick={() => { setIdentityPickerOpen(true); setIdentitySearch(""); }}
                  title="点击修改玩家身份"
                >
                  <div className="text-[10px] text-gray-500">玩家身份</div>
                  <div className="text-xs text-gray-200 mt-0.5">
                    🎭 {selected.player_identity || "博士"}
                    <span className="text-[10px] text-amber-500/80 ml-1">✎</span>
                  </div>
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
                  {!selected.worldbook_id && selected.worldbook_scope ? "当前未绑定世界书，角色条目不会载入。" :
                    selected.worldbook_scope?.legacy_full_scope || !selected.worldbook_scope ? "当前会话沿用旧版全量范围；启用按需策略并重新绑定后，角色条目才按阵容载入。" :
                    "提示：入队角色的世界书条目随会话载入；世界观及固定/依赖条目按策略生效。未入队角色不会自动导入，可在此调整阵容。"}
                  {" "}<button className="text-blue-400 hover:underline" onClick={() => {
                    setWorldbookScopeJumpId(selected.worldbook_id || null); setContentHubTab("worldbook-deps"); setCurrentView("content");
                  }}>前往内容中心配置依赖 →</button>
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
                      onClick={() => { setIndexSessionId(selected.id); setContentHubTab("index"); setCurrentView("content"); }}
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
        <div className={`fixed inset-0 z-50 flex items-center justify-center bg-black/60 ${pickerDialog.minimizedClass}`} onClick={() => setPickerOpen(false)}>
          <div
            ref={pickerDialog.containerRef}
            tabIndex={-1}
            className="bg-gray-800 border border-gray-700 rounded-xl w-[560px] max-h-[640px] flex flex-col shadow-2xl outline-none"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700">
              <h2 className="text-base font-semibold">添加角色入队</h2>
              <div className="flex items-center gap-1">
                <button
                  onClick={pickerDialog.minimize}
                  className="text-gray-500 hover:text-gray-300 text-lg leading-none px-1"
                  title="最小化（保留搜索词）"
                  aria-label="最小化对话框"
                >
                  —
                </button>
                <button
                  onClick={() => setPickerOpen(false)}
                  className="text-gray-500 hover:text-gray-300 text-lg leading-none px-1"
                  title="关闭"
                  aria-label="关闭对话框"
                >
                  ✕
                </button>
              </div>
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
                  .filter((c) => !roster.includes(charKey(c)))
                  .map((c) => {
                    const key = charKey(c);
                    return (
                      <div
                        key={c.id}
                        className={`char-tile p-2.5 flex items-center gap-2 ${busyAction === `add-${key}` ? "opacity-60" : ""}`}
                        onClick={() => void addCharacter(key)}
                        title="点击加入本会话"
                      >
                        <img
                          src={AVATAR_URL(key)}
                          alt={charName(c)}
                          className="char-avatar sm"
                          onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
                        />
                        <div className="min-w-0">
                          <div className="text-xs text-gray-200 truncate">
                            {charName(c)}
                            {selected?.player_identity === key && (
                              <span className="ml-1 text-[9px] text-purple-300">🎭 你</span>
                            )}
                          </div>
                          <div className="text-[10px] text-gray-600 truncate">{busyAction === `add-${key}` ? "加载中..." : "点击入队"}</div>
                        </div>
                      </div>
                    );
                  })}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 玩家身份选择器 */}
      {identityPickerOpen && selected && (
        <div className={`fixed inset-0 z-50 flex items-center justify-center bg-black/60 ${identityPickerDialog.minimizedClass}`} onClick={() => setIdentityPickerOpen(false)}>
          <div
            ref={identityPickerDialog.containerRef}
            tabIndex={-1}
            className="bg-gray-800 border border-gray-700 rounded-xl w-[520px] max-h-[600px] flex flex-col shadow-2xl outline-none"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700">
              <div>
                <h2 className="text-base font-semibold">选择玩家身份</h2>
                <p className="text-[11px] text-gray-500 mt-0.5">当前：{selected.player_identity || "博士"}</p>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={identityPickerDialog.minimize}
                  className="text-gray-500 hover:text-gray-300 text-lg leading-none px-1"
                  title="最小化（保留搜索词）"
                  aria-label="最小化对话框"
                >
                  —
                </button>
                <button
                  onClick={() => setIdentityPickerOpen(false)}
                  className="text-gray-500 hover:text-gray-300 text-lg leading-none px-1"
                  title="关闭"
                  aria-label="关闭对话框"
                >
                  ✕
                </button>
              </div>
            </div>
            <div className="px-5 pt-3 pb-2">
              <input
                className="input text-sm"
                placeholder="搜索身份..."
                value={identitySearch}
                onChange={(e) => setIdentitySearch(e.target.value)}
                autoFocus
              />
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-2 lobby-scroll">
              {/* 默认博士 */}
              <div
                className={`pick-card p-3 mb-2 flex items-center gap-3 ${(selected.player_identity || "博士") === "博士" ? "selected" : ""}`}
                onClick={() => void setIdentity("博士")}
              >
                <img
                  src="/api/characters/博士/avatar"
                  alt="博士"
                  className="char-avatar sm"
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
                />
                <div className="min-w-0">
                  <div className="text-sm font-medium text-gray-200">博士</div>
                  <div className="text-[10px] text-gray-500 truncate">默认玩家身份 · 罗德岛战术指挥官</div>
                </div>
              </div>

              {filteredIdentities.length === 0 && !identitySearch && (
                <p className="text-gray-500 text-sm text-center py-6">暂无自定义玩家身份</p>
              )}
              {filteredIdentities.length === 0 && identitySearch && (
                <p className="text-gray-500 text-sm text-center py-6">未找到匹配身份</p>
              )}

              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 pb-3">
                {filteredIdentities.map((i) => {
                  const isCurrent = selected.player_identity === i.id;
                  return (
                    <div
                      key={i.id}
                      className={`char-tile p-2.5 flex flex-col items-center gap-1.5 ${isCurrent ? "selected" : ""} ${busyAction === "set-identity" ? "opacity-60" : ""}`}
                      onClick={() => void setIdentity(i.id)}
                    >
                      <div className="relative w-full flex justify-center">
                        <img
                          src={`/api/characters/${encodeURIComponent(i.id)}/avatar`}
                          alt={i.name}
                          className="char-avatar"
                          onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
                        />
                        {isCurrent && (
                          <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-amber-500 text-black text-[10px] font-bold flex items-center justify-center shadow">✓</span>
                        )}
                      </div>
                      <span className={`text-xs truncate w-full text-center ${isCurrent ? "text-amber-300 font-medium" : "text-gray-200"}`}>
                        {i.name || i.id}
                      </span>
                      {i.summary && <span className="text-[9px] text-gray-500 truncate w-full text-center">{i.summary}</span>}
                    </div>
                  );
                })}
              </div>
            </div>
            <div className="px-5 py-3 border-t border-gray-700 flex justify-end">
              <button
                onClick={() => { setCurrentView("characters"); setIdentityPickerOpen(false); }}
                className="text-xs px-3 py-1.5 rounded bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
              >
                管理玩家身份
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
