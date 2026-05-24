import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useApi } from "../hooks/useApi";
import { useAppStore } from "../stores/appStore";
import type { IndexOverview, IndexDocSummary, SessionIndexConfig, IndexVerifyResult } from "../types";

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

export default function IndexManager() {
  const api = useApi();
  const sessions = useAppStore((s) => s.sessions);
  const indexSessionId = useAppStore((s) => s.indexSessionId);
  const setIndexSessionId = useAppStore((s) => s.setIndexSessionId);

  // ── Data state ──
  const [overview, setOverview] = useState<IndexOverview | null>(null);
  const [entities, setEntities] = useState<Record<string, { id: string; name: string; summary: string }[]>>({});
  const [error, setError] = useState<string | null>(null);

  // ── Config source state ──
  const [activeSource, setActiveSource] = useState<string>("global");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  // ── Session config state (for session config source) ──
  const [sessionConfig, setSessionConfig] = useState<SessionIndexConfig | null>(null);
  const [sessionConfigLoading, setSessionConfigLoading] = useState(false);
  const [sessionConfigSaving, setSessionConfigSaving] = useState(false);
  const [sessionRightMode, setSessionRightMode] = useState<"deps" | "list">("deps");
  const [expandedImports, setExpandedImports] = useState<Set<string>>(new Set());
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null);
  const [docImports, setDocImports] = useState<{ path: string; name: string }[]>([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [toast, setToast] = useState<{ text: string; type: "ok" | "error" } | null>(null);
  const [savingImport, setSavingImport] = useState<string | null>(null);

  // ── Verify state ──
  const [verifyResult, setVerifyResult] = useState<IndexVerifyResult | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [fixingVerify, setFixingVerify] = useState<string | null>(null);

  const toastTimer = useRef<ReturnType<typeof setTimeout>>();

  const showToast = useCallback((text: string, type: "ok" | "error" = "ok") => {
    setToast({ text, type });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  }, []);

  // ── Load initial data ──
  const loadData = useCallback(async () => {
    setError(null);
    try {
      const [ov, ents] = await Promise.all([
        api.getIndexOverview(),
        api.getEntities(),
      ]);
      setOverview(ov);
      setEntities(ents as Record<string, { id: string; name: string; summary: string }[]>);
    } catch (err: any) {
      setError(err.message);
    }
  }, [api]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // ── Auto-switch to session from chat settings button ──
  useEffect(() => {
    if (indexSessionId && overview) {
      switchSource(indexSessionId);
      setIndexSessionId(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [indexSessionId, overview]);

  // ── Load imports when doc changes ──
  useEffect(() => {
    if (!selectedDoc || activeSource !== "global") {
      setDocImports([]);
      return;
    }
    const parts = selectedDoc.split("/");
    const cat = parts[0];
    const docId = parts.slice(1).join("/");
    api.getDocImports(cat, docId).then((res) => {
      setDocImports(res.imports || []);
    }).catch(() => {
      setDocImports([]);
    });
  }, [selectedDoc, activeSource, api]);

  // ── Import mutations ──

  const addImport = async (entityCat: string, entityId: string) => {
    if (!selectedDoc) return;
    const parts = selectedDoc.split("/");
    const cat = parts[0];
    const docId = parts.slice(1).join("/");

    const newPath = `${entityCat}/${entityId}`;
    if (docImports.some((i) => i.path === newPath)) return;

    const entity = entities[entityCat]?.find((e) => e.id === entityId);
    const name = entity?.name || entityId;
    const newImport = `${newPath} | ${name}`;

    const newList = [...docImports.map((i) => `${i.path} | ${i.name}`), newImport];
    setSavingImport(newPath);
    try {
      await api.updateDocImports(cat, docId, newList);
      setDocImports((prev) => [...prev, { path: newPath, name }]);
      showToast(`已添加引用: ${name}`);
    } catch (err: any) {
      showToast("添加失败: " + err.message, "error");
    } finally {
      setSavingImport(null);
    }
  };

  const removeImport = async (importPath: string) => {
    if (!selectedDoc) return;
    const parts = selectedDoc.split("/");
    const cat = parts[0];
    const docId = parts.slice(1).join("/");

    const newList = docImports
      .filter((i) => i.path !== importPath)
      .map((i) => `${i.path} | ${i.name}`);

    setSavingImport(importPath);
    try {
      await api.updateDocImports(cat, docId, newList);
      setDocImports((prev) => prev.filter((i) => i.path !== importPath));
      showToast("已移除引用");
    } catch (err: any) {
      showToast("移除失败: " + err.message, "error");
    } finally {
      setSavingImport(null);
    }
  };

  // ── Source switching ──

  const switchSource = async (sourceId: string) => {
    if (sourceId === activeSource) return;
    setActiveSource(sourceId);
    setActiveSessionId(sourceId === "global" ? null : sourceId);
    setSelectedDoc(null);
    setDocImports([]);

    // 同步清空会话配置，避免用旧会话的数据渲染
    setSessionConfig(null);
    if (sourceId === "global") return;
    setSessionConfigLoading(true);
    try {
      const cfg = await api.getSessionIndexConfig(sourceId);
      setSessionConfig(cfg);
    } catch {
      setSessionConfig(null);
    } finally {
      setSessionConfigLoading(false);
    }
  };

  // ── Session config toggles ──

  const toggleSessionCategory = (cat: string) => {
    setSessionConfig((prev) => {
      if (!prev) return prev;
      const cats = prev.enabled_categories.includes(cat)
        ? prev.enabled_categories.filter((c) => c !== cat)
        : [...prev.enabled_categories, cat];
      return { ...prev, enabled_categories: cats };
    });
  };

  const toggleSessionEntity = (cat: string, entityId: string) => {
    setSessionConfig((prev) => {
      if (!prev) return prev;
      const ents = { ...prev.enabled_entities };
      const list = ents[cat] || [];
      ents[cat] = list.includes(entityId)
        ? list.filter((id) => id !== entityId)
        : [...list, entityId];
      return { ...prev, enabled_entities: ents };
    });
  };

  const selectAllInCategory = (cat: string) => {
    setSessionConfig((prev) => {
      if (!prev) return prev;
      const ids = (entities[cat] || []).map((e) => e.id);
      return { ...prev, enabled_entities: { ...prev.enabled_entities, [cat]: ids } };
    });
  };

  const deselectAllInCategory = (cat: string) => {
    setSessionConfig((prev) => {
      if (!prev) return prev;
      const ents = { ...prev.enabled_entities };
      delete ents[cat];
      return { ...prev, enabled_entities: ents };
    });
  };

  const handleSaveSessionConfig = async () => {
    if (!activeSessionId || !sessionConfig) return;
    setSessionConfigSaving(true);
    try {
      await api.saveSessionIndexConfig(activeSessionId, sessionConfig);
      showToast("会话配置已保存");
    } catch (err: any) {
      showToast("保存失败: " + err.message, "error");
    } finally {
      setSessionConfigSaving(false);
    }
  };

  const handleResetSessionConfig = async () => {
    if (!activeSessionId) return;
    setSessionConfigSaving(true);
    try {
      await api.resetSessionIndexConfig(activeSessionId);
      setSessionConfig({ mode: "all", enabled_categories: [], enabled_entities: {} });
      showToast("已重置为默认配置");
    } catch (err: any) {
      showToast("重置失败: " + err.message, "error");
    } finally {
      setSessionConfigSaving(false);
    }
  };

  // ── Export / Import ──

  const handleExport = async () => {
    try {
      const { yaml } = await api.exportIndexYaml();
      const blob = new Blob([yaml], { type: "text/yaml" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "_index_imports.yaml";
      a.click();
      URL.revokeObjectURL(url);
      showToast("配置已导出");
    } catch (err: any) {
      showToast("导出失败: " + err.message, "error");
    }
  };

  const fileInputRef = useRef<HTMLInputElement>(null);
  const handleImportClick = () => fileInputRef.current?.click();
  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      await api.importIndexYaml(text);
      showToast("配置已导入");
      loadData();
    } catch (err: any) {
      showToast("导入失败: " + err.message, "error");
    }
    e.target.value = "";
  };

  // ── Verify ──

  const handleVerify = async () => {
    setVerifying(true);
    setVerifyResult(null);
    try {
      const result = activeSource !== "global" && activeSessionId
        ? await api.verifySessionIndex(activeSessionId)
        : await api.verifyIndex();
      setVerifyResult(result);
      if (result.broken_refs.length === 0) {
        showToast("所有依赖引用完整，无断裂引用");
      }
    } catch (err: any) {
      showToast("验证失败: " + err.message, "error");
    } finally {
      setVerifying(false);
    }
  };

  const handleRemoveBrokenImport = async (docPath: string, importPath: string) => {
    const parts = docPath.split("/");
    const cat = parts[0];
    const docId = parts.slice(1).join("/");
    const key = `${docPath}::${importPath}`;
    setFixingVerify(key);
    try {
      // Fetch current imports, filter out the broken one
      const { imports } = await api.getDocImports(cat, docId);
      const filtered = imports
        .filter((i: { path: string }) => i.path !== importPath)
        .map((i: { path: string; name: string }) => `${i.path} | ${i.name}`);
      await api.updateDocImports(cat, docId, filtered);
      // Update local verify result
      setVerifyResult((prev) => {
        if (!prev) return prev;
        const updatedRefs = prev.broken_refs
          .map((ref) => {
            if (ref.doc_path !== docPath) return ref;
            const remaining = ref.broken_imports.filter((bi) => bi.import_path !== importPath);
            return remaining.length === 0 ? null : { ...ref, broken_imports: remaining };
          })
          .filter(Boolean) as typeof prev.broken_refs;
        return { ...prev, broken_refs: updatedRefs };
      });
      showToast("已移除断裂引用");
    } catch (err: any) {
      showToast("移除失败: " + err.message, "error");
    } finally {
      setFixingVerify(null);
    }
  };

  const handleAddToWhitelist = async (depPath: string, depName: string) => {
    if (!activeSessionId) return;
    const parts = depPath.split("/");
    const cat = parts[0];
    const id = parts.slice(1).join("/");
    setFixingVerify(depPath);
    try {
      const cfg = sessionConfig;
      if (!cfg) return;
      const newEnts = { ...cfg.enabled_entities };
      const list = newEnts[cat] || [];
      if (!list.includes(id)) {
        newEnts[cat] = [...list, id];
      }
      const newConfig = { ...cfg, enabled_entities: newEnts };
      // Update local state and save with same data
      setSessionConfig(newConfig);
      await api.saveSessionIndexConfig(activeSessionId, newConfig);
      // Update verify result
      setVerifyResult((prev) => {
        if (!prev) return prev;
        const updatedRefs = prev.broken_refs
          .map((ref) => {
            const remaining = ref.broken_imports.filter((bi) => bi.import_path !== depPath);
            return remaining.length === 0 ? null : { ...ref, broken_imports: remaining };
          })
          .filter(Boolean) as typeof prev.broken_refs;
        return { ...prev, broken_refs: updatedRefs };
      });
      showToast(`已加入白名单: ${depName}`);
    } catch (err: any) {
      showToast("添加失败: " + err.message, "error");
    } finally {
      setFixingVerify(null);
    }
  };

  const closeVerifyModal = () => setVerifyResult(null);

  // ── Derived ──

  const allRefCats = useMemo(
    () => Object.keys(entities).filter((c) => entities[c]?.length > 0),
    [entities]
  );

  const sessionsWithConfig = useMemo(
    () => sessions.filter((s) => s.usable),
    [sessions]
  );

  // ── Helpers for render ──

  const findDocInTree = (path: string): IndexDocSummary | null => {
    if (!overview) return null;
    for (const cat of overview.categories) {
      const doc = cat.docs.find((d) => d.path === path);
      if (doc) return doc;
    }
    return null;
  };

  const selectedDocInfo = selectedDoc ? findDocInTree(selectedDoc) : null;
  const selectedDocImportedBy = selectedDocInfo?.imported_by || [];

  // ── Dependency auto-fill data ──

  const docImportMap = useMemo(() => {
    const map: Record<string, { path: string; name: string }[]> = {};
    if (!overview) return map;
    for (const cat of overview.categories) {
      for (const doc of cat.docs) {
        map[doc.path] = doc.imports;
      }
    }
    return map;
  }, [overview]);

  const allEntityPaths = useMemo(() => {
    const paths = new Set<string>();
    for (const [cat, ents] of Object.entries(entities)) {
      for (const ent of ents) {
        paths.add(`${cat}/${ent.id}`);
      }
    }
    return paths;
  }, [entities]);

  const pathToCatId = useMemo(() => {
    const map: Record<string, { cat: string; id: string }> = {};
    for (const [cat, ents] of Object.entries(entities)) {
      for (const ent of ents) {
        map[`${cat}/${ent.id}`] = { cat, id: ent.id };
      }
    }
    return map;
  }, [entities]);

  const depCheckResult = useMemo(() => {
    if (!sessionConfig || sessionConfig.mode !== "whitelist") {
      return { resolvable: [], broken: [], totalMissing: 0 };
    }
    const enabledPaths = new Set<string>();
    for (const [cat, ents] of Object.entries(entities)) {
      if (sessionConfig.enabled_categories.includes(cat)) {
        for (const ent of ents) enabledPaths.add(`${cat}/${ent.id}`);
      }
      const catEnts = sessionConfig.enabled_entities[cat];
      if (catEnts) {
        for (const id of catEnts) enabledPaths.add(`${cat}/${id}`);
      }
    }
    const seen = new Set<string>();
    const resolvable: { path: string; name: string; cat: string; id: string }[] = [];
    const broken: { path: string; name: string; sourceEntity: string }[] = [];

    for (const enabledPath of enabledPaths) {
      const imports = docImportMap[enabledPath] || [];
      for (const imp of imports) {
        if (enabledPaths.has(imp.path) || seen.has(imp.path)) continue;
        seen.add(imp.path);
        const info = pathToCatId[imp.path];
        if (info) {
          resolvable.push({ path: imp.path, name: imp.name, cat: info.cat, id: info.id });
        } else {
          broken.push({ path: imp.path, name: imp.name, sourceEntity: enabledPath });
        }
      }
    }
    return { resolvable, broken, totalMissing: resolvable.length + broken.length };
  }, [sessionConfig, entities, docImportMap, pathToCatId]);

  const handleAutoFillDeps = () => {
    setSessionConfig((prev) => {
      if (!prev || prev.mode !== "whitelist") return prev;
      const ents = { ...prev.enabled_entities };
      for (const dep of depCheckResult.resolvable) {
        const list = ents[dep.cat] || [];
        if (!list.includes(dep.id)) {
          ents[dep.cat] = [...list, dep.id];
        }
      }
      return { ...prev, enabled_entities: ents };
    });
  };

  // ═══════════════════════════════════════════
  // RENDER: Session config panel (center, for session source)
  // ═══════════════════════════════════════════

  const renderSessionConfig = () => {
    if (sessionConfigLoading) {
      return <div className="p-4 text-gray-400 text-sm">加载会话配置中...</div>;
    }
    if (!sessionConfig) {
      return <div className="p-4 text-gray-500 text-sm">无法加载会话配置</div>;
    }

    const sessionName = sessions.find((s) => s.id === activeSessionId)?.name || activeSessionId;

    return (
      <div className="p-4 overflow-y-auto h-full space-y-4">
        {/* Session name */}
        <div>
          <h2 className="text-sm font-bold text-amber-400">{sessionName}</h2>
          <p className="text-xs text-gray-500 mt-0.5">会话索引白名单配置</p>
        </div>

        {/* Mode switch */}
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-400">索引模式：</span>
          <button
            onClick={() => setSessionConfig((prev) => prev ? { ...prev, mode: "all" } : prev)}
            className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
              sessionConfig.mode === "all"
                ? "bg-blue-600 text-white"
                : "bg-gray-700 text-gray-400 hover:text-gray-200"
            }`}
          >
            启用所有实体
          </button>
          <button
            onClick={() => setSessionConfig((prev) => prev ? { ...prev, mode: "whitelist" } : prev)}
            className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
              sessionConfig.mode === "whitelist"
                ? "bg-amber-600 text-white"
                : "bg-gray-700 text-gray-400 hover:text-gray-200"
            }`}
          >
            白名单模式
          </button>
        </div>

        {/* Whitelist editor */}
        {sessionConfig.mode === "whitelist" && (
          <div className="space-y-2 max-h-[500px] overflow-y-auto">
            {Object.keys(entities).length === 0 && (
              <div className="text-gray-500 text-sm">暂无实体数据</div>
            )}
            {Object.entries(entities).map(([cat, ents]) => (
              <div key={cat} className="card p-3">
                <div className="flex items-center justify-between mb-2">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={sessionConfig.enabled_categories.includes(cat)}
                      onChange={() => toggleSessionCategory(cat)}
                      className="accent-amber-500"
                    />
                    <span className="font-medium text-gray-200">{catLabel(cat)}</span>
                    <span className="text-gray-500">({ents.length} 项)</span>
                  </label>
                  <div className="flex gap-2">
                    <button
                      onClick={() => selectAllInCategory(cat)}
                      className="text-xs text-gray-400 hover:text-gray-200"
                    >
                      全选
                    </button>
                    <button
                      onClick={() => deselectAllInCategory(cat)}
                      className="text-xs text-gray-400 hover:text-gray-200"
                    >
                      取消全选
                    </button>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {ents.map((ent) => (
                    <button
                      key={ent.id}
                      onClick={() => toggleSessionEntity(cat, ent.id)}
                      className={`text-xs px-2 py-0.5 rounded-full transition-colors ${
                        (sessionConfig.enabled_entities[cat] || []).includes(ent.id)
                          ? "bg-blue-600/30 text-blue-300 border border-blue-500/40"
                          : "bg-gray-700 text-gray-400 border border-gray-600 hover:text-gray-200"
                      }`}
                    >
                      {ent.name}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Dependency check for whitelist mode */}
        {sessionConfig.mode === "whitelist" && depCheckResult.totalMissing > 0 && (
          <div className="p-3 rounded bg-gray-800/60 border border-gray-700/60 space-y-2">
            <div className="text-xs font-medium text-gray-300">依赖检查</div>
            {depCheckResult.resolvable.length > 0 && (
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-gray-400">
                  已选文档引用了 <span className="text-amber-300">{depCheckResult.resolvable.length}</span> 个未启用的文档
                </span>
                <button
                  onClick={handleAutoFillDeps}
                  className="text-xs px-2.5 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded transition-colors shrink-0"
                >
                  补全依赖
                </button>
              </div>
            )}
            {depCheckResult.broken.length > 0 && (
              <div>
                <div className="text-xs text-red-400">
                  以下 {depCheckResult.broken.length} 个引用目标不存在：
                </div>
                <div className="mt-1 space-y-0.5">
                  {depCheckResult.broken.map((b) => (
                    <div key={b.path} className="text-xs text-gray-500 ml-2" title={b.sourceEntity}>
                      ✗ {b.name}
                      <span className="text-gray-600 ml-1 font-mono">({b.path})</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {sessionConfig.mode === "all" && (
          <div className="text-gray-500 text-sm py-4">
            当前会话将使用所有可用实体构建上下文。切换到"白名单模式"可限制仅启用部分实体。
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-3 pt-2">
          <button
            onClick={handleSaveSessionConfig}
            disabled={sessionConfigSaving}
            className="btn-primary text-sm"
          >
            {sessionConfigSaving ? "保存中..." : "保存配置"}
          </button>
          <button
            onClick={handleResetSessionConfig}
            disabled={sessionConfigSaving}
            className="btn-ghost text-sm"
          >
            重置为默认
          </button>
        </div>
      </div>
    );
  };

  // ═══════════════════════════════════════════
  // RENDER: Detail panel (center)
  // ═══════════════════════════════════════════

  const renderDetail = () => {
    // Session source without selected doc → show config editor
    if (activeSource !== "global" && !selectedDoc) {
      return renderSessionConfig();
    }

    if (!selectedDoc) {
      return (
        <div className="p-4 overflow-y-auto h-full">
          <h3 className="text-xs font-medium text-gray-400 mb-3">
            {activeSource === "global" ? "所有类别" : "会话配置"}
          </h3>
          {activeSource === "global" ? (
            <div className="grid grid-cols-2 gap-3">
              {allRefCats.map((refCat) => {
                const catEntities = entities[refCat] || [];
                return (
                  <div key={refCat} className="p-3 rounded bg-gray-800/40 border border-gray-700/50">
                    <div className="text-xs font-medium text-gray-300 mb-1">
                      {catLabel(refCat)}
                    </div>
                    <div className="text-[10px] text-gray-500 mb-2">
                      {catEntities.length} 项
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {catEntities.slice(0, 8).map((e) => (
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
          ) : (
            <div className="text-gray-500 text-sm">
              从左侧树中选择会话查看配置
            </div>
          )}
        </div>
      );
    }

    const isSelectedDocInTree = !!selectedDocInfo;

    return (
      <div className="p-4 overflow-y-auto h-full">
        {/* Doc header */}
        <div className="mb-4 shrink-0">
          <h2 className="text-sm font-medium text-blue-300">
            {selectedDocInfo?.name || selectedDoc.split("/").pop()}
          </h2>
          <p className="text-xs text-gray-500 font-mono mt-0.5">{selectedDoc}</p>
        </div>

        {/* Imports (outgoing) */}
        <div className="mb-6">
          <h3 className="text-xs font-medium text-gray-400 mb-2 flex items-center gap-2">
            依赖引用
            <span className="text-gray-600 font-normal">({docImports.length})</span>
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {docImports.length === 0 ? (
              <span className="text-xs text-gray-600 italic">未引用任何文档</span>
            ) : (
              docImports.map((imp) => {
                const isLoading = savingImport === imp.path;
                return (
                  <span
                    key={imp.path}
                    className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-blue-600/20 text-blue-300 border border-blue-500/30"
                  >
                    <span className="truncate max-w-[160px]" title={imp.path}>
                      {imp.name}
                    </span>
                    <button
                      onClick={() => removeImport(imp.path)}
                      disabled={!!isLoading}
                      className="text-blue-400 hover:text-red-400 transition-colors shrink-0 disabled:opacity-40"
                      title="移除引用"
                    >
                      {isLoading ? "..." : "✕"}
                    </button>
                  </span>
                );
              })
            )}
          </div>
        </div>

        {/* Imported by (read-only) */}
        {selectedDocImportedBy.length > 0 && (
          <div className="mb-4 pt-4 border-t border-gray-700">
            <h3 className="text-xs font-medium text-gray-400 mb-2">
              被引用
              <span className="text-gray-600 ml-1">({selectedDocImportedBy.length})</span>
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {selectedDocImportedBy.map((ref) => (
                <span
                  key={ref.path}
                  className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-amber-600/20 text-amber-300 border border-amber-500/30 cursor-pointer hover:bg-amber-600/30"
                  onClick={() => setSelectedDoc(ref.path)}
                  title={ref.path}
                >
                  {ref.name}
                  <span className="text-amber-500/60 text-[10px]">←</span>
                </span>
              ))}
            </div>
          </div>
        )}

        {!isSelectedDocInTree && (
          <div className="mt-4 p-3 bg-gray-800/50 border border-gray-700 rounded">
            <p className="text-xs text-gray-400">文档在扫描数据中不可见（缓存未更新）</p>
          </div>
        )}
      </div>
    );
  };

  // ═══════════════════════════════════════════
  // RENDER: Add panel (right)
  // ═══════════════════════════════════════════

  const renderAddPanel = () => {
    if (!selectedDoc) return null;

    const currentPaths = new Set(docImports.map((i) => i.path));

    return (
      <div className="p-3 overflow-y-auto h-full">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-medium text-gray-400">添加引用</span>
          {searchTerm && (
            <button
              onClick={() => setSearchTerm("")}
              className="text-[10px] text-gray-500 hover:text-gray-300"
            >
              清除
            </button>
          )}
        </div>
        <input
          className="w-full px-2 py-1 text-xs bg-gray-700 border border-gray-600 rounded outline-none text-gray-200 mb-3"
          placeholder="搜索实体..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />

        <div className="space-y-4">
          {allRefCats.map((refCat) => {
            const catEntities = entities[refCat] || [];
            const filtered = catEntities.filter(
              (e) =>
                !currentPaths.has(`${refCat}/${e.id}`) &&
                (searchTerm === "" ||
                  e.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
                  e.id.toLowerCase().includes(searchTerm.toLowerCase()))
            );
            if (filtered.length === 0) return null;

            return (
              <div key={refCat}>
                <div className="text-xs text-gray-500 mb-1">
                  {catLabel(refCat)}
                  <span className="text-gray-600 ml-1">({filtered.length})</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {filtered.slice(0, 40).map((e) => {
                    const isLoading = savingImport === `${refCat}/${e.id}`;
                    return (
                      <button
                        key={e.id}
                        onClick={() => addImport(refCat, e.id)}
                        disabled={!!isLoading}
                        className="text-xs px-1.5 py-0.5 rounded bg-gray-800/50 text-gray-400 border border-gray-700/50 hover:border-green-700/50 hover:text-green-400 transition-colors truncate max-w-[160px] disabled:opacity-40"
                        title={e.summary || e.name}
                      >
                        {isLoading ? "..." : `+ ${e.name}`}
                      </button>
                    );
                  })}
                  {filtered.length > 40 && (
                    <span className="text-[10px] text-gray-600">+{filtered.length - 40}</span>
                  )}
                </div>
              </div>
            );
          })}

          {allRefCats.every((refCat) => {
            const catEntities = entities[refCat] || [];
            return catEntities.every((e) => currentPaths.has(`${refCat}/${e.id}`));
          }) && (
            <p className="text-xs text-gray-600 italic text-center pt-4">
              {searchTerm ? "无匹配结果" : "所有实体已添加"}
            </p>
          )}
        </div>
      </div>
    );
  };

  // ═══════════════════════════════════════════
  // RENDER: Session dependency panel (right, for session source)
  // ═══════════════════════════════════════════

  const renderSessionDepsPanel = () => {
    if (!sessionConfig) return null;

    // Compute enabled entity paths from config
    const enabledPaths = new Set<string>();
    if (sessionConfig.mode === "all") {
      // All entities are enabled
      for (const [cat, ents] of Object.entries(entities)) {
        for (const ent of ents) {
          enabledPaths.add(`${cat}/${ent.id}`);
        }
      }
    } else {
      // Whitelist mode: entities from enabled_categories + enabled_entities
      for (const [cat, ents] of Object.entries(entities)) {
        if (sessionConfig.enabled_categories.includes(cat)) {
          for (const ent of ents) {
            enabledPaths.add(`${cat}/${ent.id}`);
          }
        }
        const catEnts = sessionConfig.enabled_entities[cat];
        if (catEnts) {
          for (const id of catEnts) {
            enabledPaths.add(`${cat}/${id}`);
          }
        }
      }
    }

    const toggleExpand = (path: string) => {
      setExpandedImports((prev) => {
        const next = new Set(prev);
        if (next.has(path)) next.delete(path);
        else next.add(path);
        return next;
      });
    };

    // Build level → catLevels mapping from hierarchy
    const catLevelMap: Record<string, number> = {};
    const levelLabels: Record<number, string> = {};
    if (overview) {
      for (const h of overview.hierarchy) {
        levelLabels[h.level] = h.label;
        for (const c of h.categories) {
          catLevelMap[c] = h.level;
        }
      }
    }

    // Group enabled paths by hierarchy level
    const byLevel: Record<number, { label: string; paths: string[] }> = {};
    for (const path of enabledPaths) {
      const cat = path.split("/")[0];
      const level = catLevelMap[cat] ?? 99;
      if (!byLevel[level]) {
        byLevel[level] = { label: levelLabels[level] || `L${level}`, paths: [] };
      }
      byLevel[level].paths.push(path);
    }
    const sortedLevels = Object.entries(byLevel).sort(([a], [b]) => Number(a) - Number(b));

    // Recursively render a dependency node
    const renderDepNode = (path: string, depth: number, maxDepth: number = 3) => {
      if (depth > maxDepth) return null;
      const docInfo = findDocInTree(path);
      const nodeName = docInfo?.name || path.split("/").pop() || path;
      const imports = docInfo?.imports || [];
      const isExpanded = expandedImports.has(path);

      return (
        <div key={path} style={{ marginLeft: depth * 14 }}>
          <div className="flex items-center gap-1 py-0.5">
            {imports.length > 0 ? (
              <button
                onClick={() => toggleExpand(path)}
                className="text-[10px] text-gray-500 hover:text-gray-300 w-3 shrink-0 text-center"
              >
                {isExpanded ? "▼" : "▶"}
              </button>
            ) : (
              <span className="w-3 shrink-0" />
            )}
            <span className="text-xs truncate text-gray-300" title={path}>
              {nodeName}
            </span>
          </div>
          {isExpanded && imports.length > 0 && (
            <div>
              {imports.map((imp) => renderDepNode(imp.path, depth + 1, maxDepth))}
            </div>
          )}
        </div>
      );
    };

    // Group paths by category within a level, then render
    const renderLevelTree = (paths: string[]) => {
      const byCat: Record<string, string[]> = {};
      for (const p of paths) {
        const cat = p.split("/")[0];
        if (!byCat[cat]) byCat[cat] = [];
        byCat[cat].push(p);
      }
      return (
        <div className="ml-2">
          {Object.entries(byCat).sort(([a], [b]) => a.localeCompare(b)).map(([cat, catPaths]) => (
            <div key={cat} className="mb-2">
              <div className="text-[11px] font-medium text-gray-500 mb-0.5">
                {catLabel(cat)}
                <span className="text-gray-600 ml-1 font-normal">({catPaths.length})</span>
              </div>
              {catPaths.map((p) => renderDepNode(p, 0, 3))}
            </div>
          ))}
        </div>
      );
    };

    return (
      <div className="p-3 overflow-y-auto h-full">
        {/* Mode toggle */}
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-medium text-gray-400">
            {sessionRightMode === "deps" ? "依赖层级" : "实体列表"}
          </span>
          <div className="flex bg-gray-800 rounded p-0.5">
            <button
              onClick={() => setSessionRightMode("deps")}
              className={`text-[11px] px-2 py-0.5 rounded transition-colors ${
                sessionRightMode === "deps"
                  ? "bg-blue-600 text-white"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              层级
            </button>
            <button
              onClick={() => setSessionRightMode("list")}
              className={`text-[11px] px-2 py-0.5 rounded transition-colors ${
                sessionRightMode === "list"
                  ? "bg-blue-600 text-white"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              列表
            </button>
          </div>
        </div>

        {/* Entity count */}
        <div className="text-[11px] text-gray-500 mb-2">
          已启用 {enabledPaths.size} 个实体
          {sessionConfig.mode === "all" && "（全部模式）"}
        </div>

        {sessionRightMode === "deps" ? (
          /* Grouped by hierarchy level */
          <div>
            {sortedLevels.map(([level, group]) => (
              <div key={level} className="mb-3">
                <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider py-1 mb-1">
                  L{level}: {group.label}
                  <span className="text-gray-600 ml-1 font-normal normal-case">({group.paths.length})</span>
                </div>
                {renderLevelTree(group.paths)}
              </div>
            ))}
          </div>
        ) : (
          /* Flat entity list (grouped by level → category) */
          <div>
            {sortedLevels.map(([level, group]) => {
              // Group by category within level
              const byCat: Record<string, string[]> = {};
              for (const p of group.paths) {
                const cat = p.split("/")[0];
                if (!byCat[cat]) byCat[cat] = [];
                byCat[cat].push(p);
              }
              return (
                <div key={level} className="mb-3">
                  <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider py-1 mb-1">
                    L{level}: {group.label}
                    <span className="text-gray-600 ml-1 font-normal normal-case">({group.paths.length})</span>
                  </div>
                  {Object.entries(byCat).sort(([a], [b]) => a.localeCompare(b)).map(([cat, catPaths]) => (
                    <div key={cat} className="ml-2 mb-2">
                      <div className="text-[11px] font-medium text-gray-500 mb-1">
                        {catLabel(cat)}
                        <span className="text-gray-600 ml-1 font-normal">({catPaths.length})</span>
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {catPaths.slice(0, 60).map((p) => (
                          <span
                            key={p}
                            className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700/40 text-gray-400"
                            title={p}
                          >
                            {p.split("/").pop()}
                          </span>
                        ))}
                        {catPaths.length > 60 && (
                          <span className="text-[10px] text-gray-600">+{catPaths.length - 60}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="flex flex-col h-full">
      {/* ── Top bar ── */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-700 shrink-0 flex-wrap">
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
          title="导入 YAML"
        >
          导入
        </button>
        <button
          onClick={handleExport}
          className="text-xs text-gray-400 hover:text-gray-200 px-2 py-1 rounded bg-gray-800/50 border border-gray-700 hover:border-gray-600 transition-colors"
          title="导出 YAML"
        >
          导出
        </button>
        <button
          onClick={handleVerify}
          disabled={verifying}
          className="text-xs px-2 py-1 rounded bg-gray-800/50 border border-gray-700 hover:border-gray-600 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          title="验证依赖完整性"
        >
          {verifying ? "验证中..." : "验证"}
        </button>
        <button
          onClick={loadData}
          className="text-xs text-gray-500 hover:text-gray-300 px-1"
          title="刷新"
        >
          ↻
        </button>
      </div>

      {/* ── Error ── */}
      {error && (
        <div className="mx-4 mt-2 p-2 bg-red-900/30 border border-red-700/30 rounded text-xs text-red-400 shrink-0">
          {error}
        </div>
      )}

      {/* ── Three-column body ── */}
      <div className="flex flex-1 min-h-0">
        {/* Left: config sources */}
        <div className="w-48 border-r border-gray-700 shrink-0 flex flex-col">
          {/* Config sources */}
          <div className="flex-1 overflow-y-auto">
            <div className="p-3">
              <div className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                配置源
              </div>
              <div className="space-y-0.5">
                <button
                  onClick={() => switchSource("global")}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors ${
                    activeSource === "global"
                      ? "bg-blue-600/20 text-blue-300 border border-blue-700/30"
                      : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/40 border border-transparent"
                  }`}
                >
                  <span>🌐</span>
                  <span className="font-medium">全局索引</span>
                </button>
                {sessionsWithConfig.map((s) => {
                  const isActive = activeSource === s.id;
                  return (
                    <button
                      key={s.id}
                      onClick={() => switchSource(s.id)}
                      className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors ${
                        isActive
                          ? "bg-amber-600/20 text-amber-300 border border-amber-700/30"
                          : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/40 border border-transparent"
                      }`}
                    >
                      <span>📝</span>
                      <span className="truncate flex-1 text-left">
                        {s.name.length > 20 ? s.name.slice(0, 18) + "…" : s.name}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

        </div>

        {/* Center: detail */}
        <div className="flex-1 overflow-y-auto">
          {renderDetail()}
        </div>

        {/* Right: add panel (global) / session deps (session) */}
        {selectedDoc && activeSource === "global" && (
          <div className="w-72 border-l border-gray-700 overflow-y-auto shrink-0">
            {renderAddPanel()}
          </div>
        )}
        {activeSource !== "global" && sessionConfig && (
          <div className="w-72 border-l border-gray-700 overflow-y-auto shrink-0">
            {renderSessionDepsPanel()}
          </div>
        )}
      </div>

      {/* ── Verify results modal ── */}
      {verifyResult && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60" onClick={closeVerifyModal}>
          <div
            className="bg-gray-800 border border-gray-600 rounded-lg shadow-xl w-[640px] max-h-[80vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700 shrink-0">
              <h3 className="text-sm font-medium text-gray-200">
                {activeSource !== "global" ? "会话依赖完整性验证" : "依赖完整性验证"}
              </h3>
              <button onClick={closeVerifyModal} className="text-gray-500 hover:text-gray-300 text-sm">✕</button>
            </div>
            <div className="p-4 overflow-y-auto space-y-3">
              {activeSource !== "global" && (
                <div className="text-xs text-gray-500">
                  会话: <span className="text-amber-400">{(sessions.find((s) => s.id === activeSource)?.name) || activeSource}</span>
                  {" "}模式: <span className="text-gray-300">{verifyResult.mode || "all"}</span>
                </div>
              )}
              <div className="flex gap-3 text-xs text-gray-400">
                <span>文档: {verifyResult.total_docs}</span>
                <span>引用: {verifyResult.total_imports}</span>
                <span className={verifyResult.broken_refs.length > 0 ? "text-red-400" : "text-green-400"}>
                  断裂: {verifyResult.broken_refs.reduce((s, r) => s + r.broken_imports.length, 0)}
                </span>
              </div>
              {verifyResult.broken_refs.length === 0 ? (
                <div className="py-8 text-center text-sm text-green-400">所有依赖引用完整 ✓</div>
              ) : (
                <div className="space-y-2">
                  {verifyResult.broken_refs.map((ref) => (
                    <div key={ref.doc_path} className="p-3 bg-gray-800/80 border border-red-900/40 rounded">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-xs font-medium text-gray-300" title={ref.doc_path}>
                          {ref.doc_name}
                          <span className="text-gray-500 ml-1 font-mono text-[10px]">{ref.doc_path}</span>
                        </span>
                      </div>
                      <div className="space-y-1">
                        {ref.broken_imports.map((bi) => {
                          const fixKey = `${ref.doc_path}::${bi.import_path}`;
                          const isFixing = fixingVerify === fixKey;
                          const isMissing = bi.type === "missing";
                          return (
                            <div key={bi.import_path} className="flex items-center justify-between pl-3 py-0.5">
                              <span className={`text-xs ${isMissing ? "text-amber-400" : "text-red-400"}`} title={bi.import_path}>
                                {isMissing ? "○" : "✗"} {bi.name}
                                <span className="text-gray-600 ml-1 font-mono text-[10px]">{bi.import_path}</span>
                                {isMissing && <span className="text-amber-600 ml-1 text-[10px]">(未启用)</span>}
                              </span>
                              {isMissing && activeSource !== "global" ? (
                                <button
                                  onClick={() => handleAddToWhitelist(bi.import_path, bi.name)}
                                  disabled={!!isFixing}
                                  className="text-[11px] px-2 py-0.5 rounded bg-gray-700 text-gray-400 hover:bg-blue-700 hover:text-white transition-colors disabled:opacity-40"
                                >
                                  {isFixing ? "处理中..." : "加入白名单"}
                                </button>
                              ) : (
                                <button
                                  onClick={() => handleRemoveBrokenImport(ref.doc_path, bi.import_path)}
                                  disabled={!!isFixing}
                                  className="text-[11px] px-2 py-0.5 rounded bg-gray-700 text-gray-400 hover:bg-red-700 hover:text-white transition-colors disabled:opacity-40"
                                >
                                  {isFixing ? "处理中..." : "移除引用"}
                                </button>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="flex justify-end px-4 py-3 border-t border-gray-700 shrink-0">
              <button onClick={closeVerifyModal} className="btn-primary text-sm">关闭</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Toast ── */}
      {toast && (
        <div
          className={`fixed bottom-4 right-4 z-50 px-4 py-2 rounded-lg shadow-lg text-sm ${
            toast.type === "error" ? "bg-red-600 text-white" : "bg-green-700 text-white"
          }`}
        >
          {toast.text}
        </div>
      )}
    </div>
  );
}
