import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "../hooks/useApi";
import { useAppStore } from "../stores/appStore";
import type { WorldBookDetail, WorldBookSummary } from "../types";
import type { WorldBookGraphView } from "../utils/worldbookGraph";
import { useScopePreview, useWorldbookDraft } from "../hooks/useWorldbookDraft";
import WorldBookScopeManager from "./WorldBookScopeManager";
import WorldBookConfigOverview from "./worldbook/WorldBookConfigOverview";
import WorldBookEntryWorkbench from "./worldbook/WorldBookEntryWorkbench";
import type { WorldBookPanelProps } from "./worldbook/panel";
import WorldBookGraphIcon from "./WorldBookGraphIcon";

/** 默认界面：三个视图。高级图谱里保留原有的分类 / 网络 / 树 / 批量能力。 */
type PageView = "overview" | "entries" | "advanced";

const PAGE_VIEWS: Array<{ id: PageView; label: string; hint: string }> = [
  { id: "overview", label: "配置概览", hint: "基础设定、角色设定、关联补充与待处理，一眼看完并一次保存" },
  { id: "entries", label: "条目与角色", hint: "逐条决定怎么用：加入基础设定、角色入队时选用、同时选用、仅标记相关" },
  { id: "advanced", label: "高级图谱", hint: "分类结构、依赖网络、依赖树与批量操作" },
];

const ADVANCED_VIEWS: Array<{ id: WorldBookGraphView; label: string; icon: "folder" | "link" | "tree"; hint: string }> = [
  { id: "taxonomy", label: "分类结构", icon: "folder", hint: "分类树与条目归属，分类连线不参与依赖展开" },
  { id: "dependencies", label: "条目依赖", icon: "link", hint: "力导向关系网络：按角色着色并逐条检查依赖边" },
  { id: "tree", label: "依赖树", icon: "tree", hint: "按起点与展开方式分层展开，并标出不会展开的边" },
];

export default function WorldBookDependencyPage() {
  const api = useApi();
  const { worldbookScopeJumpId, setWorldbookScopeJumpId } = useAppStore();
  const [books, setBooks] = useState<WorldBookSummary[]>([]);
  const [selected, setSelected] = useState(worldbookScopeJumpId || "");
  const [detail, setDetail] = useState<WorldBookDetail | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<PageView>("overview");
  const [advancedView, setAdvancedView] = useState<WorldBookGraphView>("tree");
  const [roster, setRoster] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const sequence = useRef(0);

  const { draft, patch, dirty, saving, error: saveError, conflict, save, undo, savedAt } = useWorldbookDraft(detail);
  // 预览始终按统一草稿计算：三个视图共用同一份「保存后会长成什么样」。
  const { preview, loading: previewing, error: previewError } =
    useScopePreview(detail?.id || "", detail?.updated_at, draft, roster, [], !!detail);

  useEffect(() => {
    let cancelled = false;
    api.listWorldbooks().then(({ books: result }) => {
      if (cancelled) return;
      setBooks(result); setSelected((id) => id || result[0]?.id || "");
    }).catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [api]);
  useEffect(() => {
    if (worldbookScopeJumpId) { setSelected(worldbookScopeJumpId); setWorldbookScopeJumpId(null); }
  }, [worldbookScopeJumpId, setWorldbookScopeJumpId]);
  const reload = useCallback(async () => {
    const seq = ++sequence.current;
    if (!selected) { setDetail(null); return; }
    setError("");
    try { const value = await api.getWorldbook(selected); if (seq === sequence.current) setDetail(value); }
    catch (e) { if (seq === sequence.current) { setDetail(null); setError(e instanceof Error ? e.message : "加载失败"); } }
  }, [api, selected]);
  useEffect(() => { setDetail(null); setRoster([]); void reload(); return () => { sequence.current++; }; }, [reload]);
  // 保存成功（revision 变化 → 草稿重置）后清掉「已保存」提示之外的状态
  useEffect(() => { if (savedAt) { setNotice("已保存：本次改动一次性写入，正文未被改写。"); } }, [savedAt]);
  useEffect(() => { if (!dirty) return; const prevent = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", prevent); return () => window.removeEventListener("beforeunload", prevent); }, [dirty]);

  const switchBook = (id: string) => {
    if (id === selected) return;
    if (dirty) {
      const choice = window.confirm("切换世界书会丢弃未保存的草稿。\n确定＝丢弃并切换；取消＝留在当前世界书。");
      if (!choice) return;
    }
    setSelected(id); setNotice("");
  };

  const doSave = async () => {
    const ok = await save();
    if (ok) { setNotice(""); await reload(); }
  };

  const panelProps: WorldBookPanelProps | null = detail && draft ? {
    detail, draft, patch, dirty, saving, saveError, conflict, save: doSave, undo,
    preview, previewing, previewError, roster, setRoster,
  } : null;

  return <div className="wbg-page">
    <div className="wbg-page-bar">
      <label>世界书 <select aria-label="依赖图世界书" value={selected} onChange={(event) => switchBook(event.target.value)}>
        <option value="">请选择</option>{books.map((book) => <option key={book.id} value={book.id}>{book.name}{!book.enabled && "（已停用）"}</option>)}
      </select></label>
      <nav className="wbg-view-tabs" aria-label="世界书配置视图">
        {PAGE_VIEWS.map((item) => <button key={item.id} title={item.hint} aria-pressed={view === item.id} onClick={() => setView(item.id)}>
          {item.label}
        </button>)}
      </nav>
      {detail && <div className="wbg-page-status">
        <span className={"wbg-save-state" + (dirty ? " is-dirty" : "")}>{dirty ? "有未保存修改" : "已同步"}</span>
        {dirty && <button className="wbg-button wbg-button-quiet" disabled={saving} onClick={undo}>撤销</button>}
        <button className="wbg-button wbg-button-primary" disabled={saving || !dirty} onClick={() => void doSave()}>
          {saving ? "保存中…" : "保存"}
        </button>
      </div>}
      {view === "advanced" && detail && <nav className="wbg-view-tabs" aria-label="高级图谱视图">
        {ADVANCED_VIEWS.map((item) => <button key={item.id} title={item.hint} aria-pressed={advancedView === item.id} onClick={() => setAdvancedView(item.id)}>
          <WorldBookGraphIcon name={item.icon} size={14} />{item.label}
        </button>)}
      </nav>}
    </div>

    {error && <p role="alert" className="text-xs text-red-300">{error} <button onClick={() => void reload()}>重试</button></p>}
    {saveError && <div role="alert" className="wbg-notice wbg-error">
      <span>{conflict ? "保存被拒绝：" : "保存失败："}{saveError}{conflict && "（你的草稿仍完整保留，可先对照最新数据再保存）"}</span>
      <button onClick={() => void doSave()}>重试保存</button>
    </div>}
    {notice && <div role="status" className="wbg-notice wbg-ok"><span>{notice}</span><button aria-label="关闭" onClick={() => setNotice("")}>×</button></div>}

    {panelProps && view === "overview" &&
      <div className="wbg-page-content"><WorldBookConfigOverview {...panelProps} /></div>}
    {panelProps && view === "entries" &&
      <div className="wbg-page-content"><WorldBookEntryWorkbench {...panelProps} onNotice={setNotice} /></div>}
    {panelProps && view === "advanced" &&
      <div className="wbg-page-content"><WorldBookScopeManager key={detail!.id} detail={detail!} view={advancedView}
        draft={draft} patch={patch} unifiedSave={doSave} unifiedSaving={saving} unifiedDirty={dirty}
        unifiedPreview={preview} unifiedPreviewError={previewError} unifiedUndo={undo} onChanged={reload} /></div>}
    {selected && !detail && !error && <p role="status" className="text-xs text-gray-400 p-4">正在加载图谱…</p>}
    {!selected && !error && <p className="text-xs text-gray-500">先创建或导入世界书，再配置条目依赖。</p>}
  </div>;
}
