/**
 * 卡牌管理 — 角色卡牌与职业卡牌编辑。
 *
 * 由内容中心「卡牌」Tab 挂载（原 DocumentManager 卡牌 Tab 独立成组件）。
 *
 * 来源标注：每个角色/职业条目显示所属世界书（index.md frontmatter 的
 * worldbook_id），支持按世界书筛选，详情面板可修改归属。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "../hooks/useApi";
import type { CardsTreeDTO, WorldBookSummary } from "../types";
import CardEditor from "./combat/CardEditor";
import { WorldbookSelect } from "./AssetManager";

interface ToastState {
  message: string;
  type: "success" | "error";
}

export default function CardManager() {
  const api = useApi();
  const apiRef = useRef(api);
  apiRef.current = api;

  // ── 数据 ──
  const [cardsTree, setCardsTree] = useState<CardsTreeDTO | null>(null);
  const [worldbooks, setWorldbooks] = useState<WorldBookSummary[]>([]);
  /** 来源筛选："" = 全部，"__none__" = 未标注，否则为 book id */
  const [bookFilter, setBookFilter] = useState("");
  const [collapsed, setCollapsed] = useState<{ characters: boolean; classes: boolean }>({ characters: false, classes: false });
  const [selectedCardEntity, setSelectedCardEntity] = useState<string | null>(null);
  const [selectedCardEntityType, setSelectedCardEntityType] = useState<"character" | "class" | null>(null);

  // ── Toast ──
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout>>();
  const showToast = useCallback((message: string, type: "success" | "error" = "success") => {
    setToast({ message, type });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  }, []);

  const loadCardsTree = useCallback(async () => {
    try {
      const data = await apiRef.current.getCardsTree();
      setCardsTree(data);
    } catch { /* ignore */ }
  }, []);

  const loadWorldbooks = useCallback(async () => {
    try {
      const res = await apiRef.current.listWorldbooks();
      setWorldbooks(res.books || []);
    } catch { /* 后端不可用时不阻塞卡牌管理 */ }
  }, []);

  useEffect(() => {
    loadCardsTree();
    loadWorldbooks();
  }, [loadCardsTree, loadWorldbooks]);

  const bookName = (id: string) => worldbooks.find((b) => b.id === id)?.name || id;
  const bookOf = (type: "character" | "class", name: string) =>
    (type === "character"
      ? cardsTree?.worldbook_map?.characters?.[name]
      : cardsTree?.worldbook_map?.classes?.[name]) || "";

  /** 修改角色/职业的所属世界书标注 */
  const handleSetWorldbook = async (type: "character" | "class", name: string, bookId: string) => {
    const category = type === "character" ? "characters" : "classes";
    try {
      await apiRef.current.setEntityWorldbook(category, name, bookId);
      showToast(bookId ? "所属世界书已标注" : "已清除标注");
      setCardsTree((prev) => {
        if (!prev?.worldbook_map) return prev;
        const map = prev.worldbook_map;
        return {
          ...prev,
          worldbook_map: {
            characters: type === "character" ? { ...map.characters, [name]: bookId } : { ...map.characters },
            classes: type === "class" ? { ...map.classes, [name]: bookId } : { ...map.classes },
          },
        };
      });
    } catch (err: any) {
      showToast(err.message || "标注失败", "error");
    }
  };

  /** 筛选：保留有匹配来源的条目 */
  const matchBook = (type: "character" | "class", name: string) => {
    if (!bookFilter) return true;
    const id = bookOf(type, name);
    return bookFilter === "__none__" ? !id : id === bookFilter;
  };

  const characters = (cardsTree?.characters || []).filter((n) => matchBook("character", n));
  const classes = (cardsTree?.classes || []).filter((n) => matchBook("class", n));

  const renderEntityRow = (type: "character" | "class", name: string) => {
    const selected = selectedCardEntity === name && selectedCardEntityType === type;
    const bookId = bookOf(type, name);
    return (
      <div
        key={`${type}-${name}`}
        className={`group flex items-center gap-1 cursor-pointer rounded text-sm transition-colors select-none py-0.5 ${
          selected
            ? "bg-blue-600/20 text-blue-300"
            : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/50"
        }`}
        style={{ paddingLeft: 20 }}
        onClick={() => {
          setSelectedCardEntity(name);
          setSelectedCardEntityType(type);
        }}
      >
        <span className={`w-4 text-center shrink-0 ${type === "character" ? "text-purple-500" : "text-amber-500"}`}>🃏</span>
        <span className="truncate">{name}</span>
        {type === "character" && cardsTree?.character_class_map[name] && (
          <span className="text-[10px] text-gray-600 ml-1">{cardsTree.character_class_map[name]}</span>
        )}
        {bookId ? (
          <span
            className="text-[9px] px-1 rounded bg-amber-600/15 text-amber-300 border border-amber-700/40 shrink-0 ml-1 max-w-[8rem] truncate"
            title={`所属世界书：${bookName(bookId)}`}
          >
            📖 {bookName(bookId)}
          </span>
        ) : (
          <span className="text-[9px] text-gray-600 shrink-0 ml-1 opacity-0 group-hover:opacity-100" title="未标注所属世界书">
            未标注
          </span>
        )}
      </div>
    );
  };

  return (
    <div className="flex h-full">
      {/* ── 卡牌树侧栏 ── */}
      <div className="w-72 border-r border-gray-700 overflow-y-auto p-3 shrink-0" id="card-tree-sidebar">
        <div className="flex items-center gap-1 mb-3">
          <span className="text-xs px-3 py-1 rounded bg-blue-600/30 text-blue-300">🃏 卡牌</span>
          <div className="flex-1" />
          <button
            onClick={loadCardsTree}
            className="text-xs text-gray-500 hover:text-gray-300"
            title="刷新"
          >
            ↻
          </button>
        </div>

        <select
          className="w-full bg-gray-800/80 border border-gray-700 rounded px-2 py-1 text-[11px] text-gray-300 mb-2"
          value={bookFilter}
          onChange={(e) => setBookFilter(e.target.value)}
          title="按所属世界书筛选"
        >
          <option value="">📚 全部世界书</option>
          <option value="__none__">未标注来源</option>
          {worldbooks.map((b) => (
            <option key={b.id} value={b.id}>📖 {b.name}</option>
          ))}
        </select>

        {!cardsTree ? (
          <p className="text-gray-500 text-sm text-center py-4">加载中...</p>
        ) : (
          <div className="space-y-2">
            {/* Characters group */}
            <div>
              <div
                className="flex items-center gap-1 cursor-pointer rounded text-xs font-medium text-gray-400 hover:text-gray-200 py-0.5 select-none"
                onClick={() => setCollapsed((c) => ({ ...c, characters: !c.characters }))}
              >
                <span className="w-3 text-center shrink-0">{collapsed.characters ? "▶" : "▼"}</span>
                <span>角色卡牌</span>
                <span className="text-[10px] text-gray-600">({characters.length})</span>
              </div>
              {!collapsed.characters && (
                <div className="ml-3 border-l border-gray-700/30 pl-2">
                  {characters.length === 0 ? (
                    <p className="text-xs text-gray-600 italic pl-5">(空)</p>
                  ) : (
                    characters.map((name) => renderEntityRow("character", name))
                  )}
                </div>
              )}
            </div>

            {/* Classes group */}
            <div>
              <div
                className="flex items-center gap-1 cursor-pointer rounded text-xs font-medium text-gray-400 hover:text-gray-200 py-0.5 select-none"
                onClick={() => setCollapsed((c) => ({ ...c, classes: !c.classes }))}
              >
                <span className="w-3 text-center shrink-0">{collapsed.classes ? "▶" : "▼"}</span>
                <span>职业卡牌</span>
                <span className="text-[10px] text-gray-600">({classes.length})</span>
              </div>
              {!collapsed.classes && (
                <div className="ml-3 border-l border-gray-700/30 pl-2">
                  {classes.length === 0 ? (
                    <p className="text-xs text-gray-600 italic pl-5">(空)</p>
                  ) : (
                    classes.map((name) => renderEntityRow("class", name))
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── 卡牌编辑器面板 ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {!selectedCardEntity || !selectedCardEntityType ? (
          <div className="flex items-center justify-center h-full text-gray-500">
            <p>选择左侧卡牌进行编辑</p>
          </div>
        ) : (
          <div className="flex flex-col h-full">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
              <h2 className="text-sm font-medium text-gray-300 truncate max-w-[40%]">
                {selectedCardEntityType === "character" ? "角色" : "职业"}: {selectedCardEntity}
              </h2>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-gray-500">所属世界书</span>
                <WorldbookSelect
                  value={bookOf(selectedCardEntityType, selectedCardEntity)}
                  worldbooks={worldbooks}
                  onChange={(id) => handleSetWorldbook(selectedCardEntityType, selectedCardEntity, id)}
                />
                <button
                  onClick={() => { setSelectedCardEntity(null); setSelectedCardEntityType(null); }}
                  className="text-xs text-gray-500 hover:text-gray-300"
                >
                  ✕ 关闭
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-hidden">
              <CardEditor
                key={`${selectedCardEntityType}-${selectedCardEntity}`}
                embedded
                entityName={selectedCardEntity}
                entityType={selectedCardEntityType}
              />
            </div>
          </div>
        )}
      </div>

      {toast && (
        <div
          className={`fixed bottom-16 right-6 px-4 py-2 rounded-lg shadow-lg text-sm z-50 ${
            toast.type === "success"
              ? "bg-green-800/90 text-green-100"
              : "bg-red-800/90 text-red-100"
          }`}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}
