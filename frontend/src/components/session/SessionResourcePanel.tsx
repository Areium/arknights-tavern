import { useState, useEffect, useCallback, useRef } from "react";
import { useAppStore } from "../../stores/appStore";
import { useApi } from "../../hooks/useApi";
import type {
  SessionResourcesDTO,
  SessionResourceDTO,
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
