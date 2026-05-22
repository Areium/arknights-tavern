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

const CUSTOM = "__custom__";

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

  // 自由模式编辑态
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<EnvState>({ location: "", weather: "", time: "" });
  const [customFields, setCustomFields] = useState<Record<string, boolean>>({});

  // 剧情模式场景选择弹窗
  const [pickerOpen, setPickerOpen] = useState(false);

  const loadEnv = useCallback(async () => {
    if (!activeSessionId) return;
    setLoading(true);
    try {
      const data = await api.getEnvironment(activeSessionId);
      setEnv(data);
      setForm(data);
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

  const handleSave = async () => {
    if (!activeSessionId) return;
    try {
      await api.updateEnvironment(activeSessionId, form);
      setEnv(form);
      setEditing(false);
      setCustomFields({});
      triggerEnvRefresh();
    } catch (err: any) {
      alert("更新环境失败: " + err.message);
    }
  };

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

  const handleCancel = () => {
    setEditing(false);
    setForm(env || { location: "", weather: "", time: "" });
    setCustomFields({});
  };

  const updateForm = (field: keyof EnvState, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  // ── 下拉选择渲染 ──

  const renderSelect = (
    field: keyof EnvState,
    options: EnvPreset[],
    value: string,
    optionLabel: (o: EnvPreset) => string
  ) => {
    const isCustom = customFields[field] || (value && !options.find(
      (o) => o.name === value || o.id === value
    ));
    return (
      <div className="space-y-1">
        <select
          className="input text-sm"
          value={isCustom ? CUSTOM : value}
          onChange={(e) => {
            const v = e.target.value;
            if (v === CUSTOM) {
              setCustomFields((prev) => ({ ...prev, [field]: true }));
              updateForm(field, "");
            } else {
              setCustomFields((prev) => ({ ...prev, [field]: false }));
              updateForm(field, v);
            }
          }}
        >
          {options.map((o) => (
            <option key={o.name} value={o.name}>
              {optionLabel(o)}
            </option>
          ))}
          <option value={CUSTOM}>✏️ 自定义...</option>
        </select>
        {isCustom && (
          <input
            className="input text-sm"
            placeholder={`输入自定义${field === "location" ? "地点" : field === "weather" ? "天气" : "时间"}`}
            value={value}
            onChange={(e) => updateForm(field, e.target.value)}
          />
        )}
      </div>
    );
  };

  if (!activeSessionId) return null;

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
            <p className="text-xs text-gray-600 pt-2">环境由剧情发展决定</p>
          </div>
        ) : null}

        {/* 场景选择弹窗 */}
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

  // ── 自由模式：预设选择 + 自定义编辑 ──

  const locOptions = presets?.locations || [];
  const weatherOptions = presets?.weathers || [];
  const timeOptions = (presets?.times || []).map((t) => ({ name: t }));

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h2 className="panel-title mb-0">环境</h2>
        <button
          onClick={() => editing ? handleCancel() : setEditing(true)}
          className="text-xs text-gray-500 hover:text-gray-300"
        >
          {editing ? "取消" : "编辑"}
        </button>
      </div>

      {loading ? (
        <p className="text-gray-500 text-sm text-center py-2">加载中...</p>
      ) : error ? (
        <p className="text-red-400 text-sm text-center py-2">{error}</p>
      ) : editing ? (
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">地点</label>
            {renderSelect("location", locOptions, form.location, (o) => o.name)}
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">天气</label>
            {renderSelect("weather", weatherOptions, form.weather, (o) =>
              o.icon ? `${o.icon} ${o.name}` : o.name
            )}
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">时间</label>
            {renderSelect("time", timeOptions, form.time, (o) => o.name)}
          </div>
          <button onClick={handleSave} className="btn-primary text-sm w-full">
            保存
          </button>
        </div>
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
        </div>
      ) : null}
    </div>
  );
}
