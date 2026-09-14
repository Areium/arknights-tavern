import { useState, useEffect, useCallback } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";

interface EnvPreset {
  name: string;
  region?: string;
  summary?: string;
  icon?: string;
  id?: string;
  category?: string;
}

interface EnvState {
  location: string;
  weather: string;
  time: string;
}

export default function EnvironmentPanel() {
  const { activeSessionId, chatMode, envRefreshKey, triggerEnvRefresh, triggerSceneSwitch } =
    useAppStore();
  const api = useApi();

  const [env, setEnv] = useState<EnvState | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // 预设数据
  const [presets, setPresets] = useState<{
    locations: EnvPreset[];
    weathers: EnvPreset[];
    times: string[];
  } | null>(null);

  // 剧情模式场景选择弹窗
  const [pickerOpen, setPickerOpen] = useState(false);

  const loadEnv = useCallback(async () => {
    if (!activeSessionId) return;
    setLoading(true);
    try {
      const data = await api.getEnvironment(activeSessionId);
      setEnv(data);
      setError("");
    } catch (err: any) {
      setError(err.message || "加载失败");
    } finally {
      setLoading(false);
    }
  }, [activeSessionId, api]);

  const loadPresets = useCallback(async () => {
    if (presets) return;
    try {
      const data = await api.getEnvironmentPresets();
      setPresets(data);
    } catch {
      // 预设加载失败不影响使用
    }
  }, [api, presets]);

  useEffect(() => {
    loadEnv();
  }, [loadEnv]);

  // envRefreshKey 变化时刷新（SSE scene_event 触发）
  useEffect(() => {
    if (envRefreshKey > 0) loadEnv();
  }, [envRefreshKey]);

  // 首次加载预设
  useEffect(() => {
    loadPresets();
  }, [loadPresets]);

  const handlePickerSelect = async (locName: string) => {
    if (!activeSessionId) return;
    try {
      await api.updateEnvironment(activeSessionId, { location: locName });
      setPickerOpen(false);
      triggerEnvRefresh();
      triggerSceneSwitch();
    } catch (err: any) {
      alert("切换场景失败: " + err.message);
    }
  };

  if (!activeSessionId) return null;

  const readOnlyView = (note: string) => (
    <>
      {loading ? (
        <p className="text-gray-500 text-sm text-center py-2">加载中...</p>
      ) : error ? (
        <p className="text-red-400 text-sm text-center py-2">{error}</p>
      ) : env ? (
        <div className="text-sm space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-gray-500 w-8">📍</span>
            <span>{env.location || "未知"}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-gray-500 w-8">🌤</span>
            <span>{env.weather || "未知"}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-gray-500 w-8">⏰</span>
            <span>{env.time || "未知"}</span>
          </div>
          <p className="text-xs text-gray-600 pt-2">{note}</p>
        </div>
      ) : null}
    </>
  );

  // ── 剧情模式：只读 + 场景选择 ──

  if (chatMode === "story") {
    return (
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h2 className="panel-title mb-0">环境</h2>
          <button
            onClick={() => setPickerOpen(true)}
            className="text-xs text-blue-400 hover:text-blue-300"
          >
            切换场景
          </button>
        </div>

        {readOnlyView("环境由剧情发展决定")}
        {pickerOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
               onClick={() => setPickerOpen(false)}>
            <div className="bg-gray-800 border border-gray-600 rounded-xl p-4 w-80 max-h-96 overflow-y-auto"
                 onClick={(e) => e.stopPropagation()}>
              <h3 className="text-sm font-medium mb-3">选择目的地</h3>
              <div className="space-y-1">
                {(presets?.locations || []).map((loc) => (
                  <button
                    key={loc.name}
                    onClick={() => handlePickerSelect(loc.name)}
                    className="w-full text-left px-3 py-2 rounded-lg hover:bg-gray-700/50 transition-colors"
                  >
                    <div className="text-sm">{loc.name}</div>
                    {loc.summary && (
                      <div className="text-xs text-gray-500 mt-0.5 line-clamp-2">
                        {loc.summary}
                      </div>
                    )}
                  </button>
                ))}
              </div>
              <button
                onClick={() => setPickerOpen(false)}
                className="btn-ghost text-xs w-full mt-3"
              >
                取消
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── 自由模式：只读（环境由会话/剧情统一管理，对话内不再手动编辑） ──

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h2 className="panel-title mb-0">环境</h2>
      </div>
      {readOnlyView("环境由会话统一管理")}
    </div>
  );
}
