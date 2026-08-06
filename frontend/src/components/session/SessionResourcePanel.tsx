import { useState, useEffect, useCallback, useRef } from "react";
import { useAppStore } from "../../stores/appStore";
import { useApi } from "../../hooks/useApi";
import type {
  SessionResourcesDTO,
  SessionResourceDTO,
  SessionResourceDocDTO,
} from "../../types";

const MEDIA_LABEL: Record<string, string> = {
  avatar: "头像",
  skin: "立绘",
  card_face: "卡面",
};
const MEDIA_TYPES: Array<"avatar" | "skin" | "card_face"> = [
  "avatar",
  "skin",
  "card_face",
];

/** 拼接缓存爆破参数（v），保证覆盖图上传后强制刷新浏览器缓存 */
function withVersion(url: string | null | undefined, v: number): string {
  if (!url) return "";
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}v=${v}`;
}

function Thumb({ url, alt, className = "w-12 h-12" }: {
  url: string | null | undefined;
  alt: string;
  className?: string;
}) {
  const [ok, setOk] = useState(true);
  useEffect(() => { setOk(true); }, [url]);
  if (!url || !ok) {
    return (
      <div className={`${className} rounded bg-gray-800 flex items-center justify-center text-gray-600 text-[10px] shrink-0`}>
        无图
      </div>
    );
  }
  return (
    <img
      src={url}
      alt={alt}
      className={`${className} rounded object-cover shrink-0 border border-gray-700`}
      onError={() => setOk(false)}
    />
  );
}

export default function SessionResourcePanel() {
  const { activeSessionId, bumpResourceVersion } = useAppStore();
  const setSessions = useAppStore((s) => s.setSessions);
  const setActiveSession = useAppStore((s) => s.setActiveSession);
  const resourceVersion = useAppStore((s) => s.resourceVersion);
  const api = useApi();
  const importFileRef = useRef<HTMLInputElement | null>(null);

  const [data, setData] = useState<SessionResourcesDTO | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const [newDocPath, setNewDocPath] = useState("");
  const [importDocPath, setImportDocPath] = useState("");
  // 当前编辑的会话文档副本
  const [editingDoc, setEditingDoc] = useState<SessionResourceDocDTO | null>(null);
  const [editContent, setEditContent] = useState("");
  const [editLoading, setEditLoading] = useState(false);

  const load = useCallback(async () => {
    if (!activeSessionId) {
      setData(null);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const d = await api.getSessionResources(activeSessionId);
      setData(d);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [activeSessionId, api]);

  useEffect(() => {
    load();
  }, [load]);

  const refresh = async () => {
    await load();
    bumpResourceVersion();
  };

  const handleBgUpload = async (bgId: string, file: File) => {
    if (!activeSessionId) return;
    setBusy(true);
    try {
      await api.uploadSessionBackground(activeSessionId, bgId, file);
      await refresh();
    } catch (err: any) {
      alert("背景上传失败: " + err.message);
    } finally {
      setBusy(false);
    }
  };

  const handleBgDelete = async (bgId: string) => {
    if (!activeSessionId) return;
    setBusy(true);
    try {
      await api.deleteSessionBackground(activeSessionId, bgId);
      await refresh();
    } catch (err: any) {
      alert("删除失败: " + err.message);
    } finally {
      setBusy(false);
    }
  };

  const handleCharMediaUpload = async (
    name: string,
    mediaType: string,
    file: File,
  ) => {
    if (!activeSessionId) return;
    setBusy(true);
    try {
      await api.uploadSessionCharacterMedia(activeSessionId, name, mediaType, file);
      await refresh();
    } catch (err: any) {
      alert("形象上传失败: " + err.message);
    } finally {
      setBusy(false);
    }
  };

  const handleCharMediaDelete = async (name: string, mediaType: string) => {
    if (!activeSessionId) return;
    setBusy(true);
    try {
      await api.deleteSessionCharacterMedia(activeSessionId, name, mediaType);
      await refresh();
    } catch (err: any) {
      alert("删除失败: " + err.message);
    } finally {
      setBusy(false);
    }
  };

  const openDoc = async (doc: SessionResourceDocDTO) => {
    if (!activeSessionId) return;
    setEditingDoc(doc);
    setEditLoading(true);
    try {
      const d = await api.getSessionDoc(activeSessionId, doc.path);
      setEditContent(d.content);
    } catch (err: any) {
      alert("读取失败: " + err.message);
      setEditingDoc(null);
    } finally {
      setEditLoading(false);
    }
  };

  const saveDoc = async () => {
    if (!activeSessionId || !editingDoc) return;
    setBusy(true);
    try {
      await api.saveSessionDoc(activeSessionId, editingDoc.path, editContent, {});
      await load();
    } catch (err: any) {
      alert("保存失败: " + err.message);
    } finally {
      setBusy(false);
    }
  };

  const deleteDoc = async (doc: SessionResourceDocDTO) => {
    if (!activeSessionId) return;
    if (!window.confirm(`删除会话文档副本「${doc.path}」？（全局文档不受影响）`)) return;
    setBusy(true);
    try {
      await api.deleteSessionDoc(activeSessionId, doc.path);
      if (editingDoc?.path === doc.path) setEditingDoc(null);
      await load();
    } catch (err: any) {
      alert("删除失败: " + err.message);
    } finally {
      setBusy(false);
    }
  };

  const createDoc = async () => {
    if (!activeSessionId || !newDocPath.trim()) return;
    const path = newDocPath.trim();
    setBusy(true);
    try {
      await api.saveSessionDoc(activeSessionId, path, "", {});
      setNewDocPath("");
      await load();
    } catch (err: any) {
      alert("新建失败: " + err.message);
    } finally {
      setBusy(false);
    }
  };

  const importDoc = async () => {
    if (!activeSessionId || !importDocPath.trim()) return;
    const raw = importDocPath.trim();
    // 格式：category/path 或 category/path.md
    const slash = raw.indexOf("/");
    if (slash <= 0) {
      alert("请输入「类别/路径」，如 characters/银灰");
      return;
    }
    const category = raw.slice(0, slash);
    const docPath = raw.slice(slash + 1).replace(/\.md$/i, "");
    setBusy(true);
    try {
      await api.importSessionDoc(activeSessionId, category, docPath);
      setImportDocPath("");
      await load();
    } catch (err: any) {
      alert("导入失败: " + err.message);
    } finally {
      setBusy(false);
    }
  };

  const handleExport = async () => {
    if (!activeSessionId) return;
    setBusy(true);
    try {
      await api.exportSession(activeSessionId);
    } catch (err: any) {
      alert("导出失败: " + err.message);
    } finally {
      setBusy(false);
    }
  };

  const handleImport = async (file: File) => {
    setBusy(true);
    try {
      const res = await api.importSession(file);
      const newId = res?.id;
      const sessions = await api.listSessions();
      setSessions(sessions);
      if (newId) setActiveSession(newId);
      alert(`会话导入成功${newId && newId !== activeSessionId ? "，已切换到新会话" : ""}`);
    } catch (err: any) {
      alert("导入失败: " + err.message);
    } finally {
      setBusy(false);
    }
  };

  if (!activeSessionId) {
    return (
      <aside className="w-80 border-l border-gray-700 overflow-y-auto p-3 shrink-0 bg-gray-900/60">
        <h2 className="panel-title mb-2">会话资源</h2>
        <p className="text-gray-500 text-sm text-center py-6 leading-relaxed">
          请先选择一个会话
          <br />
          再管理它的覆盖资源
        </p>
      </aside>
    );
  }

  const bgByKey = new Map<string, SessionResourceDTO>(
    (data?.backgrounds ?? []).map((b): [string, SessionResourceDTO] => [b.key, b]),
  );
  const mediaByChar = new Map<string, SessionResourceDTO>(
    (data?.character_media ?? []).map((m): [string, SessionResourceDTO] => [m.key, m]),
  );

  return (
    <aside className="w-80 border-l border-gray-700 overflow-y-auto p-3 shrink-0 bg-gray-900/60 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="panel-title mb-0">会话资源</h2>
        <div className="flex gap-1">
          <button
            disabled={busy}
            onClick={handleExport}
            className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700 text-gray-300 hover:bg-gray-600"
            title="导出会话存档 zip（含资源依赖，可分享）"
          >
            ⬇ 导出
          </button>
          <button
            disabled={busy}
            onClick={() => importFileRef.current?.click()}
            className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700 text-gray-300 hover:bg-gray-600"
            title="导入会话存档 zip"
          >
            ⬆ 导入
          </button>
          <input
            ref={importFileRef}
            type="file"
            accept=".zip"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleImport(f);
              e.target.value = "";
            }}
          />
        </div>
      </div>
      {error && <p className="text-red-400 text-xs">加载失败: {error}</p>}
      {loading && <p className="text-gray-500 text-xs">加载中...</p>}

      {/* ── 角色形象 ── */}
      <section>
        <h3 className="text-xs font-semibold text-gray-400 mb-2">角色形象</h3>
        {!data || data.scene_characters.length === 0 ? (
          <p className="text-gray-600 text-xs">请先在左侧面板加载场景角色</p>
        ) : (
          <div className="space-y-2">
            {data.scene_characters.map((name) => {
              const covered = mediaByChar.get(name);
              const coveredType = covered?.media_type ?? null;
              return (
                <div key={name} className="card p-2">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium truncate">{name}</span>
                    <span
                      className={`text-[10px] px-1.5 rounded ${
                        coveredType
                          ? "bg-blue-700/40 text-blue-200"
                          : "bg-gray-700 text-gray-400"
                      }`}
                    >
                      {coveredType ? `会话覆盖·${MEDIA_LABEL[coveredType]}` : "全局来源"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 mb-1.5">
                    <Thumb
                      url={coveredType === "avatar" ? withVersion(covered?.url, resourceVersion) : `/api/characters/${encodeURIComponent(name)}/avatar`}
                      alt={`${name}头像`}
                    />
                    <Thumb
                      url={`/api/characters/${encodeURIComponent(name)}/avatar`}
                      alt={`${name}全局头像`}
                    />
                    <span className="text-[10px] text-gray-600">会话 / 全局</span>
                  </div>
                  <div className="flex gap-1 flex-wrap">
                    {MEDIA_TYPES.map((t) => {
                      const isCovered = coveredType === t;
                      const key = `char-${name}-${t}`;
                      return (
                        <button
                          key={t}
                          disabled={busy}
                          onClick={() => fileRefs.current[key]?.click()}
                          className={`text-[10px] px-1.5 py-0.5 rounded ${
                            isCovered
                              ? "bg-amber-700/30 text-amber-300 hover:bg-amber-700/50"
                              : "bg-gray-700 text-gray-300 hover:bg-gray-600"
                          }`}
                          title={`上传会话${MEDIA_LABEL[t]}（仅本会话生效）`}
                        >
                          {isCovered ? "替换" : "上传"}{MEDIA_LABEL[t]}
                        </button>
                      );
                    })}
                    {coveredType && (
                      <button
                        disabled={busy}
                        onClick={() => handleCharMediaDelete(name, coveredType!)}
                        className="text-[10px] px-1.5 py-0.5 rounded bg-red-700/30 text-red-300 hover:bg-red-700/50"
                        title="删除会话覆盖，还原为全局形象"
                      >
                        删除
                      </button>
                    )}
                    {MEDIA_TYPES.map((t) => (
                      <input
                        key={t}
                        type="file"
                        accept="image/*"
                        className="hidden"
                        ref={(el) => { fileRefs.current[`char-${name}-${t}`] = el; }}
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          if (f) handleCharMediaUpload(name, t, f);
                          e.target.value = "";
                        }}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* ── 战斗背景 ── */}
      <section>
        <h3 className="text-xs font-semibold text-gray-400 mb-2">战斗背景</h3>
        <p className="text-gray-600 text-[11px] mb-2">
          上传后，本会话的战斗优先使用此图；删除即还原全局背景。
        </p>
        {!data || data.available_background_ids.length === 0 ? (
          <p className="text-gray-600 text-xs">暂无可用背景</p>
        ) : (
          <div className="space-y-2">
            {data.available_background_ids.map((bgId) => {
              const covered = bgByKey.get(bgId);
              return (
                <div key={bgId} className="card p-2">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium truncate">{bgId}</span>
                    <span
                      className={`text-[10px] px-1.5 rounded ${
                        covered
                          ? "bg-blue-700/40 text-blue-200"
                          : "bg-gray-700 text-gray-400"
                      }`}
                    >
                      {covered ? "会话覆盖" : "全局来源"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 mb-1.5">
                    <Thumb
                      url={covered ? withVersion(covered.url, resourceVersion) : null}
                      alt={`${bgId}会话图`}
                      className="w-16 h-10"
                    />
                    <Thumb
                      url={covered ? covered.global_url : null}
                      alt={`${bgId}全局图`}
                      className="w-16 h-10"
                    />
                    <span className="text-[10px] text-gray-600">会话 / 全局</span>
                  </div>
                  <div className="flex gap-1">
                    <button
                      disabled={busy}
                      onClick={() => fileRefs.current[`bg-${bgId}`]?.click()}
                      className={`text-[10px] px-1.5 py-0.5 rounded ${
                        covered
                          ? "bg-amber-700/30 text-amber-300 hover:bg-amber-700/50"
                          : "bg-gray-700 text-gray-300 hover:bg-gray-600"
                      }`}
                    >
                      {covered ? "替换" : "上传"}
                    </button>
                    {covered && (
                      <button
                        disabled={busy}
                        onClick={() => handleBgDelete(bgId)}
                        className="text-[10px] px-1.5 py-0.5 rounded bg-red-700/30 text-red-300 hover:bg-red-700/50"
                      >
                        删除
                      </button>
                    )}
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      ref={(el) => { fileRefs.current[`bg-${bgId}`] = el; }}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) handleBgUpload(bgId, f);
                        e.target.value = "";
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* ── 会话文档副本 ── */}
      <section>
        <h3 className="text-xs font-semibold text-gray-400 mb-2">会话文档</h3>
        <p className="text-gray-600 text-[11px] mb-2">
          会话内文档副本，编辑不影响全局原文。
        </p>
        <div className="flex gap-1 mb-2">
          <input
            value={newDocPath}
            onChange={(e) => setNewDocPath(e.target.value)}
            placeholder="新建路径，如 characters/我的设定"
            className="flex-1 min-w-0 bg-gray-800 rounded px-2 py-1 text-xs text-gray-200 placeholder-gray-600"
          />
          <button
            disabled={busy || !newDocPath.trim()}
            onClick={createDoc}
            className="text-[10px] px-2 py-1 rounded bg-green-700/30 text-green-300 hover:bg-green-700/50"
          >
            新建
          </button>
        </div>
        <div className="flex gap-1 mb-2">
          <input
            value={importDocPath}
            onChange={(e) => setImportDocPath(e.target.value)}
            placeholder="从全局导入，如 characters/银灰"
            className="flex-1 min-w-0 bg-gray-800 rounded px-2 py-1 text-xs text-gray-200 placeholder-gray-600"
          />
          <button
            disabled={busy || !importDocPath.trim()}
            onClick={importDoc}
            className="text-[10px] px-2 py-1 rounded bg-violet-700/30 text-violet-300 hover:bg-violet-700/50"
          >
            导入
          </button>
        </div>

        {data && data.docs.length > 0 && (
          <div className="space-y-1">
            {data.docs.map((doc) => (
              <div
                key={doc.path}
                className="flex items-center justify-between px-2 py-1.5 rounded bg-gray-800/50 text-xs"
              >
                <button
                  className="truncate text-left text-gray-200 hover:text-blue-300"
                  onClick={() => openDoc(doc)}
                  title={doc.path}
                >
                  {doc.path}
                </button>
                <div className="flex gap-1 shrink-0 ml-2">
                  <button
                    onClick={() => openDoc(doc)}
                    className="text-[10px] text-gray-400 hover:text-blue-300"
                  >
                    编辑
                  </button>
                  <button
                    onClick={() => deleteDoc(doc)}
                    className="text-[10px] text-gray-400 hover:text-red-400"
                  >
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {editingDoc && (
          <div className="mt-2 border border-gray-700 rounded p-2">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[11px] text-gray-400 truncate">{editingDoc.path}</span>
              <button
                onClick={() => setEditingDoc(null)}
                className="text-[10px] text-gray-500 hover:text-gray-300"
              >
                关闭
              </button>
            </div>
            {editLoading ? (
              <p className="text-gray-500 text-xs">加载中...</p>
            ) : (
              <>
                <textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  className="w-full h-40 bg-gray-900 rounded p-2 text-xs text-gray-200 font-mono resize-y"
                />
                <button
                  disabled={busy}
                  onClick={saveDoc}
                  className="mt-1.5 text-[10px] px-2 py-1 rounded bg-blue-700/40 text-blue-200 hover:bg-blue-700/60"
                >
                  保存副本
                </button>
              </>
            )}
          </div>
        )}
      </section>

      {/* ── 目录路径 ── */}
      {data && (
        <div className="text-[10px] text-gray-600 break-all border-t border-gray-700/50 pt-2">
          <div>resources: {data.resources_dir}</div>
          <div>backgrounds: {data.backgrounds_dir}</div>
        </div>
      )}
    </aside>
  );
}
