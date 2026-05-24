import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import type { IndexConfigTree, IndexConfigTreeDoc } from "../types";

// ── Helpers ──

const CATEGORY_LABELS: Record<string, string> = {
  characters: "角色",
  factions: "势力",
  items: "物品",
  locations: "地点",
  plots: "剧情",
  races: "种族",
  classes: "职业",
  enemies: "叙事敌人",
  combat_enemies: "战斗敌人",
  combat_cards: "卡牌",
  combat_encounters: "遭遇战",
  weather: "天气",
  world: "世界观",
  attributes: "属性",
  rules: "规则",
};

function catLabel(cat: string): string {
  return CATEGORY_LABELS[cat] || cat;
}

/** 在树中找到指定文档，对其 doc 执行 mutate，返回新树。 */
function patchTreeDoc(
  tree: IndexConfigTree,
  docPath: string,
  mutate: (doc: any) => void
): IndexConfigTree {
  return {
    ...tree,
    categories: tree.categories.map((cat) => ({
      ...cat,
      docs: cat.docs.map((doc) => {
        if (doc.path === docPath) {
          mutate(doc);
          return { ...doc };
        }
        return doc;
      }) as any,
    })),
  };
}

interface Props {
  api: any;
}

export default function IndexManager({ api }: Props) {
  const apiRef = useRef(api);
  apiRef.current = api;

  // ── Data state ──
  const [tree, setTree] = useState<IndexConfigTree | null>(null);
  const [config, setConfig] = useState<Record<string, Record<string, string[]>>>({});
  const [entities, setEntities] = useState<Record<string, any[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // ── Config source state ──
  const [configSources, setConfigSources] = useState<any[]>([]);
  const [activeSourceId, setActiveSourceId] = useState<string>("global");
  const activeSourceIdRef = useRef(activeSourceId);
  activeSourceIdRef.current = activeSourceId;
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  // ── UI state ──
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null);
  const [expandedCats, setExpandedCats] = useState<Set<string>>(new Set());
  const [expandedDocs, setExpandedDocs] = useState<Set<string>>(new Set());
  const [catFilter, setCatFilter] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [scanResults, setScanResults] = useState<Record<string, any> | null>(null);
  const [showAddDropdown, setShowAddDropdown] = useState<string | null>(null);
  const [addSearchTerm, setAddSearchTerm] = useState("");
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout>>();
  const [showTree, setShowTree] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const showToast = useCallback((message: string, type: "success" | "error" = "success") => {
    setToast({ message, type });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  }, []);

  // ── Load config sources ──

  const loadSources = useCallback(async () => {
    try {
      const data = await apiRef.current.listIndexSources();
      setConfigSources(data.sources || []);
    } catch {
      // ignore
    }
  }, []);

  // ── Load data for current source ──

  const loadData = useCallback(async (sourceId?: string) => {
    const srcId = sourceId || activeSourceIdRef.current;
    setLoading(true);
    setError("");
    setSelectedDoc(null);
    setScanResults(null);
    try {
      let configData: any;
      let treeData: any;
      if (srcId === "global") {
        [treeData, configData] = await Promise.all([
          apiRef.current.getFullIndexTree(),
          apiRef.current.getIndexConfig(),
        ]);
      } else {
        configData = await apiRef.current.getSessionIndexConfig(srcId);
        treeData = await apiRef.current.buildIndexTree(configData.config || {});
      }
      setConfig(configData.config || {});
      setEntities(configData.entities || {});
      setTree(treeData);
      const cats = (treeData.categories || []).map((c: any) => c.category);
      setExpandedCats(new Set(cats));
    } catch (err: any) {
      setError("加载索引配置失败: " + err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadSources();
    loadData("global");
  }, [loadSources, loadData]);

  // ── Source switching ──

  const switchSource = (sourceId: string) => {
    if (sourceId === activeSourceId) return;
    setActiveSourceId(sourceId);
    setActiveSessionId(sourceId === "global" ? null : sourceId);
    loadData(sourceId);
  };

  // ── Tree collapse ──

  const toggleCat = (cat: string) => {
    setExpandedCats((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const toggleDoc = (path: string) => {
    setExpandedDocs((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  // ── Ref mutations (local, optimistic tree update) ──

  const handleAddRef = (docPath: string, refCat: string, entityId: string) => {
    // Update config
    setConfig((prev) => {
      const next = { ...prev };
      const refs = { ...(next[docPath] || {}) };
      const list = [...(refs[refCat] || [])];
      if (!list.includes(entityId)) {
        list.push(entityId);
        refs[refCat] = list;
        next[docPath] = refs;
      }
      return next;
    });
    // Optimistic tree update
    setTree((prev) => {
      if (!prev) return prev;
      return patchTreeDoc(prev, docPath, (doc) => {
        if (!doc.refs[refCat]) doc.refs[refCat] = [];
        if (!doc.refs[refCat].includes(entityId)) {
          doc.refs[refCat].push(entityId);
          doc.ref_count = (doc.ref_count || 0) + 1;
        }
      });
    });
  };

  const handleRemoveRef = (docPath: string, refCat: string, entityId: string) => {
    // Update config
    setConfig((prev) => {
      const next = { ...prev };
      const refs = { ...(next[docPath] || {}) };
      const list = (refs[refCat] || []).filter((id: string) => id !== entityId);
      if (list.length > 0) {
        refs[refCat] = list;
        next[docPath] = refs;
      } else {
        delete refs[refCat];
        if (Object.keys(refs).length > 0) {
          next[docPath] = refs;
        } else {
          delete next[docPath];
        }
      }
      return next;
    });
    // Optimistic tree update
    setTree((prev) => {
      if (!prev) return prev;
      return patchTreeDoc(prev, docPath, (doc) => {
        if (doc.refs[refCat]) {
          doc.refs[refCat] = doc.refs[refCat].filter((id: string) => id !== entityId);
          doc.ref_count = Math.max(0, (doc.ref_count || 0) - 1);
          if (doc.refs[refCat].length === 0) delete doc.refs[refCat];
        }
      });
    });
  };

  const handleAddAll = (docPath: string, refCat: string) => {
    const allEntities = entities[refCat] || [];
    const current = config[docPath]?.[refCat] || [];
    allEntities.forEach((e: any) => {
      if (!current.includes(e.id)) {
        handleAddRef(docPath, refCat, e.id);
      }
    });
  };

  // ── Doc management (add/remove from config) ──

  const handleAddDoc = async (docPath: string) => {
    try {
      await apiRef.current.addDocToConfig(docPath);
      setConfig((prev) => ({ ...prev, [docPath]: {} }));
      showToast(`已添加 ${docPath.split("/").pop()} 到索引配置`);
      // Reload full tree
      const treeData = await apiRef.current.getFullIndexTree();
      setTree(treeData);
    } catch (err: any) {
      setError("添加文档失败: " + err.message);
    }
  };

  const handleRemoveDoc = async (docPath: string) => {
    try {
      await apiRef.current.removeDocFromConfig(docPath);
      setConfig((prev) => {
        const next = { ...prev };
        delete next[docPath];
        return next;
      });
      showToast(`已从索引配置移除`);
      // Reload full tree
      const treeData = await apiRef.current.getFullIndexTree();
      setTree(treeData);
      setSelectedDoc(null);
    } catch (err: any) {
      setError("移除文档失败: " + err.message);
    }
  };

  // ── Scan all ──

  const handleScanAll = async () => {
    if (activeSourceId !== "global") {
      showToast("只有全局配置支持扫描", "error");
      return;
    }
    setScanning(true);
    setScanResults(null);
    try {
      const result = await apiRef.current.scanAllIndex();
      setScanResults(result.results || {});
      showToast("扫描完成");
    } catch (err: any) {
      setError("扫描失败: " + err.message);
    } finally {
      setScanning(false);
    }
  };

  // ── Export ──

  const handleExport = async () => {
    try {
      const { yaml } = await apiRef.current.exportIndexConfig();
      const blob = new Blob([yaml], { type: "text/yaml" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "_index_config.yaml";
      a.click();
      URL.revokeObjectURL(url);
      showToast("配置已导出");
    } catch (err: any) {
      setError("导出失败: " + err.message);
    }
  };

  // ── Import ──

  const handleImportClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      await apiRef.current.importIndexConfig(text);
      showToast("配置已导入");
      switchSource("global");
    } catch (err: any) {
      setError("导入失败: " + err.message);
    }
    e.target.value = "";
  };

  // ── Save ──

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      if (activeSourceId === "global") {
        await apiRef.current.updateIndexConfig(config);
      } else {
        await apiRef.current.saveSessionIndexConfig(activeSourceId, config);
      }
      const treeData = activeSourceId === "global"
        ? await apiRef.current.getFullIndexTree()
        : await apiRef.current.buildIndexTree(config);
      setTree(treeData);
      loadSources();
      showToast("索引配置已保存");
    } catch (err: any) {
      setError("保存失败: " + err.message);
    } finally {
      setSaving(false);
    }
  };

  // ── Derived ──

  const displayedCats = useMemo(
    () =>
      tree?.categories?.filter(
        (c) => catFilter.length === 0 || catFilter.includes(c.category)
      ) || [],
    [tree, catFilter]
  );

  const allRefCats = useMemo(
    () => Object.keys(entities).filter((c) => entities[c]?.length > 0),
    [entities]
  );

  const getAddableEntities = useCallback(
    (docPath: string, refCat: string) => {
      const all = entities[refCat] || [];
      const current = config[docPath]?.[refCat] || [];
      return all.filter(
        (e: any) =>
          !current.includes(e.id) &&
          (addSearchTerm === "" ||
            e.name.includes(addSearchTerm) ||
            e.id.includes(addSearchTerm))
      );
    },
    [entities, config, addSearchTerm]
  );

  // ── Render helpers ──

  const renderTreeDoc = (doc: IndexConfigTreeDoc & { in_config?: boolean }, depth: number) => {
    const isExpanded = expandedDocs.has(doc.path);
    const isSelected = selectedDoc === doc.path;
    const hasRefs = doc.ref_count > 0;
    const hasRefedBy = doc.refed_by_count > 0;
    const isConfigured = doc.in_config !== false;

    return (
      <div key={doc.path}>
        <div
          className={`flex items-center gap-1 cursor-pointer rounded text-xs py-0.5 select-none ${
            isSelected
              ? "text-blue-300 bg-blue-900/20"
              : isConfigured
                ? "text-gray-300 hover:text-gray-100"
                : "text-gray-600 hover:text-gray-400"
          }`}
          style={{ paddingLeft: depth * 16 + 4 }}
          onClick={() => isConfigured && setSelectedDoc(doc.path)}
        >
          {(hasRefs || hasRefedBy) ? (
            <span className="w-3 text-center shrink-0 text-gray-500">
              {isExpanded ? "▼" : "▶"}
            </span>
          ) : (
            <span className="w-3 shrink-0" />
          )}
          <span className="truncate">{doc.id}</span>
          {isConfigured ? (
            <span className="text-gray-600 shrink-0">
              [{doc.ref_count > 0 ? `→${doc.ref_count}` : ""}
              {doc.refed_by_count > 0 ? ` | ←${doc.refed_by_count}` : ""}]
            </span>
          ) : (
            <button
              onClick={(e) => { e.stopPropagation(); handleAddDoc(doc.path); }}
              className="ml-auto text-green-500 hover:text-green-400 text-[11px] px-1 shrink-0"
              title="添加到索引配置"
            >
              +添加
            </button>
          )}
        </div>
        {isExpanded && isConfigured && (
          <div>
            {Object.keys(doc.refs).length > 0 && (
              <div className="text-[11px] text-gray-500" style={{ paddingLeft: depth * 16 + 20 }}>
                引用
              </div>
            )}
            {Object.entries(doc.refs).map(([refCat, ids]) => (
              <div
                key={`ref-${refCat}`}
                className="text-[11px] text-gray-600 truncate"
                style={{ paddingLeft: depth * 16 + 32 }}
              >
                {catLabel(refCat)} ({ids.length})
              </div>
            ))}
            {Object.keys(doc.refed_by).length > 0 && (
              <div className="text-[11px] text-gray-500" style={{ paddingLeft: depth * 16 + 20 }}>
                被引用
              </div>
            )}
            {Object.entries(doc.refed_by).map(([refCat, refDocs]) => (
              <div
                key={`refed-${refCat}`}
                className="text-[11px] text-gray-600 truncate"
                style={{ paddingLeft: depth * 16 + 32 }}
              >
                {catLabel(refCat)} ({refDocs.length})
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  const renderTree = () => {
    if (loading) {
      return <p className="text-gray-500 text-sm text-center py-4">加载中...</p>;
    }
    if (displayedCats.length === 0) {
      return (
        <p className="text-gray-500 text-sm text-center py-4">
          {tree?.categories?.length === 0 ? "暂无索引数据" : "当前类别无数据"}
        </p>
      );
    }
    return displayedCats.map((cat: any) => {
      const isExpanded = expandedCats.has(cat.category);
      return (
        <div key={cat.category} className="mb-1">
          <div
            className="flex items-center gap-1 cursor-pointer rounded text-xs font-semibold text-gray-500 uppercase tracking-wider py-1 hover:text-gray-300 select-none"
            onClick={() => toggleCat(cat.category)}
          >
            <span className="w-3 text-center shrink-0">
              {isExpanded ? "▼" : "▶"}
            </span>
            <span className="truncate">{catLabel(cat.category)}</span>
            <span className="text-gray-600 ml-1">
              ({cat.configured_count ?? cat.doc_count}/{cat.doc_count})
            </span>
          </div>
          {isExpanded && (
            <div>
              {cat.docs.length === 0 ? (
                <p className="text-xs text-gray-600 italic" style={{ paddingLeft: 20 }}>
                  (空)
                </p>
              ) : (
                cat.docs.map((doc: any) => renderTreeDoc(doc, 1))
              )}
            </div>
          )}
        </div>
      );
    });
  };

  // ── Detail panel (center) ──

  const renderDetail = () => {
    if (!selectedDoc) {
      return (
        <div className="p-4 overflow-y-auto h-full">
          <h3 className="text-xs font-medium text-gray-400 mb-3">所有类别</h3>
          <div className="grid grid-cols-2 gap-3">
            {allRefCats.map((refCat) => {
              const catEntities = entities[refCat] || [];
              return (
                <div
                  key={refCat}
                  className="p-3 rounded bg-gray-800/40 border border-gray-700/50 transition-colors"
                >
                  <div className="text-xs font-medium text-gray-300 mb-1">
                    {catLabel(refCat)}
                  </div>
                  <div className="text-[10px] text-gray-500 mb-2">
                    {catEntities.length} 项
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {catEntities.slice(0, 8).map((e: any) => (
                      <span
                        key={e.id}
                        className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700/30 text-gray-400 truncate max-w-[100px]"
                        title={e.name}
                      >
                        {e.name}
                      </span>
                    ))}
                    {catEntities.length > 8 && (
                      <span className="text-[10px] text-gray-600">+{catEntities.length - 8}</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      );
    }

    const docRefs = config[selectedDoc] || {};
    const docId = selectedDoc.split("/").pop() || selectedDoc;
    const isInConfig = selectedDoc in config;

    return (
      <div className="p-4 overflow-y-auto h-full">
        {/* Doc header */}
        <div className="mb-4 flex items-start justify-between shrink-0">
          <div>
            <h2 className="text-sm font-medium text-blue-300">{docId}</h2>
            <p className="text-xs text-gray-500">{selectedDoc}</p>
          </div>
          {isInConfig && (
            <button
              onClick={() => handleRemoveDoc(selectedDoc)}
              className="text-[11px] text-red-400 hover:text-red-300 px-2 py-0.5 rounded bg-red-900/20 border border-red-800/30"
            >
              从配置移除
            </button>
          )}
        </div>

        {!isInConfig && (
          <div className="mb-4 p-3 bg-gray-800/50 border border-gray-700 rounded">
            <p className="text-xs text-gray-400 mb-2">此文档不在索引配置中</p>
            <button
              onClick={() => handleAddDoc(selectedDoc)}
              className="text-xs text-green-400 hover:text-green-300 px-3 py-1 rounded bg-green-900/20 border border-green-800/30"
            >
              + 添加到索引配置
            </button>
          </div>
        )}

        {isInConfig && (
          <>
            {/* Summary bar */}
            <div className="mb-4 flex items-center gap-3 text-xs text-gray-500 shrink-0">
              <span>已引用: {Object.values(docRefs).reduce((s, a) => s + a.length, 0)} 项</span>
              {(() => {
                const refedBy = tree?.categories
                  .flatMap((c: any) => c.docs)
                  .find((d: any) => d.path === selectedDoc)?.refed_by;
                const count = refedBy ? Object.values(refedBy).reduce((s: number, a: any) => s + a.length, 0) : 0;
                return count > 0 ? <span>被引用: {count} 处</span> : null;
              })()}
            </div>

            {/* Current refs grouped by category */}
            <div className="space-y-4">
              {allRefCats.map((refCat) => {
                const currentIds = docRefs[refCat] || [];
                return (
                  <div key={refCat}>
                    <div className="flex items-center justify-between mb-1.5">
                      <h4 className="text-xs font-medium text-gray-400">
                        {catLabel(refCat)}
                        <span className="text-gray-600 ml-1">({currentIds.length})</span>
                      </h4>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {currentIds.length === 0 ? (
                        <span className="text-xs text-gray-600 italic">未引用</span>
                      ) : (
                        currentIds.map((id: string) => {
                          const entity = (entities[refCat] || []).find(
                            (e: any) => e.id === id
                          );
                          return (
                            <span
                              key={`${refCat}-${id}`}
                              className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-gray-700/50 text-gray-300 border border-gray-600"
                            >
                              <span className="truncate max-w-[140px]" title={entity?.name || id}>
                                {entity?.name || id}
                              </span>
                              <button
                                onClick={() => handleRemoveRef(selectedDoc, refCat, id)}
                                className="text-gray-500 hover:text-red-400 transition-colors shrink-0"
                                title="移除引用"
                              >
                                ✕
                              </button>
                            </span>
                          );
                        })
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Refed-by (read-only) */}
            {tree && (() => {
              const cat = tree.categories.find((c: any) =>
                c.docs.some((d: any) => d.path === selectedDoc)
              );
              const doc = cat?.docs.find((d: any) => d.path === selectedDoc);
              const refedBy = doc?.refed_by;
              if (!refedBy || Object.keys(refedBy).length === 0) return null;
              return (
                <div className="mt-6 pt-4 border-t border-gray-700">
                  <h3 className="text-xs font-medium text-gray-400 mb-2">
                    被引用
                    <span className="text-gray-600 ml-1">
                      ({Object.values(refedBy).reduce((s: number, a: any) => s + a.length, 0)})
                    </span>
                  </h3>
                  {Object.entries(refedBy).map(([refCat, refDocs]: [string, any]) => (
                    <div key={refCat} className="mb-2">
                      <span className="text-xs text-gray-500">{catLabel(refCat)}</span>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {refDocs.map((r: any) => (
                          <span
                            key={`${refCat}-${r.id}`}
                            className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-amber-900/20 text-amber-300 border border-amber-800/30"
                          >
                            {r.id}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              );
            })()}
          </>
        )}
      </div>
    );
  };

  // ── Add panel (right) ──

  const renderAddPanel = () => {
    if (!selectedDoc) return null;
    const docRefs = config[selectedDoc] || {};
    const isInConfig = selectedDoc in config;
    if (!isInConfig) return null;

    return (
      <div className="p-3 overflow-y-auto h-full">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-medium text-gray-400">选择添加</span>
          {(addSearchTerm || showAddDropdown) && (
            <button
              onClick={() => { setAddSearchTerm(""); setShowAddDropdown(null); }}
              className="text-[10px] text-gray-500 hover:text-gray-300"
            >
              清除
            </button>
          )}
        </div>
        <input
          className="w-full px-2 py-1 text-xs bg-gray-700 border border-gray-600 rounded outline-none text-gray-200 mb-3"
          placeholder="搜索实体..."
          value={addSearchTerm}
          onChange={(e) => setAddSearchTerm(e.target.value)}
        />
        <div className="space-y-3">
          {allRefCats.map((refCat) => {
            const catEntities = entities[refCat] || [];
            const currentIds = docRefs[refCat] || [];
            const filtered = catEntities.filter(
              (e: any) =>
                !currentIds.includes(e.id) &&
                (addSearchTerm === "" ||
                  e.name.toLowerCase().includes(addSearchTerm.toLowerCase()) ||
                  e.id.toLowerCase().includes(addSearchTerm.toLowerCase()))
            );
            if (filtered.length === 0) return null;

            return (
              <div key={refCat}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-gray-500">{catLabel(refCat)} ({filtered.length})</span>
                  <button
                    onClick={() => handleAddAll(selectedDoc, refCat)}
                    className="text-[10px] text-green-400 hover:text-green-300"
                    title="添加全部"
                  >
                    全部
                  </button>
                </div>
                <div className="flex flex-wrap gap-1">
                  {filtered.slice(0, 30).map((e: any) => (
                    <button
                      key={e.id}
                      onClick={() => handleAddRef(selectedDoc, refCat, e.id)}
                      className="text-xs px-1.5 py-0.5 rounded bg-gray-800/50 text-gray-400 border border-gray-700/50 hover:border-green-700/50 hover:text-green-400 transition-colors truncate max-w-[150px]"
                      title={e.summary ? `${e.name} — ${e.summary}` : e.name}
                    >
                      + {e.name}
                    </button>
                  ))}
                  {filtered.length > 30 && (
                    <span className="text-[10px] text-gray-600">+{filtered.length - 30}</span>
                  )}
                </div>
              </div>
            );
          })}
          {allRefCats.every((refCat) => {
            const currentIds = docRefs[refCat] || [];
            const catEntities = entities[refCat] || [];
            return catEntities.every((e: any) => currentIds.includes(e.id));
          }) && (
            <p className="text-xs text-gray-600 italic text-center pt-4">
              {addSearchTerm ? "无匹配结果" : "所有实体已添加"}
            </p>
          )}
        </div>
      </div>
    );
  };

  // ── Tree view (full screen) ──

  const renderTreeView = () => {
    if (!tree) {
      return <p className="text-gray-500 text-sm text-center py-4">加载中...</p>;
    }

    return (
      <div className="p-6 overflow-y-auto h-full">
        {displayedCats.length === 0 ? (
          <p className="text-gray-500 text-sm text-center py-8">
            {tree.categories.length === 0 ? "暂无索引数据" : "当前类别无数据"}
          </p>
        ) : (
          <div className="max-w-4xl mx-auto space-y-6">
            {displayedCats.map((cat: any) => (
              <div key={cat.category}>
                <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
                  {catLabel(cat.category)}
                  <span className="text-xs text-gray-600 font-normal">
                    {cat.configured_count ?? cat.doc_count}/{cat.doc_count} 个文档
                  </span>
                </h2>
                <div className="space-y-2 ml-2">
                  {cat.docs.length === 0 ? (
                    <p className="text-xs text-gray-600 italic ml-2">(空)</p>
                  ) : (
                    cat.docs.map((doc: any) => (
                      <div
                        key={doc.path}
                        className={`p-3 rounded border ${
                          doc.in_config !== false
                            ? "bg-gray-800/40 border-gray-700/60"
                            : "bg-gray-800/20 border-gray-700/30 opacity-60"
                        }`}
                      >
                        <div className="flex items-center gap-2 mb-2">
                          <span className={`text-sm font-medium ${doc.in_config !== false ? "text-blue-300" : "text-gray-500"}`}>
                            {doc.id}
                          </span>
                          <span className="text-[10px] text-gray-600">{doc.path}</span>
                          <div className="flex gap-2 ml-auto text-[10px] text-gray-500">
                            {doc.ref_count > 0 && <span>→{doc.ref_count}</span>}
                            {doc.refed_by_count > 0 && <span>←{doc.refed_by_count}</span>}
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
                          {Object.keys(doc.refs).length > 0 && (
                            <div>
                              <span className="text-gray-500 mr-1">引用:</span>
                              {Object.entries(doc.refs).map(([refCat, ids]: [string, any]) => (
                                <span key={refCat} className="text-gray-400 mr-3">
                                  {catLabel(refCat)}({ids.length})
                                </span>
                              ))}
                            </div>
                          )}
                          {Object.keys(doc.refed_by).length > 0 && (
                            <div>
                              <span className="text-gray-500 mr-1">被引用:</span>
                              {Object.entries(doc.refed_by).map(([refCat, refDocs]: [string, any]) => (
                                <span key={refCat} className="text-amber-400/70 mr-3">
                                  {catLabel(refCat)}({refDocs.length})
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                        {doc.in_config === false && (
                          <button
                            onClick={() => { setSelectedDoc(doc.path); setShowTree(false); }}
                            className="mt-2 text-[10px] text-green-500 hover:text-green-400"
                          >
                            + 添加到索引配置
                          </button>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  // ── Main render ──

  return (
    <div className="flex flex-col h-full">
      {/* Top bar */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-700 shrink-0 flex-wrap">
        {tree && (tree as any).categories?.length > 0 && (
          <div className="flex items-center gap-1 flex-wrap">
            <button
              onClick={() => setCatFilter([])}
              className={`text-xs px-2 py-0.5 rounded transition-colors ${
                catFilter.length === 0
                  ? "bg-blue-600/30 text-blue-300"
                  : "text-gray-500 hover:text-gray-300 bg-gray-800/50"
              }`}
            >
              全部
            </button>
            {(tree as any).categories.map((cat: any) => (
              <button
                key={cat.category}
                onClick={() =>
                  setCatFilter((prev) =>
                    prev.includes(cat.category)
                      ? prev.filter((c) => c !== cat.category)
                      : [...prev, cat.category]
                  )
                }
                className={`text-xs px-2 py-0.5 rounded transition-colors ${
                  catFilter.length === 0 || catFilter.includes(cat.category)
                    ? "bg-gray-700/50 text-gray-300"
                    : "text-gray-600 hover:text-gray-400 bg-gray-800/30"
                }`}
              >
                {catLabel(cat.category)}
              </button>
            ))}
          </div>
        )}
        <div className="flex-1" />
        <input
          ref={fileInputRef}
          type="file"
          accept=".yaml,.yml"
          className="hidden"
          onChange={handleFileSelected}
        />
        <button
          onClick={handleImportClick}
          className="text-xs text-gray-400 hover:text-gray-200 px-2 py-1 rounded bg-gray-800/50 border border-gray-700 hover:border-gray-600 transition-colors"
          title="导入 YAML 配置"
        >
          📥 导入
        </button>
        <button
          onClick={handleExport}
          className="text-xs text-gray-400 hover:text-gray-200 px-2 py-1 rounded bg-gray-800/50 border border-gray-700 hover:border-gray-600 transition-colors"
          title="导出为 YAML"
        >
          📤 导出
        </button>
        <button
          onClick={handleScanAll}
          disabled={scanning}
          className="btn-ghost text-xs px-3 py-1"
        >
          {scanning ? "扫描中..." : "🔍 扫描全部"}
        </button>
        <button
          onClick={handleSave}
          disabled={saving}
          className="btn-primary text-xs px-3 py-1"
        >
          {saving ? "保存中..." : "💾 保存配置"}
        </button>
        <button
          onClick={() => loadData()}
          className="text-xs text-gray-500 hover:text-gray-300 px-1"
          title="刷新"
        >
          ↻
        </button>
        <button
          onClick={() => setShowTree((v) => !v)}
          className={`text-xs px-2 py-1 rounded transition-colors ${
            showTree
              ? "bg-blue-600/30 text-blue-300 border border-blue-700/40"
              : "text-gray-500 hover:text-gray-300"
          }`}
          title={showTree ? "切换到配置视图" : "切换到引用树"}
        >
          {showTree ? "⚙️" : "🌳"}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="mx-4 mt-2 p-2 bg-red-900/30 border border-red-700/30 rounded text-xs text-red-400">
          {error}
        </div>
      )}

      {/* Scan results */}
      {scanResults && (
        <div className="mx-4 mt-2 p-3 bg-blue-900/20 border border-blue-700/30 rounded max-h-40 overflow-y-auto shrink-0">
          <p className="text-xs text-blue-300 font-medium mb-1">扫描结果：</p>
          {Object.keys(scanResults).length === 0 ? (
            <p className="text-xs text-gray-500">未发现新的实体匹配</p>
          ) : (
            Object.entries(scanResults).map(([docPath, result]: any) => {
              const newCount = Object.values(result.new_matches || {}).reduce(
                (s: number, a: any) => s + a.length, 0
              );
              return (
                <div key={docPath} className="text-xs text-gray-400 mb-1">
                  <span className="text-gray-500">{docPath}:</span>{" "}
                  {newCount > 0 ? (
                    <span className="text-green-400">{newCount} 个新匹配</span>
                  ) : (
                    <span className="text-gray-600">无新匹配</span>
                  )}
                  <button
                    className="ml-2 text-blue-400 hover:text-blue-300"
                    onClick={() => setSelectedDoc(docPath)}
                  >
                    [查看]
                  </button>
                </div>
              );
            })
          )}
        </div>
      )}

      {showTree ? renderTreeView() : (
      // Main layout: sidebar + detail + add panel
      <div className="flex flex-1 min-h-0">
        <div className="w-72 border-r border-gray-700 shrink-0 flex flex-col">
          {/* Config files section */}
          {configSources.length > 0 && (
            <div className="border-b border-gray-700 shrink-0">
              <div className="p-3 pb-2">
                <div className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5 flex items-center justify-between">
                  <span>配置文件</span>
                  <span className="text-gray-600 font-normal normal-case text-[10px]">{configSources.length} 项</span>
                </div>
                <div className="space-y-0.5">
                  {configSources.map((src) => {
                    const isActive = activeSourceId === src.id;
                    const isSession = src.type === "session";
                    return (
                      <div key={src.id}>
                        <button
                          onClick={() => switchSource(src.id)}
                          className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors ${
                            isActive
                              ? isSession
                                ? "bg-amber-600/20 text-amber-300 border border-amber-700/30"
                                : "bg-blue-600/20 text-blue-300 border border-blue-700/30"
                              : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/40 border border-transparent"
                          }`}
                          title={isSession ? `会话: ${src.name}` : "全局索引配置"}
                        >
                          <span className="shrink-0">{isSession ? "📝" : "🌐"}</span>
                          <span className="truncate flex-1 text-left">
                            {isSession ? (src.name.length > 22 ? src.name.slice(0, 20) + "…" : src.name) : "全局索引"}
                          </span>
                          <span className="text-gray-500 shrink-0 text-[10px]">{src.doc_count}</span>
                        </button>
                        {isActive && isSession && (
                          <div className="pl-8 pr-2 py-1 text-[10px] text-amber-400/50 leading-tight">
                            会话配置 · 保存不影响全局
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
          {/* Tree section */}
          <div className="flex-1 overflow-y-auto p-3">
            {renderTree()}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {renderDetail()}
        </div>
        {selectedDoc && (selectedDoc in config) && (
          <div className="w-72 border-l border-gray-700 overflow-y-auto shrink-0">
            {renderAddPanel()}
          </div>
        )}
      </div>
      )}

      {/* Dropdown overlay */}
      {showAddDropdown && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => { setShowAddDropdown(null); setAddSearchTerm(""); }}
        />
      )}

      {/* Toast */}
      {toast && (
        <div
          className={`fixed bottom-4 right-4 z-50 px-4 py-2 rounded-lg shadow-lg text-sm transition-all ${
            toast.type === "error"
              ? "bg-red-600 text-white"
              : "bg-green-700 text-white"
          }`}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}
