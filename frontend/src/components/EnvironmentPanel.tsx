import { useState, useEffect, useCallback } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";

interface Environment {
  location: string;
  weather: string;
  time: string;
}

export default function EnvironmentPanel() {
  const { activeSessionId } = useAppStore();
  const api = useApi();
  const [env, setEnv] = useState<Environment | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Environment>({
    location: "",
    weather: "",
    time: "",
  });

  const loadEnv = useCallback(async () => {
    if (!activeSessionId) return;
    try {
      const data = await api.getEnvironment(activeSessionId);
      setEnv(data);
      setForm(data);
      setError("");
    } catch (err: any) {
      setError(err.message || "加载失败");
    }
  }, [activeSessionId, api]);

  useEffect(() => {
    loadEnv();
  }, [loadEnv]);

  const handleSave = async () => {
    if (!activeSessionId) return;
    try {
      await api.updateEnvironment(activeSessionId, form);
      setEnv(form);
      setEditing(false);
    } catch (err: any) {
      alert("更新环境失败: " + err.message);
    }
  };

  if (!activeSessionId) return null;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h2 className="panel-title mb-0">环境</h2>
        <button
          onClick={() => setEditing(!editing)}
          className="text-xs text-gray-500 hover:text-gray-300"
        >
          {editing ? "取消" : "编辑"}
        </button>
      </div>

      {editing ? (
        <div className="space-y-2">
          <div>
            <label className="text-xs text-gray-500">地点</label>
            <input
              className="input text-sm"
              value={form.location}
              onChange={(e) => setForm({ ...form, location: e.target.value })}
            />
          </div>
          <div>
            <label className="text-xs text-gray-500">天气</label>
            <input
              className="input text-sm"
              value={form.weather}
              onChange={(e) => setForm({ ...form, weather: e.target.value })}
            />
          </div>
          <div>
            <label className="text-xs text-gray-500">时间</label>
            <input
              className="input text-sm"
              value={form.time}
              onChange={(e) => setForm({ ...form, time: e.target.value })}
            />
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
      ) : error ? (
        <p className="text-red-400 text-sm text-center py-2">{error}</p>
      ) : (
        <p className="text-gray-500 text-sm text-center py-2">加载中...</p>
      )}
    </div>
  );
}
