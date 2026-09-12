/**
 * 内容中心 — 资产/卡牌/索引/节点图等模块整合后的统一管理入口。
 *
 * 管理模式：
 *  - 单一入口：导航仅保留「内容中心」，内部按 Tab 组织（索引/资产/卡牌/节点图）。
 *  - 返回入口唯一：页面级返回走全局顶栏 GameTopBar（本页不再放返回按钮）。
 *  - 统一来源：资产/卡牌标注来源世界书（worldbook_id），支持按书筛选。
 *  - 统一检索：顶部搜索框跨世界书条目检索，命中可一键跳转到「世界书」页。
 *  - 依赖管理收敛到「索引」Tab。
 *  - 世界书不在内部重复承载：上一级导航「世界书」页为唯一入口（检索命中直接跳该页）。
 *  - 文档管理已移除：世界观语料经 scripts/generate_builtin_worldbook.py 整理为
 *    「世界书整合包」（data/packs/arknights.json），随世界书导入/预装分发。
 *  - 战斗节点编辑：先选世界书再编辑（NodeFlowEditor），节点数据归属所选世界书。
 */
import { useEffect, useRef, useState } from "react";
import { useApi } from "../hooks/useApi";
import { useAppStore, type ContentHubTab } from "../stores/appStore";
import type { WorldBookSearchHit } from "../types";
import SourceBadge from "./SourceBadge";
import AssetManager from "./AssetManager";
import CardManager from "./CardManager";
import IndexManager from "./IndexManager";
import NodeFlowEditor from "./combat/NodeFlowEditor";

const TABS: { id: ContentHubTab; label: string; icon: string; hint: string }[] = [
  { id: "index", label: "索引", icon: "🔗", hint: "文档依赖关系与会话白名单" },
  { id: "images", label: "资产", icon: "🖼️", hint: "图片资产上传 / 裁剪 / 默认图 / 来源世界书" },
  { id: "cards", label: "卡牌", icon: "🃏", hint: "角色与职业卡牌编辑 / 所属世界书" },
  { id: "combat", label: "节点图", icon: "⚔", hint: "按世界书编排剧情与战斗节点" },
];

export default function ContentHub() {
  const api = useApi();
  const { contentHubTab, setContentHubTab, setCurrentView, worldbookJumpId, setWorldbookJumpId, activeSessionId } = useAppStore();
  const [query, setQuery] = useState("");
  const [wbHits, setWbHits] = useState<WorldBookSearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const searchSeq = useRef(0);

  // 世界书跳转（检索结果点击 / 其他模块联动）→ 上一级「世界书」页选中该书（由 WorldBookManager 消费并清除）
  useEffect(() => {
    if (worldbookJumpId) {
      setCurrentView("worldbook");
    }
  }, [worldbookJumpId, setCurrentView]);

  // 统一检索：跨世界书条目
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setWbHits([]);
      setSearchOpen(false);
      return;
    }
    const seq = ++searchSeq.current;
    setSearching(true);
    const timer = setTimeout(async () => {
      try {
        const wb = await api.searchWorldbooks(q, 5);
        if (seq !== searchSeq.current) return;
        setWbHits(wb.results || []);
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
      {/* ── 统一顶栏：Tab 切换 + 统一检索（返回主菜单走全局顶栏） ── */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-700/70 bg-gray-900/60 shrink-0">
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
            placeholder="🔍 搜索世界书条目…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => query.trim() && setSearchOpen(true)}
            onBlur={() => setTimeout(() => setSearchOpen(false), 200)}
          />
          {searching && (
            <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] text-gray-500">…</span>
          )}
          {searchOpen && wbHits.length > 0 && (
            <div className="absolute right-0 top-full mt-1 w-[26rem] max-h-96 overflow-y-auto rounded-lg border border-gray-700 bg-gray-900/98 backdrop-blur shadow-xl z-50 text-left">
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
            </div>
          )}
          {searchOpen && query.trim() && wbHits.length === 0 && !searching && (
            <div className="absolute right-0 top-full mt-1 w-72 rounded-lg border border-gray-700 bg-gray-900/98 shadow-xl z-50 p-3 text-center text-xs text-gray-500">
              无匹配结果
            </div>
          )}
        </div>
      </div>

      {/* ── Tab 内容区 ── */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {contentHubTab === "index" && <IndexManager key="im" />}
        {contentHubTab === "images" && <AssetManager key="am" />}
        {contentHubTab === "cards" && <CardManager key="cm" />}
        {contentHubTab === "combat" && (
          <NodeFlowEditor
            key="nfe"
            sessionId={activeSessionId}
          />
        )}
      </div>
    </div>
  );
}
