/**
 * 内容中心 — 资产/世界书/索引三模块整合后的统一管理入口。
 *
 * 管理模式：
 *  - 单一入口：导航仅保留「内容中心」，内部按 Tab 组织（文档/世界书/索引/资产/卡牌）。
 *  - 统一来源：内置（builtin，只读开箱即用）与导入（imported，自由扩展）内容徽章区分。
 *  - 统一检索：顶部搜索框跨世界书条目/文档检索，命中可一键跳转对应 Tab。
 *  - 依赖管理收敛到「索引」Tab（文档 Tab 内仅保留跳转入口，消除重复实现）。
 */
import { useEffect, useRef, useState } from "react";
import { useApi } from "../hooks/useApi";
import { useAppStore, type ContentHubTab } from "../stores/appStore";
import type { WorldBookSearchHit } from "../types";
import SourceBadge from "./SourceBadge";
import DocumentManager from "./DocumentManager";
import WorldBookManager from "./WorldBookManager";
import IndexManager from "./IndexManager";

const TABS: { id: ContentHubTab; label: string; icon: string; hint: string }[] = [
  { id: "docs", label: "角色·剧情", icon: "📜", hint: "角色资料与剧情文档（内置开箱即用）" },
  { id: "worldbook", label: "世界书", icon: "📖", hint: "关键词触发式设定注入（内置 + 导入）" },
  { id: "index", label: "索引", icon: "🔗", hint: "文档依赖关系与会话白名单" },
  { id: "images", label: "资产", icon: "🖼️", hint: "图片资产上传 / 裁剪 / 默认图" },
  { id: "cards", label: "卡牌", icon: "🃏", hint: "角色与职业卡牌编辑" },
];

export default function ContentHub() {
  const api = useApi();
  const { contentHubTab, setContentHubTab, setCurrentView, worldbookJumpId, setWorldbookJumpId, setDocJumpTarget } = useAppStore();
  const [query, setQuery] = useState("");
  const [wbHits, setWbHits] = useState<WorldBookSearchHit[]>([]);
  const [docHits, setDocHits] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const searchSeq = useRef(0);

  // 世界书跳转（检索结果点击 / 其他模块联动）→ 世界书 Tab 选中该书（由 WorldBookManager 消费并清除）
  useEffect(() => {
    if (worldbookJumpId) {
      setContentHubTab("worldbook");
    }
  }, [worldbookJumpId, setContentHubTab]);

  // 统一检索：跨世界书条目 + 文档
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setWbHits([]);
      setDocHits([]);
      setSearchOpen(false);
      return;
    }
    const seq = ++searchSeq.current;
    setSearching(true);
    const timer = setTimeout(async () => {
      try {
        const [wb, docs] = await Promise.all([
          api.searchWorldbooks(q, 5),
          api.searchDocuments(q).catch(() => []),
        ]);
        if (seq !== searchSeq.current) return;
        setWbHits(wb.results || []);
        setDocHits((docs as any[]) || []);
        setSearchOpen(true);
      } catch {
        /* 后端不可用 */
      } finally {
        if (seq === searchSeq.current) setSearching(false);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [query, api]);

  const jumpWorldbook = (bookId: string) => {
    setWorldbookJumpId(bookId);
    setQuery("");
  };

  const jumpTab = (tab: ContentHubTab) => {
    setContentHubTab(tab);
    setQuery("");
  };

  return (
    <div className="flex flex-col h-full">
      {/* ── 统一顶栏：Tab 切换 + 统一检索 ── */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-700/70 bg-gray-900/60 shrink-0">
        <button
          onClick={() => setCurrentView("home")}
          className="text-xs text-gray-500 hover:text-amber-300 transition-colors shrink-0"
          title="返回主菜单"
        >
          ◀ 主菜单
        </button>
        <div className="w-px h-5 bg-gray-700/70" />
        <nav className="flex items-center gap-1 overflow-x-auto">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => jumpTab(t.id)}
              title={t.hint}
              className={
                "flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs whitespace-nowrap transition-colors " +
                (contentHubTab === t.id
                  ? "bg-amber-600/20 text-amber-300 font-medium border border-amber-500/30"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/50 border border-transparent")
              }
            >
              <span>{t.icon}</span>
              <span>{t.label}</span>
            </button>
          ))}
        </nav>

        {/* 统一检索 */}
        <div className="flex-1" />
        <div className="relative w-72 shrink-0">
          <input
            className="w-full bg-gray-800/80 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-200 outline-none focus:border-amber-500/50 placeholder:text-gray-600"
            placeholder="🔍 搜索世界书条目 / 角色 / 剧情…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => query.trim() && setSearchOpen(true)}
            onBlur={() => setTimeout(() => setSearchOpen(false), 200)}
          />
          {searching && (
            <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] text-gray-500">…</span>
          )}
          {searchOpen && (wbHits.length > 0 || docHits.length > 0) && (
            <div className="absolute right-0 top-full mt-1 w-[26rem] max-h-96 overflow-y-auto rounded-lg border border-gray-700 bg-gray-900/98 backdrop-blur shadow-xl z-50 text-left">
              {wbHits.length > 0 && (
                <div className="p-2">
                  <p className="text-[10px] text-gray-500 px-1 mb-1">世界书条目</p>
                  <div className="space-y-0.5">
                    {wbHits.map((h) => (
                      <button
                        key={h.book.id}
                        className="w-full flex items-center gap-2 rounded px-2 py-1.5 hover:bg-gray-800 text-left"
                        onClick={() => jumpWorldbook(h.book.id)}
                      >
                        <SourceBadge source={h.book.source} size="xs" />
                        <span className="text-xs text-gray-200 truncate flex-1">{h.book.name}</span>
                        <span className="text-[10px] text-gray-500 shrink-0">{h.match_count} 条命中</span>
                        <span className="text-[10px] text-amber-400 shrink-0">查看 →</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {docHits.length > 0 && (
                <div className="p-2 border-t border-gray-800">
                  <p className="text-[10px] text-gray-500 px-1 mb-1">角色 / 剧情文档</p>
                  <div className="space-y-0.5">
                    {(docHits as any[]).slice(0, 8).map((d) => (
                      <button
                        key={d.path || d.id}
                        className="w-full flex items-center gap-2 rounded px-2 py-1.5 hover:bg-gray-800 text-left"
                        onMouseDown={() => {
                          setDocJumpTarget({ category: d.category, id: d.id });
                          setContentHubTab("docs");
                          setQuery("");
                        }}
                      >
                        <SourceBadge source="builtin" size="xs" />
                        <span className="text-xs text-gray-200 truncate flex-1">{d.title || d.id}</span>
                        <span className="text-[10px] text-gray-500 shrink-0 font-mono">{d.path || d.id}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          {searchOpen && query.trim() && wbHits.length === 0 && docHits.length === 0 && !searching && (
            <div className="absolute right-0 top-full mt-1 w-72 rounded-lg border border-gray-700 bg-gray-900/98 shadow-xl z-50 p-3 text-center text-xs text-gray-500">
              无匹配结果
            </div>
          )}
        </div>
      </div>

      {/* ── Tab 内容区 ── */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {contentHubTab === "docs" && <DocumentManager key="dm-docs" initialTab="docs" />}
        {contentHubTab === "images" && <DocumentManager key="dm-images" initialTab="images" />}
        {contentHubTab === "cards" && <DocumentManager key="dm-cards" initialTab="cards" />}
        {contentHubTab === "worldbook" && <WorldBookManager key="wbm" />}
        {contentHubTab === "index" && <IndexManager key="im" />}
      </div>
    </div>
  );
}
