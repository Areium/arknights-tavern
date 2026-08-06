import { useCallback, useEffect, useState } from "react";
import { useApi } from "../../hooks/useApi";
import type { SessionBackgroundListDTO } from "../../types";

interface Props {
  sessionId: string;
  onToast?: (message: string, type?: "success" | "error") => void;
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
}

/** 会话级战斗背景覆盖管理：列表 / 上传 / 替换 / 删除。 */
export default function SessionBackgrounds({ sessionId, onToast }: Props) {
  const api = useApi();
  const [data, setData] = useState<SessionBackgroundListDTO | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [bgIdChoice, setBgIdChoice] = useState("default");
  const [customBgId, setCustomBgId] = useState("");
  const [uploading, setUploading] = useState(false);
  // 替换同 bg_id 图后 URL 不变，用版本号强制刷新缩略图
  const [version, setVersion] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await api.listSessionBackgrounds(sessionId));
    } catch (e: any) {
      setError(e.message || "加载失败");
    } finally {
      setLoading(false);
    }
  }, [api, sessionId]);

  useEffect(() => {
    setData(null);
    load();
  }, [load]);

  const effectiveBgId = bgIdChoice === "__custom__" ? customBgId.trim() : bgIdChoice;

  const handleUpload = async (file: File) => {
    if (!effectiveBgId) {
      onToast?.("请先选择或输入背景 ID", "error");
      return;
    }
    setUploading(true);
    try {
      await api.uploadSessionBackground(sessionId, effectiveBgId, file);
      onToast?.(`已上传为「${effectiveBgId}」的会话覆盖`);
      await load();
      setVersion((v) => v + 1);
    } catch (e: any) {
      onToast?.(e.message || "上传失败", "error");
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (name: string, bgId: string) => {
    if (!window.confirm(`删除会话覆盖 ${name}？该会话的「${bgId}」背景将回退到全局图。`)) return;
    try {
      await api.deleteSessionBackground(sessionId, name);
      onToast?.("已删除");
      await load();
    } catch (e: any) {
      onToast?.(e.message || "删除失败", "error");
    }
  };

  const availableIds = data?.available_bg_ids ?? [];

  return (
    <div className="space-y-3">
      {/* 上传区 */}
      <div className="border border-gray-700 rounded-lg p-3 space-y-2">
        <div className="text-xs text-gray-400">上传覆盖图（仅当前会话生效）</div>
        <div className="flex items-center gap-2">
          <select
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-300 flex-1 min-w-0"
            value={bgIdChoice}
            onChange={(e) => setBgIdChoice(e.target.value)}
          >
            {availableIds.map((id) => (
              <option key={id} value={id}>{id}</option>
            ))}
            <option value="__custom__">✏️ 自定义 ID...</option>
          </select>
          <label className={`text-xs px-3 py-1 rounded cursor-pointer shrink-0 ${
            uploading ? "bg-gray-700 text-gray-500" : "bg-blue-600 hover:bg-blue-500 text-white"
          }`}>
            {uploading ? "上传中..." : "选择图片"}
            <input
              type="file"
              accept=".png,.jpg,.jpeg,.webp"
              className="hidden"
              disabled={uploading}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleUpload(file);
                e.target.value = "";
              }}
            />
          </label>
        </div>
        {bgIdChoice === "__custom__" && (
          <input
            type="text"
            className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-300"
            placeholder="背景 ID（小写字母/数字/下划线，如 kjerag_snow）"
            value={customBgId}
            onChange={(e) => setCustomBgId(e.target.value)}
          />
        )}
        <p className="text-[10px] text-gray-600 leading-relaxed">
          文件名即背景 ID：上传到 <code>default</code> 替换本会话兜底背景；上传到某个全局 ID 则仅在本会话覆盖它。
          建议 1920×1080 的 jpg/webp。
        </p>
      </div>

      {/* 列表 */}
      {loading && !data ? (
        <p className="text-gray-500 text-sm text-center py-4">加载中...</p>
      ) : error ? (
        <p className="text-red-400 text-sm text-center py-4">{error}</p>
      ) : !data || data.backgrounds.length === 0 ? (
        <p className="text-gray-600 text-xs text-center py-4 leading-relaxed">
          当前会话还没有覆盖任何背景。<br />上传后，本会话的战斗将优先使用这些图。
        </p>
      ) : (
        <div className="space-y-2">
          {data.backgrounds.map((bg) => (
            <div key={bg.name} className="border border-gray-700 rounded-lg overflow-hidden">
              <div className="flex gap-2 p-2">
                {/* 会话覆盖图 */}
                <div className="flex-1 min-w-0">
                  <div className="text-[10px] text-gray-500 mb-1">会话覆盖</div>
                  <img
                    src={`${bg.url}?v=${version}`}
                    alt={bg.name}
                    className="w-full aspect-video object-cover rounded border border-gray-700"
                  />
                </div>
                {/* 全局原图对比 */}
                {bg.global_url && (
                  <div className="flex-1 min-w-0">
                    <div className="text-[10px] text-gray-500 mb-1">全局原图</div>
                    <img
                      src={bg.global_url}
                      alt={`global ${bg.bg_id}`}
                      className="w-full aspect-video object-cover rounded border border-gray-700 opacity-70"
                    />
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2 px-2 pb-2">
                <span className="text-xs text-blue-400 font-mono truncate">{bg.bg_id}</span>
                <span className="text-[10px] text-gray-600 shrink-0">{formatSize(bg.size)}</span>
                <div className="flex-1" />
                <label className="text-[10px] text-blue-400 hover:text-blue-300 cursor-pointer shrink-0">
                  替换
                  <input
                    type="file"
                    accept=".png,.jpg,.jpeg,.webp"
                    className="hidden"
                    disabled={uploading}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) {
                        setUploading(true);
                        api.uploadSessionBackground(sessionId, bg.bg_id, file)
                          .then(async () => {
                            onToast?.(`已替换「${bg.bg_id}」的会话覆盖`);
                            await load();
                            setVersion((v) => v + 1);
                          })
                          .catch((err) => onToast?.(err.message || "上传失败", "error"))
                          .finally(() => setUploading(false));
                      }
                      e.target.value = "";
                    }}
                  />
                </label>
                <button
                  className="text-[10px] text-red-400 hover:text-red-300 shrink-0"
                  onClick={() => handleDelete(bg.name, bg.bg_id)}
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 目录位置 */}
      {data && (
        <p className="text-[10px] text-gray-700 break-all" title={data.backgrounds_dir}>
          目录：{data.backgrounds_dir}
        </p>
      )}
    </div>
  );
}
