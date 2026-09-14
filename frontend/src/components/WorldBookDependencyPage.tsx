import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "../hooks/useApi";
import { useAppStore } from "../stores/appStore";
import type { WorldBookDetail, WorldBookSummary } from "../types";
import type { WorldBookGraphView } from "../utils/worldbookGraph";
import WorldBookScopeManager from "./WorldBookScopeManager";
import WorldBookGraphIcon from "./WorldBookGraphIcon";

const VIEWS: Array<{ id: WorldBookGraphView; label: string; icon: "folder" | "link" | "tree"; hint: string }> = [
  { id: "taxonomy", label: "分类结构", icon: "folder", hint: "分类树与条目归属，分类连线不参与依赖展开" },
  { id: "dependencies", label: "条目依赖", icon: "link", hint: "力导向关系网络：按角色着色并逐条检查依赖边" },
  { id: "tree", label: "依赖树", icon: "tree", hint: "按导入源与遍历深度分层展开，并标出不会展开的边" },
];

export default function WorldBookDependencyPage() {
  const api = useApi();
  const { worldbookScopeJumpId, setWorldbookScopeJumpId } = useAppStore();
  const [books, setBooks] = useState<WorldBookSummary[]>([]);
  const [selected, setSelected] = useState(worldbookScopeJumpId || "");
  const [detail, setDetail] = useState<WorldBookDetail | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<WorldBookGraphView>("tree");
  const [dirty, setDirty] = useState(false);
  const sequence = useRef(0);
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
  useEffect(() => { setDetail(null); void reload(); return () => { sequence.current++; }; }, [reload]);
  return <div className="wbg-page">
    <div className="wbg-page-bar">
      <label>世界书 <select aria-label="依赖图世界书" value={selected} onChange={(event) => {
        if (!dirty || window.confirm("切换世界书会丢弃未保存的策略草稿，继续吗？")) setSelected(event.target.value);
      }}>
        <option value="">请选择</option>{books.map((book) => <option key={book.id} value={book.id}>{book.name}{!book.enabled && "（已停用）"}</option>)}
      </select></label>
      <nav className="wbg-view-tabs" aria-label="世界书图谱视图">
        {VIEWS.map((item) => <button key={item.id} title={item.hint} aria-pressed={view === item.id} onClick={() => setView(item.id)}>
          <WorldBookGraphIcon name={item.icon} size={14} />{item.label}
        </button>)}
      </nav>
    </div>
    {error && <p role="alert" className="text-xs text-red-300">{error} <button onClick={() => void reload()}>重试</button></p>}
    {detail && <div className="wbg-page-content"><WorldBookScopeManager key={detail.id} detail={detail} view={view} onChanged={reload} onDirtyChange={setDirty} /></div>}
    {selected && !detail && !error && <p role="status" className="text-xs text-gray-400 p-4">正在加载图谱…</p>}
    {!selected && !error && <p className="text-xs text-gray-500">先创建或导入世界书，再配置条目依赖。</p>}
  </div>;
}
