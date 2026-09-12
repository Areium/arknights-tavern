/**
 * 角色管理 — 主页直达入口。
 *
 * 内设两个 Tab：
 *  - 角色库：浏览全部可用角色，导入角色卡，查看详情，跳转编辑资料/卡牌。
 *  - 玩家身份：创建、编辑、删除多个玩家身份角色，供创建/切换会话时使用。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useApi } from "../hooks/useApi";
import { useAppStore } from "../stores/appStore";
import MarkdownRenderer from "./MarkdownRenderer";

interface CharacterSummary {
  id: string;
  name: string;
  title?: string;
}

interface IdentitySummary {
  id: string;
  name: string;
  summary: string;
  tags: string[];
}

interface CharacterDetail {
  metadata: Record<string, any>;
  content: string;
}

type ManagerTab = "characters" | "identities";

const AVATAR_URL = (name: string) => `/api/characters/${encodeURIComponent(name)}/avatar`;

const ATTR_LABELS: Record<string, string> = {
  strength: "力量",
  intelligence: "智力",
  emotional_stability: "情绪",
  combat_skill: "战斗",
  originium_arts: "源石",
  charisma: "魅力",
  endurance: "耐力",
  agility: "敏捷",
};

export default function CharacterManager() {
  const api = useApi();
  const { setCurrentView, setContentHubTab, setWorldbookJumpId } = useAppStore();

  const [tab, setTab] = useState<ManagerTab>("characters");

  // ── 角色库 ──
  const [characters, setCharacters] = useState<CharacterSummary[]>([]);
  const [charSearch, setCharSearch] = useState("");
  const [selectedChar, setSelectedChar] = useState<string | null>(null);
  const [charDetail, setCharDetail] = useState<CharacterDetail | null>(null);
  const [charLoading, setCharLoading] = useState(false);
  const [charImporting, setCharImporting] = useState(false);

  // ── 玩家身份 ──
  const [identities, setIdentities] = useState<IdentitySummary[]>([]);
  const [identitySearch, setIdentitySearch] = useState("");
  const [selectedIdentity, setSelectedIdentity] = useState<string | null>(null);
  const [identityLoading, setIdentityLoading] = useState(false);
  const [identitySaving, setIdentitySaving] = useState(false);
  const [isCreating, setIsCreating] = useState(false);

  // 编辑草稿
  const [draftName, setDraftName] = useState("");
  const [draftSummary, setDraftSummary] = useState("");
  const [draftTags, setDraftTags] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [draftAttrs, setDraftAttrs] = useState<Record<string, number>>({});

  const charFileRef = useRef<HTMLInputElement>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [toast, setToast] = useState<{ text: string; type: "ok" | "error" } | null>(null);

  const showToast = (text: string, type: "ok" | "error" = "ok") => {
    setToast({ text, type });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  };

  // ── 加载角色库 ──
  useEffect(() => {
    let cancelled = false;
    api.getCharacters()
      .then((data) => {
        if (!cancelled) {
          const list: CharacterSummary[] = (data || []).map((c: any) => ({
            id: c.id || c.name || "",
            name: c.name || c.title || c.id || "",
            title: c.title,
          }));
          setCharacters(list);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [api]);

  // ── 加载玩家身份列表 ──
  const loadIdentities = () => {
    api.getPlayerIdentities()
      .then((data) => setIdentities(data || []))
      .catch(() => setIdentities([]));
  };

  useEffect(() => {
    loadIdentities();
  }, [api]);

  // ── 加载角色详情 ──
  useEffect(() => {
    if (!selectedChar || tab !== "characters") {
      setCharDetail(null);
      return;
    }
    let cancelled = false;
    setCharLoading(true);
    api.getCharacter(selectedChar)
      .then((d) => { if (!cancelled) setCharDetail(d); })
      .catch(() => { if (!cancelled) setCharDetail(null); })
      .finally(() => { if (!cancelled) setCharLoading(false); });
    return () => { cancelled = true; };
  }, [selectedChar, tab, api]);

  // ── 加载身份详情 ──
  useEffect(() => {
    if (!selectedIdentity || tab !== "identities") {
      return;
    }
    let cancelled = false;
    setIdentityLoading(true);
    api.getCharacter(selectedIdentity)
      .then((d) => {
        if (!cancelled) {
          initDraft(selectedIdentity, d);
        }
      })
      .catch(() => { if (!cancelled) initDraft(selectedIdentity, null); })
      .finally(() => { if (!cancelled) setIdentityLoading(false); });
    return () => { cancelled = true; };
  }, [selectedIdentity, tab, api]);

  const initDraft = (name: string, detail: CharacterDetail | null) => {
    const meta = detail?.metadata || {};
    setDraftName(meta.name || name);
    setDraftSummary(meta.summary || "");
    setDraftTags((meta.tags || []).join("、"));
    setDraftContent(detail?.content || "");
    setDraftAttrs(meta.attributes || {});
  };

  const resetIdentityForm = () => {
    setDraftName("");
    setDraftSummary("");
    setDraftTags("");
    setDraftContent("");
    setDraftAttrs({});
  };

  // ── 导入角色卡 ──
  const handleImportCharacterCard = async (file: File) => {
    setCharImporting(true);
    try {
      const res = await api.importCharacterCard(file);
      showToast(`角色「${res.character?.name || file.name}」已导入`);
      const data = await api.getCharacters();
      setCharacters((data || []).map((c: any) => ({
        id: c.id || c.name || "",
        name: c.name || c.title || c.id || "",
        title: c.title,
      })));
      if (res.character?.name) {
        setTab("characters");
        setSelectedChar(res.character.name);
      }
    } catch (err: any) {
      showToast(err.message || "导入失败", "error");
    } finally {
      setCharImporting(false);
    }
  };

  // ── 保存玩家身份 ──
  const handleSaveIdentity = async () => {
    const name = (isCreating ? draftName : selectedIdentity) || "";
    if (!name.trim()) {
      showToast("身份名称不能为空", "error");
      return;
    }
    setIdentitySaving(true);
    try {
      const tags = draftTags.split(/[、,]/).map((t) => t.trim()).filter(Boolean);
      const metadata: Record<string, any> = {
        name: draftName.trim() || name,
        summary: draftSummary.trim(),
        tags,
        player_identity: true,
      };
      if (Object.keys(draftAttrs).length > 0) {
        metadata.attributes = draftAttrs;
      }
      await api.savePlayerIdentity(name.trim(), metadata, draftContent);
      showToast(isCreating ? "已创建玩家身份" : "已保存玩家身份");
      loadIdentities();
      if (isCreating) {
        setIsCreating(false);
        setSelectedIdentity(name.trim());
      }
    } catch (err: any) {
      showToast(err.message || "保存失败", "error");
    } finally {
      setIdentitySaving(false);
    }
  };

  // ── 删除玩家身份 ──
  const handleDeleteIdentity = async (name: string) => {
    if (!window.confirm(`确定删除玩家身份「${name}」吗？`)) return;
    try {
      await api.deletePlayerIdentity(name);
      showToast("已删除玩家身份");
      setIdentities((prev) => prev.filter((i) => i.id !== name));
      if (selectedIdentity === name) {
        setSelectedIdentity(null);
      }
    } catch (err: any) {
      showToast(err.message || "删除失败", "error");
    }
  };

  // ── 跳转编辑 ──
  // 角色资料已迁移至世界书（整合包/来源标注），跳转世界书页编辑
  const jumpToWorldbook = () => {
    const bookId = String((charDetail?.metadata as any)?.worldbook_id || "");
    setWorldbookJumpId(bookId || null);
    setCurrentView("worldbook");
  };

  const jumpToCards = () => {
    // 通过 content hub 的 cards tab 选中该角色，需要扩展 store 支持
    // 这里先简单跳转到 content/cards，用户再手动选择
    setContentHubTab("cards");
    setCurrentView("content");
  };

  const filteredCharacters = useMemo(() => {
    const q = charSearch.trim().toLowerCase();
    if (!q) return characters;
    return characters.filter((c) =>
      (c.name || "").toLowerCase().includes(q) ||
      (c.id || "").toLowerCase().includes(q)
    );
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

  const renderCharDetail = () => {
    if (!selectedChar) {
      return (
        <div className="flex items-center justify-center h-full text-gray-500 text-sm">
          从左侧选择一个角色查看详情
        </div>
      );
    }
    if (charLoading) {
      return <div className="flex items-center justify-center h-full text-gray-500 text-sm">加载中…</div>;
    }
    const meta = charDetail?.metadata || {};
    const attrs: Record<string, number> = meta.attributes || {};
    const tags: string[] = meta.tags || [];
    return (
      <div className="h-full overflow-y-auto p-5 space-y-4">
        <div className="flex items-start gap-4">
          <img
            src={AVATAR_URL(selectedChar)}
            alt={meta.name || selectedChar}
            className="w-20 h-20 rounded-lg object-cover border border-gray-700 bg-gray-800"
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
          />
          <div className="flex-1 min-w-0">
            <h2 className="text-lg font-semibold text-gray-100 truncate">{meta.name || selectedChar}</h2>
            <div className="flex flex-wrap gap-1.5 mt-2">
              {meta.class && <span className="px-2 py-0.5 rounded bg-blue-700/40 text-blue-200 text-xs">{meta.class}</span>}
              {meta.race && <span className="px-2 py-0.5 rounded bg-purple-700/40 text-purple-200 text-xs">{meta.race}</span>}
              {meta.faction && <span className="px-2 py-0.5 rounded bg-green-700/40 text-green-200 text-xs">{meta.faction}</span>}
            </div>
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {tags.map((t) => <span key={t} className="px-1.5 py-0.5 rounded bg-gray-700/50 text-gray-300 text-xs">{t}</span>)}
              </div>
            )}
          </div>
        </div>

        {Object.keys(attrs).length > 0 && (
          <div>
            <h3 className="text-xs text-gray-500 mb-2 font-medium">属性</h3>
            <div className="grid grid-cols-4 gap-2">
              {Object.entries(attrs).map(([k, v]) => (
                <div key={k} className="flex flex-col items-center px-2 py-1.5 rounded bg-gray-800 border border-gray-700">
                  <span className="text-gray-400 text-[10px]">{ATTR_LABELS[k] || k}</span>
                  <span className="text-gray-200 font-mono text-sm">{v}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {charDetail?.content && (
          <div>
            <h3 className="text-xs text-gray-500 mb-2 font-medium">背景</h3>
            <div className="text-sm text-gray-300 leading-relaxed bg-gray-800/50 rounded-lg p-3 border border-gray-700">
              <MarkdownRenderer content={charDetail.content} />
            </div>
          </div>
        )}

        <div className="flex flex-wrap gap-2 pt-2">
          <button
            onClick={jumpToWorldbook}
            className="text-xs px-3 py-1.5 rounded bg-blue-600/20 text-blue-300 hover:bg-blue-600/40 transition-colors"
            title="角色设定已迁移至世界书，跳转世界书页编辑"
          >
            📖 编辑世界书设定
          </button>
          <button
            onClick={() => jumpToCards()}
            className="text-xs px-3 py-1.5 rounded bg-amber-600/20 text-amber-300 hover:bg-amber-600/40 transition-colors"
          >
            🃏 编辑战斗卡牌
          </button>
        </div>
      </div>
    );
  };

  const renderIdentityDetail = () => {
    if (isCreating) {
      return renderIdentityEditor();
    }
    if (!selectedIdentity) {
      return (
        <div className="flex flex-col items-center justify-center h-full text-gray-500 text-sm gap-3">
          <span>从左侧选择一个玩家身份，或点击「新建身份」</span>
          <button
            onClick={() => { resetIdentityForm(); setIsCreating(true); }}
            className="text-xs px-3 py-1.5 rounded bg-amber-600/20 text-amber-300 hover:bg-amber-600/40 transition-colors"
          >
            ＋ 新建身份
          </button>
        </div>
      );
    }
    if (identityLoading) {
      return <div className="flex items-center justify-center h-full text-gray-500 text-sm">加载中…</div>;
    }
    return renderIdentityEditor();
  };

  const renderIdentityEditor = () => {
    return (
      <div className="h-full overflow-y-auto p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-200">
            {isCreating ? "新建玩家身份" : "编辑玩家身份"}
          </h2>
          {!isCreating && selectedIdentity && (
            <button
              onClick={() => selectedIdentity && handleDeleteIdentity(selectedIdentity)}
              className="text-xs px-2.5 py-1 rounded bg-red-700/20 text-red-300 hover:bg-red-700/40 transition-colors"
            >
              🗑 删除
            </button>
          )}
        </div>

        <div className="space-y-3">
          <label className="block text-xs text-gray-400">
            身份名称
            <input
              className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200"
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              placeholder="例如：博士、罗德岛新兵、龙门侦探"
            />
          </label>

          <label className="block text-xs text-gray-400">
            简介
            <input
              className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200"
              value={draftSummary}
              onChange={(e) => setDraftSummary(e.target.value)}
              placeholder="一句话描述这个身份"
            />
          </label>

          <label className="block text-xs text-gray-400">
            标签（、分隔）
            <input
              className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200"
              value={draftTags}
              onChange={(e) => setDraftTags(e.target.value)}
              placeholder="例如：指挥官、感染者、战术专家"
            />
          </label>

          <div>
            <label className="text-xs text-gray-400 mb-1 block">属性（可选）</label>
            <div className="grid grid-cols-4 gap-2">
              {Object.entries(ATTR_LABELS).map(([key, label]) => (
                <div key={key} className="flex flex-col items-center gap-0.5">
                  <span className="text-[10px] text-gray-500">{label}</span>
                  <input
                    className="w-full bg-gray-900 border border-gray-700 rounded px-1 py-1 text-xs text-center text-gray-200"
                    type="number"
                    min={1}
                    max={10}
                    value={draftAttrs[key] ?? ""}
                    onChange={(e) => setDraftAttrs({ ...draftAttrs, [key]: parseInt(e.target.value) || 0 })}
                  />
                </div>
              ))}
            </div>
          </div>

          <label className="block text-xs text-gray-400">
            身份背景
            <textarea
              className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 min-h-[160px]"
              value={draftContent}
              onChange={(e) => setDraftContent(e.target.value)}
              placeholder="描述这个身份的背景、性格、目标……"
            />
          </label>
        </div>

        <div className="flex items-center gap-2 pt-2">
          <button
            onClick={handleSaveIdentity}
            disabled={identitySaving || !draftName.trim()}
            className="text-xs px-4 py-1.5 rounded bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-50 transition-colors"
          >
            {identitySaving ? "保存中…" : "保存身份"}
          </button>
          {isCreating && (
            <button
              onClick={() => { setIsCreating(false); resetIdentityForm(); }}
              className="text-xs px-3 py-1.5 rounded bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
            >
              取消
            </button>
          )}
        </div>

        <p className="text-[11px] text-gray-600 leading-relaxed">
          提示：玩家身份就是一份特殊的角色卡，保存后可在创建会话或会话大厅中选择使用。
          头像请前往「内容中心 → 资产」为该身份上传 avatar 图片。
        </p>
      </div>
    );
  };

  return (
    <div className="flex h-full">
      {/* ── 左侧列表 ── */}
      <div className="w-72 border-r border-gray-700 flex flex-col shrink-0">
        {/* Tabs */}
        <div className="flex items-center gap-1 p-2 border-b border-gray-700">
          <button
            onClick={() => setTab("characters")}
            className={`flex-1 text-xs px-2 py-1.5 rounded transition-colors ${tab === "characters" ? "bg-blue-600/30 text-blue-300" : "text-gray-500 hover:text-gray-300"}`}
          >
            角色库
          </button>
          <button
            onClick={() => setTab("identities")}
            className={`flex-1 text-xs px-2 py-1.5 rounded transition-colors ${tab === "identities" ? "bg-amber-600/30 text-amber-300" : "text-gray-500 hover:text-gray-300"}`}
          >
            玩家身份
          </button>
        </div>

        {/* Toolbar */}
        <div className="p-2 border-b border-gray-700 space-y-2">
          <input
            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 placeholder:text-gray-600"
            placeholder={tab === "characters" ? "搜索角色…" : "搜索身份…"}
            value={tab === "characters" ? charSearch : identitySearch}
            onChange={(e) => tab === "characters" ? setCharSearch(e.target.value) : setIdentitySearch(e.target.value)}
          />
          {tab === "characters" ? (
            <>
              <button
                onClick={() => charFileRef.current?.click()}
                disabled={charImporting}
                className="w-full text-xs px-2 py-1.5 rounded bg-amber-600/20 text-amber-300 hover:bg-amber-600/40 disabled:opacity-50 transition-colors"
              >
                {charImporting ? "导入中…" : "⬆ 导入角色卡"}
              </button>
              <input
                ref={charFileRef}
                type="file"
                accept=".png,.json,.webp,.jpg,.jpeg"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) { void handleImportCharacterCard(f); e.target.value = ""; }
                }}
              />
            </>
          ) : (
            <button
              onClick={() => { resetIdentityForm(); setSelectedIdentity(null); setIsCreating(true); }}
              className="w-full text-xs px-2 py-1.5 rounded bg-amber-600/20 text-amber-300 hover:bg-amber-600/40 transition-colors"
            >
              ＋ 新建身份
            </button>
          )}
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {tab === "characters" ? (
            filteredCharacters.length === 0 ? (
              <p className="text-xs text-gray-600 text-center py-4">
                {charSearch ? "未找到匹配角色" : "暂无可用角色"}
              </p>
            ) : (
              filteredCharacters.map((c) => (
                <button
                  key={c.id}
                  onClick={() => setSelectedChar(c.id)}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left transition-colors ${
                    selectedChar === c.id
                      ? "bg-blue-600/20 text-blue-300 border border-blue-600/30"
                      : "text-gray-300 hover:bg-gray-800"
                  }`}
                >
                  <img
                    src={AVATAR_URL(c.id)}
                    alt={c.name}
                    className="w-8 h-8 rounded object-cover border border-gray-700 bg-gray-800 shrink-0"
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
                  />
                  <div className="min-w-0">
                    <div className="text-xs font-medium truncate">{c.name || c.id}</div>
                    {c.title && <div className="text-[10px] text-gray-500 truncate">{c.title}</div>}
                  </div>
                </button>
              ))
            )
          ) : (
            filteredIdentities.length === 0 && !isCreating ? (
              <div className="text-center py-4">
                <p className="text-xs text-gray-600 mb-2">还没有玩家身份</p>
                <button
                  onClick={() => { resetIdentityForm(); setIsCreating(true); }}
                  className="text-xs px-2 py-1 rounded bg-amber-600/20 text-amber-300 hover:bg-amber-600/40 transition-colors"
                >
                  新建身份
                </button>
              </div>
            ) : (
              filteredIdentities.map((i) => (
                <button
                  key={i.id}
                  onClick={() => { setIsCreating(false); setSelectedIdentity(i.id); }}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left transition-colors ${
                    selectedIdentity === i.id && !isCreating
                      ? "bg-amber-600/20 text-amber-300 border border-amber-600/30"
                      : "text-gray-300 hover:bg-gray-800"
                  }`}
                >
                  <img
                    src={AVATAR_URL(i.id)}
                    alt={i.name}
                    className="w-8 h-8 rounded object-cover border border-gray-700 bg-gray-800 shrink-0"
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }}
                  />
                  <div className="min-w-0">
                    <div className="text-xs font-medium truncate">{i.name || i.id}</div>
                    {i.summary && <div className="text-[10px] text-gray-500 truncate">{i.summary}</div>}
                  </div>
                </button>
              ))
            )
          )}
        </div>
      </div>

      {/* ── 右侧详情 ── */}
      <div className="flex-1 min-w-0 bg-gray-900/30">
        {tab === "characters" ? renderCharDetail() : renderIdentityDetail()}
      </div>

      {/* Toast */}
      {toast && (
        <div
          className={`fixed bottom-12 right-4 px-3 py-2 rounded-lg text-sm shadow-lg z-50 ${
            toast.type === "ok" ? "bg-green-700/90 text-white" : "bg-red-700/90 text-white"
          }`}
        >
          {toast.text}
        </div>
      )}
    </div>
  );
}
