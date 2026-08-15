import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "../hooks/useApi";
import { useAppStore } from "../stores/appStore";
import type {
  WorldBookDetail,
  WorldBookEntryDTO,
  WorldBookImportReport,
  WorldBookSummary,
} from "../types";
import SourceBadge from "./SourceBadge";

/** 条目编辑草稿（触发词/副键用逗号分隔文本编辑） */
interface EntryDraft {
  name: string;
  content: string;
  triggerKeysText: string;
  secondaryKeysText: string;
  alwaysActive: boolean;
  selective: boolean;
  enabled: boolean;
  probability: number;
  position: number;
  depth: number;
  scanDepth: number;
  group: string;
  groupWeight: number;
  caseSensitive: boolean;
  matchWholeWords: boolean;
}

function entryToDraft(e: WorldBookEntryDTO): EntryDraft {
  return {
    name: e.name || "",
    content: e.content || "",
    triggerKeysText: (e.trigger_keys || []).join(", "),
    secondaryKeysText: (e.secondary_keys || []).join(", "),
    alwaysActive: !!e.always_active,
    selective: !!e.selective,
    enabled: !!e.enabled,
    probability: e.probability ?? 100,
    position: e.position ?? 0,
    depth: e.depth ?? 4,
    scanDepth: e.scan_depth ?? 4,
    group: e.group || "",
    groupWeight: e.group_weight ?? 100,
    caseSensitive: !!e.case_sensitive,
    matchWholeWords: !!e.match_whole_words,
  };
}

function draftToEntry(draft: EntryDraft): Partial<WorldBookEntryDTO> {
  const split = (s: string) =>
    s.split(/[,，]/).map((x) => x.trim()).filter(Boolean);
  return {
    name: draft.name.trim(),
    content: draft.content,
    trigger_keys: split(draft.triggerKeysText),
    secondary_keys: split(draft.secondaryKeysText),
    always_active: draft.alwaysActive,
    selective: draft.selective,
    enabled: draft.enabled,
    probability: draft.probability,
    position: draft.position,
    depth: draft.depth,
    scan_depth: draft.scanDepth,
    group: draft.group.trim(),
    group_weight: draft.groupWeight,
    case_sensitive: draft.caseSensitive,
    match_whole_words: draft.matchWholeWords,
  };
}

const SOURCE_LABELS: Record<string, string> = {
  sillytavern_v1: "酒馆 v1",
  sillytavern_v2: "酒馆 v2",
  character_card: "角色卡内嵌",
  chat_backup_jsonl: "聊天备份",
  manual: "手动",
};

function sourceLabel(fmt: string): string {
  return SOURCE_LABELS[fmt] || fmt;
}

export default function WorldBookManager() {
  const api = useApi();
  const sessions = useAppStore((s) => s.sessions);
  const worldbookJumpId = useAppStore((s) => s.worldbookJumpId);
  const setWorldbookJumpId = useAppStore((s) => s.setWorldbookJumpId);

  const [books, setBooks] = useState<WorldBookSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<WorldBookDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ text: string; type: "ok" | "error" } | null>(null);
  const [importReport, setImportReport] = useState<WorldBookImportReport | null>(null);
  const [importing, setImporting] = useState(false);

  // 书元信息编辑
  const [bookName, setBookName] = useState("");
  const [budgetTokens, setBudgetTokens] = useState("0");

  // 会话绑定
  const [bindSessionId, setBindSessionId] = useState("");
  const [boundBookId, setBoundBookId] = useState<string | null>(null);
  const [effectiveBookId, setEffectiveBookId] = useState<string | null>(null);

  // 条目编辑
  const [editorMode, setEditorMode] = useState<"create" | "edit" | null>(null);
  const [editingUid, setEditingUid] = useState<string | null>(null);
  const [draft, setDraft] = useState<EntryDraft | null>(null);
  const [saving, setSaving] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout>>();

  const showToast = useCallback((text: string, type: "ok" | "error" = "ok") => {
    setToast({ text, type });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3500);
  }, []);

  // ── 加载书列表 ──
  const loadBooks = useCallback(async () => {
    setError(null);
    try {
      const res = await api.listWorldbooks();
      setBooks(res.books || []);
    } catch (err: any) {
      setError(err.message || "加载世界书列表失败");
    }
  }, [api]);

  useEffect(() => { loadBooks(); }, [loadBooks]);

  // ── 统一检索/其他模块跳转：选中指定书 ──
  useEffect(() => {
    if (worldbookJumpId) {
      setSelectedId(worldbookJumpId);
      setWorldbookJumpId(null);
    }
  }, [worldbookJumpId, setWorldbookJumpId]);

  // ── 加载书详情 ──
  const loadDetail = useCallback(async (id: string | null) => {
    if (!id) {
      setDetail(null);
      return;
    }
    setLoadingDetail(true);
    try {
      const d = await api.getWorldbook(id);
      setDetail(d);
      setBookName(d.name);
      setBudgetTokens(String(d.budget_tokens ?? 0));
    } catch (err: any) {
      showToast(err.message || "加载世界书详情失败", "error");
    } finally {
      setLoadingDetail(false);
    }
  }, [api, showToast]);

  useEffect(() => {
    loadDetail(selectedId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  // ── 会话绑定查询 ──
  useEffect(() => {
    if (!bindSessionId) {
      setBoundBookId(null);
      setEffectiveBookId(null);
      return;
    }
    api.resolveWorldbook(bindSessionId)
      .then((res) => {
        setEffectiveBookId(res.book?.id ?? null);
      })
      .catch(() => { /* ignore */ });
    // 从会话列表找到绑定的书（overlay 中的 worldbook_id）
    const session = sessions.find((s) => s.id === bindSessionId);
    setBoundBookId(session?.worldbook_id ?? null);
  }, [bindSessionId, sessions, api]);

  const refreshListAfterMutate = useCallback(async (keepId?: string) => {
    await loadBooks();
    if (keepId) {
      await loadDetail(keepId);
    } else {
      await loadDetail(selectedId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadBooks, loadDetail, selectedId]);

  // ── 创建书 ──
  const createBook = async () => {
    const name = window.prompt("新世界书名称：", "未命名世界书");
    if (!name) return;
    try {
      const res = await api.createWorldbook(name.trim());
      await loadBooks();
      setSelectedId(res.book.id);
      showToast("已创建世界书");
    } catch (err: any) {
      showToast(err.message || "创建失败", "error");
    }
  };

  // ── 导入 ──
  const onImportFile = async (file: File) => {
    setImporting(true);
    setImportReport(null);
    try {
      const name = file.name.replace(/\.(json|jsonl)$/i, "");
      const res = await api.importWorldbookFile(name, file);
      setImportReport(res.report);
      await loadBooks();
      setSelectedId(res.book.id);
      showToast(`导入完成：${res.report.imported} 条`);
    } catch (err: any) {
      showToast(err.message || "导入失败", "error");
    } finally {
      setImporting(false);
    }
  };

  const onImportJsonText = async (text: string, name: string) => {
    setImporting(true);
    setImportReport(null);
    try {
      let data: any;
      try {
        data = JSON.parse(text);
      } catch {
        // 交给后端按 .jsonl 解析
        data = text;
      }
      const res = await api.importWorldbookJson(name || "导入的世界书", data);
      setImportReport(res.report);
      await loadBooks();
      setSelectedId(res.book.id);
      showToast(`导入完成：${res.report.imported} 条`);
    } catch (err: any) {
      showToast(err.message || "导入失败", "error");
    } finally {
      setImporting(false);
    }
  };

  // ── 书元信息保存 ──
  const saveBookMeta = async () => {
    if (!detail) return;
    try {
      await api.updateWorldbook(detail.id, {
        name: bookName.trim() || detail.name,
        budget_tokens: parseInt(budgetTokens || "0", 10) || 0,
      });
      await refreshListAfterMutate(detail.id);
      showToast("已保存");
    } catch (err: any) {
      showToast(err.message || "保存失败", "error");
    }
  };

  const toggleDefault = async (id: string, isDefault: boolean) => {
    try {
      await api.setDefaultWorldbook(id, isDefault);
      await loadBooks();
      showToast(isDefault ? "已设为全局默认书" : "已取消默认");
    } catch (err: any) {
      showToast(err.message || "操作失败", "error");
    }
  };

  const deleteBook = async (id: string) => {
    if (!window.confirm("确定删除这本书吗？绑定它的会话将回落到全局默认书。")) return;
    try {
      await api.deleteWorldbook(id);
      if (selectedId === id) {
        setSelectedId(null);
        setDetail(null);
      }
      await loadBooks();
      showToast("已删除");
    } catch (err: any) {
      showToast(err.message || "删除失败", "error");
    }
  };

  const toggleEnabled = async (book: WorldBookSummary) => {
    try {
      await api.updateWorldbook(book.id, { enabled: !book.enabled });
      await refreshListAfterMutate(book.id);
      showToast(book.enabled ? "已停用（不再参与解析）" : "已启用");
    } catch (err: any) {
      showToast(err.message || "操作失败", "error");
    }
  };

  const reinstallBook = async (id: string) => {
    if (!window.confirm("将恢复该预装整合包的出厂内容（覆盖当前副本的修改），确定重装？")) return;
    try {
      const res = await api.reinstallWorldbook(id);
      await loadBooks();
      setSelectedId(res.book.id);
      showToast("已重装预装整合包");
    } catch (err: any) {
      showToast(err.message || "重装失败", "error");
    }
  };

  const duplicateBook = async (id: string) => {
    const name = window.prompt("副本名称：", "");
    if (name === null) return;
    try {
      const res = await api.duplicateWorldbook(id, name || undefined);
      await loadBooks();
      setSelectedId(res.book.id);
      showToast("已创建副本（导入书）");
    } catch (err: any) {
      showToast(err.message || "复制失败", "error");
    }
  };

  const exportBook = async (id: string) => {
    try {
      const res = await api.exportWorldbook(id);
      const blob = new Blob([JSON.stringify(res.data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${res.name || id}.worldbook.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      showToast(err.message || "导出失败", "error");
    }
  };

  // ── 会话绑定 ──
  const bindToSession = async (bound: boolean) => {
    if (!detail || !bindSessionId) return;
    try {
      await api.bindWorldbook(detail.id, bindSessionId, bound);
      setBoundBookId(bound ? detail.id : null);
      const res = await api.resolveWorldbook(bindSessionId);
      setEffectiveBookId(res.book?.id ?? null);
      showToast(bound ? "已绑定到会话" : "已解绑会话");
    } catch (err: any) {
      showToast(err.message || "绑定失败", "error");
    }
  };

  // ── 条目编辑 ──
  const openCreate = () => {
    setEditorMode("create");
    setEditingUid(null);
    setDraft(entryToDraft({
      uid: "", name: "", content: "", trigger_keys: [], secondary_keys: [],
      always_active: false, selective: true, enabled: true, position: 0,
      depth: 4, scan_depth: 4, probability: 100, group: "", group_weight: 100,
      case_sensitive: false, match_whole_words: false,
    }));
  };

  const openEdit = (e: WorldBookEntryDTO) => {
    setEditorMode("edit");
    setEditingUid(e.uid);
    setDraft(entryToDraft(e));
  };

  const saveEntry = async () => {
    if (!detail || !draft) return;
    if (!draft.content.trim()) {
      showToast("条目内容不能为空", "error");
      return;
    }
    setSaving(true);
    try {
      const payload = draftToEntry(draft);
      if (editorMode === "create") {
        await api.createWorldbookEntry(detail.id, payload);
      } else if (editingUid) {
        await api.updateWorldbookEntry(detail.id, editingUid, payload);
      }
      setEditorMode(null);
      setDraft(null);
      await loadDetail(detail.id);
      showToast("已保存条目");
    } catch (err: any) {
      showToast(err.message || "保存条目失败", "error");
    } finally {
      setSaving(false);
    }
  };

  const deleteEntry = async (entryId: string) => {
    if (!detail) return;
    if (!window.confirm("确定删除该条目吗？")) return;
    try {
      await api.deleteWorldbookEntry(detail.id, entryId);
      if (editingUid === entryId) {
        setEditorMode(null);
        setDraft(null);
      }
      await loadDetail(detail.id);
      showToast("已删除条目");
    } catch (err: any) {
      showToast(err.message || "删除条目失败", "error");
    }
  };

  // ── 渲染 ──
  return (
    <div className="flex h-full">
      {/* ═══ 左侧：书列表 + 导入 ═══ */}
      <div className="w-80 border-r border-gray-700 overflow-y-auto p-3 shrink-0">
        <div className="flex items-center justify-between mb-3">
          <h2 className="panel-title">世界书</h2>
          <div className="flex gap-1">
            <button
              className="text-xs px-2 py-1 rounded bg-amber-600/20 text-amber-300 hover:bg-amber-600/40 transition-colors"
              onClick={createBook}
              title="新建空书"
            >
              ＋新建
            </button>
            <button
              className={`text-xs px-2 py-1 rounded bg-blue-600/20 text-blue-300 hover:bg-blue-600/40 transition-colors ${importing ? "opacity-50 cursor-wait" : ""}`}
              onClick={() => fileInputRef.current?.click()}
              disabled={importing}
              title="导入酒馆世界书 JSON / 聊天备份 jsonl"
            >
              {importing ? "导入中…" : "⬆导入"}
            </button>
          </div>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".json,.jsonl,.txt"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onImportFile(f);
            e.target.value = "";
          }}
        />
        <p className="text-xs text-gray-500 mb-2 leading-relaxed">
          支持酒馆世界书导出 JSON（v1/v2）、角色卡内嵌世界书、聊天备份 .jsonl。
          兼容触发词/副键/常驻/概率/插入位置等语义。
        </p>

        {/* 粘贴导入 */}
        <details className="mb-3 text-xs">
          <summary className="cursor-pointer text-gray-400 hover:text-gray-200 select-none">
            粘贴 JSON 导入
          </summary>
          <PasteImportBox onImport={onImportJsonText} importing={importing} />
        </details>

        {/* 导入报告 */}
        {importReport && (
          <div className="mb-3 p-2 rounded bg-gray-800 border border-gray-700 text-xs">
            <p className="text-green-400">
              导入成功 {importReport.imported} 条
              {importReport.skipped > 0 && `，跳过 ${importReport.skipped} 条`}
            </p>
            <p className="text-gray-500 mt-0.5">来源：{sourceLabel(importReport.source_format)}</p>
            {importReport.warnings.length > 0 && (
              <ul className="mt-1 text-amber-400/80 list-disc list-inside max-h-24 overflow-y-auto">
                {importReport.warnings.slice(0, 20).map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
                {importReport.warnings.length > 20 && (
                  <li>…共 {importReport.warnings.length} 条警告</li>
                )}
              </ul>
            )}
          </div>
        )}

        {error && <p className="text-red-400 text-xs mb-2">{error}</p>}

        {/* 书列表 */}
        <div className="space-y-1.5">
          {books.length === 0 && (
            <p className="text-gray-600 text-xs">还没有世界书，点击「⬆导入」或「＋新建」开始。</p>
          )}
          {books.map((b) => (
            <div
              key={b.id}
              onClick={() => setSelectedId(b.id)}
              className={`p-2 rounded-lg border cursor-pointer transition-colors ${
                selectedId === b.id
                  ? "border-blue-600/60 bg-blue-600/10"
                  : "border-gray-700 bg-gray-800/60 hover:border-gray-600"
              } ${!b.enabled ? "opacity-60" : ""}`}
            >
              <div className="flex items-center justify-between gap-1">
                <span className="text-sm text-gray-200 truncate">{b.name}</span>
                <span className="flex items-center gap-1 shrink-0">
                  <SourceBadge source={b.source} size="xs" />
                  {b.is_default && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-600/30 text-amber-300">
                      默认
                    </span>
                  )}
                  {!b.enabled && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700 text-gray-400">
                      停用
                    </span>
                  )}
                </span>
              </div>
              <div className="flex items-center justify-between mt-1 text-[11px] text-gray-500">
                <span>{b.entry_count} 条 · {sourceLabel(b.source_format)}</span>
                <span className="flex gap-1" onClick={(e) => e.stopPropagation()}>
                  <button
                    className="hover:text-gray-300"
                    title={b.enabled ? "停用（不再参与解析）" : "启用"}
                    onClick={() => toggleEnabled(b)}
                  >
                    {b.enabled ? "⏸" : "▶"}
                  </button>
                  <button
                    className="hover:text-gray-300"
                    title="设为全局默认书"
                    onClick={() => toggleDefault(b.id, true)}
                  >
                    ⭐
                  </button>
                  <button
                    className="hover:text-gray-300"
                    title="导出酒馆格式"
                    onClick={() => exportBook(b.id)}
                  >
                    ⬇
                  </button>
                  <button
                    className="hover:text-gray-300"
                    title="复制为新导入书"
                    onClick={() => duplicateBook(b.id)}
                  >
                    📄
                  </button>
                  {b.is_preinstalled && (
                    <button
                      className="hover:text-cyan-300"
                      title="重装预装整合包（恢复出厂内容）"
                      onClick={() => reinstallBook(b.id)}
                    >
                      ↻
                    </button>
                  )}
                  <button
                    className="hover:text-red-400"
                    title="删除（预装包可重装还原）"
                    onClick={() => deleteBook(b.id)}
                  >
                    🗑
                  </button>
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ═══ 右侧：详情 + 条目管理 ═══ */}
      <div className="flex-1 overflow-y-auto p-4">
        {!detail && (
          <p className="text-gray-600 text-sm mt-8 text-center">
            选择左侧世界书，或导入/新建一本。
          </p>
        )}

        {detail && (
          <>
            {/* ── 书元信息 ── */}
            <div className="mb-4 p-3 rounded-lg bg-gray-800/60 border border-gray-700">
              <div className="flex items-center gap-2 flex-wrap">
                <input
                  className="flex-1 min-w-[160px] bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200"
                  value={bookName}
                  onChange={(e) => setBookName(e.target.value)}
                />
                <label className="text-xs text-gray-500 flex items-center gap-1">
                  Token 预算
                  <input
                    className="w-20 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200"
                    type="number"
                    min={0}
                    value={budgetTokens}
                    onChange={(e) => setBudgetTokens(e.target.value)}
                  />
                  <span title="0 = 不限制">（0=不限）</span>
                </label>
                <button
                  className="text-xs px-2 py-1 rounded bg-blue-600/20 text-blue-300 hover:bg-blue-600/40"
                  onClick={saveBookMeta}
                >
                  保存
                </button>
                <button
                  className="text-xs px-2 py-1 rounded bg-amber-600/20 text-amber-300 hover:bg-amber-600/40"
                  onClick={() => toggleDefault(detail.id, !detail.is_default)}
                >
                  {detail.is_default ? "取消默认" : "设为全局默认"}
                </button>
                <button
                  className="text-xs px-2 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600"
                  onClick={() => exportBook(detail.id)}
                >
                  导出酒馆格式
                </button>
                <button
                  className="text-xs px-2 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600"
                  onClick={() => duplicateBook(detail.id)}
                >
                  📄 复制
                </button>
                {detail.is_preinstalled && (
                  <button
                    className="text-xs px-2 py-1 rounded bg-cyan-700/40 text-cyan-200 hover:bg-cyan-700/60"
                    onClick={() => reinstallBook(detail.id)}
                  >
                    ↻ 重装整合包
                  </button>
                )}
              </div>
              <p className="text-[11px] text-gray-500 mt-2 flex items-center gap-1.5 flex-wrap">
                <SourceBadge source={detail.source} size="xs" />
                <span>
                  {detail.entry_count} 条 · 来源 {sourceLabel(detail.source_format)} ·
                  生效规则：会话绑定 &gt; 全局默认书{detail.is_preinstalled ? " &gt; 预装整合包" : ""}
                </span>
                {!detail.enabled && <span className="text-red-400">（已停用，不参与解析）</span>}
              </p>
            </div>

            {/* ── 会话绑定 ── */}
            <div className="mb-4 p-3 rounded-lg bg-gray-800/60 border border-gray-700">
              <h3 className="text-xs text-gray-400 mb-2">会话绑定</h3>
              <div className="flex items-center gap-2 flex-wrap">
                <select
                  className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200 max-w-[240px]"
                  value={bindSessionId}
                  onChange={(e) => setBindSessionId(e.target.value)}
                >
                  <option value="">选择会话…</option>
                  {sessions.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
                {bindSessionId && (
                  <>
                    {boundBookId === detail.id ? (
                      <button
                        className="text-xs px-2 py-1 rounded bg-red-600/20 text-red-300 hover:bg-red-600/40"
                        onClick={() => bindToSession(false)}
                      >
                        解绑该会话
                      </button>
                    ) : (
                      <button
                        className="text-xs px-2 py-1 rounded bg-blue-600/20 text-blue-300 hover:bg-blue-600/40"
                        onClick={() => bindToSession(true)}
                      >
                        绑定该会话
                      </button>
                    )}
                    <span className="text-[11px] text-gray-500">
                      {boundBookId === detail.id
                        ? "该会话已绑定本书"
                        : effectiveBookId
                          ? "该会话当前生效其他书"
                          : "该会话当前生效全局默认书"}
                    </span>
                  </>
                )}
              </div>
            </div>

            {/* ── 条目区 ── */}
            <div className="flex items-center justify-between mb-2">
              <h3 className="panel-title">条目（{detail.entries.length}）</h3>
              <button
                className="text-xs px-2 py-1 rounded bg-amber-600/20 text-amber-300 hover:bg-amber-600/40"
                onClick={openCreate}
              >
                ＋新增条目
              </button>
            </div>

            {loadingDetail && <p className="text-gray-500 text-xs">加载中…</p>}

            {/* 条目列表 */}
            {!loadingDetail && detail.entries.length === 0 && (
              <p className="text-gray-600 text-xs">本书暂无条目。</p>
            )}
            <div className="space-y-2">
              {detail.entries.map((e) => (
                <div
                  key={e.uid}
                  className={`p-2.5 rounded-lg border transition-colors ${
                    editingUid === e.uid
                      ? "border-amber-600/60 bg-amber-600/5"
                      : "border-gray-700 bg-gray-800/60"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm text-gray-200 truncate">
                      {e.name || e.content.slice(0, 24) || "(未命名)"}
                      {!e.enabled && <span className="text-gray-600 ml-1">[停用]</span>}
                      {e.always_active && (
                        <span className="text-[10px] px-1 py-0.5 rounded bg-purple-600/30 text-purple-300 ml-1">
                          常驻
                        </span>
                      )}
                    </span>
                    <span className="flex gap-1 shrink-0">
                      <button
                        className="text-xs px-1.5 py-0.5 rounded hover:bg-gray-700 text-gray-400 hover:text-gray-200"
                        onClick={() => openEdit(e)}
                      >
                        编辑
                      </button>
                      <button
                        className="text-xs px-1.5 py-0.5 rounded hover:bg-red-600/20 text-gray-400 hover:text-red-300"
                        onClick={() => deleteEntry(e.uid)}
                      >
                        删除
                      </button>
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 flex-wrap text-[11px] text-gray-500">
                    {e.trigger_keys.length > 0 && (
                      <span title="触发词">
                        🔑 {e.trigger_keys.slice(0, 4).join(", ")}
                        {e.trigger_keys.length > 4 && ` +${e.trigger_keys.length - 4}`}
                      </span>
                    )}
                    {e.secondary_keys.length > 0 && (
                      <span title="副键">
                        🔸 {e.secondary_keys.slice(0, 4).join(", ")}
                        {e.secondary_keys.length > 4 && ` +${e.secondary_keys.length - 4}`}
                      </span>
                    )}
                    <span>位置：{e.position === 0 ? "卡前" : "卡后"}</span>
                    <span>深度：{e.depth}</span>
                    {e.probability < 100 && <span>概率：{e.probability}%</span>}
                    {e.group && <span>组：{e.group}</span>}
                    {(e.case_sensitive || e.match_whole_words) && (
                      <span>
                        {e.case_sensitive ? "区分大小写" : ""}
                        {e.case_sensitive && e.match_whole_words ? " · " : ""}
                        {e.match_whole_words ? "全词匹配" : ""}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-gray-400 line-clamp-2">
                    {e.content.slice(0, 120)}
                  </p>
                </div>
              ))}
            </div>

            {/* ── 条目编辑器 ── */}
            {editorMode && draft && (
              <div className="mt-4 p-3 rounded-lg border border-amber-600/40 bg-gray-900/60">
                <h3 className="text-sm text-amber-300 mb-3">
                  {editorMode === "create" ? "新增条目" : "编辑条目"}
                </h3>
                <div className="grid grid-cols-2 gap-3">
                  <label className="text-xs text-gray-400 col-span-2">
                    名称（comment）
                    <input
                      className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200"
                      value={draft.name}
                      onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                    />
                  </label>
                  <label className="text-xs text-gray-400 col-span-2">
                    内容（content）
                    <textarea
                      className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200 min-h-[100px]"
                      value={draft.content}
                      onChange={(e) => setDraft({ ...draft, content: e.target.value })}
                    />
                  </label>
                  <label className="text-xs text-gray-400">
                    触发词（正则，逗号分隔）
                    <input
                      className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200"
                      value={draft.triggerKeysText}
                      onChange={(e) => setDraft({ ...draft, triggerKeysText: e.target.value })}
                    />
                  </label>
                  <label className="text-xs text-gray-400">
                    副键（逗号分隔）
                    <input
                      className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200"
                      value={draft.secondaryKeysText}
                      onChange={(e) => setDraft({ ...draft, secondaryKeysText: e.target.value })}
                    />
                  </label>
                  <label className="text-xs text-gray-400">
                    分组
                    <input
                      className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200"
                      value={draft.group}
                      onChange={(e) => setDraft({ ...draft, group: e.target.value })}
                    />
                  </label>
                  <label className="text-xs text-gray-400">
                    插入位置
                    <select
                      className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200"
                      value={draft.position}
                      onChange={(e) => setDraft({ ...draft, position: Number(e.target.value) })}
                    >
                      <option value={0}>0 - 卡前（稳定层）</option>
                      <option value={1}>1 - 卡后（动态层）</option>
                    </select>
                  </label>
                  <label className="text-xs text-gray-400">
                    深度
                    <input
                      className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200"
                      type="number" min={0} max={20}
                      value={draft.depth}
                      onChange={(e) => setDraft({ ...draft, depth: Number(e.target.value) })}
                    />
                  </label>
                  <label className="text-xs text-gray-400">
                    扫描回溯消息数
                    <input
                      className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200"
                      type="number" min={1} max={50}
                      value={draft.scanDepth}
                      onChange={(e) => setDraft({ ...draft, scanDepth: Number(e.target.value) })}
                    />
                  </label>
                  <label className="text-xs text-gray-400">
                    概率 %
                    <input
                      className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200"
                      type="number" min={0} max={100}
                      value={draft.probability}
                      onChange={(e) => setDraft({ ...draft, probability: Number(e.target.value) })}
                    />
                  </label>
                  <label className="text-xs text-gray-400">
                    组权重
                    <input
                      className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-gray-200"
                      type="number"
                      value={draft.groupWeight}
                      onChange={(e) => setDraft({ ...draft, groupWeight: Number(e.target.value) })}
                    />
                  </label>
                </div>
                <div className="mt-3 flex items-center gap-4 flex-wrap text-xs text-gray-300">
                  {[
                    ["alwaysActive", "常驻（constant）"],
                    ["selective", "选择性（主键命中才查副键）"],
                    ["enabled", "启用"],
                    ["caseSensitive", "区分大小写"],
                    ["matchWholeWords", "全词匹配"],
                  ].map(([key, label]) => (
                    <label key={key} className="flex items-center gap-1 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={(draft as any)[key]}
                        onChange={(e) => setDraft({ ...draft, [key]: e.target.checked })}
                      />
                      {label}
                    </label>
                  ))}
                </div>
                <div className="mt-4 flex gap-2">
                  <button
                    className="text-xs px-3 py-1 rounded bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-50"
                    onClick={saveEntry}
                    disabled={saving}
                  >
                    {saving ? "保存中…" : "保存条目"}
                  </button>
                  <button
                    className="text-xs px-3 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600"
                    onClick={() => { setEditorMode(null); setDraft(null); }}
                  >
                    取消
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Toast */}
      {toast && (
        <div
          className={`fixed bottom-12 right-4 px-3 py-2 rounded-lg text-sm shadow-lg ${
            toast.type === "ok"
              ? "bg-green-700/90 text-white"
              : "bg-red-700/90 text-white"
          }`}
        >
          {toast.text}
        </div>
      )}
    </div>
  );
}

/** 粘贴 JSON 导入小面板 */
function PasteImportBox({
  onImport,
  importing,
}: {
  onImport: (text: string, name: string) => void;
  importing: boolean;
}) {
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  return (
    <div className="mt-2 space-y-1.5">
      <input
        className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200"
        placeholder="书名（可选）"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <textarea
        className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 min-h-[90px] font-mono"
        placeholder='粘贴 {"entries": {...}} 或多行 .jsonl 内容'
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <button
        className="text-xs px-2 py-1 rounded bg-blue-600/20 text-blue-300 hover:bg-blue-600/40 disabled:opacity-50"
        disabled={!text.trim() || importing}
        onClick={() => onImport(text, name)}
      >
        {importing ? "导入中…" : "导入"}
      </button>
    </div>
  );
}
