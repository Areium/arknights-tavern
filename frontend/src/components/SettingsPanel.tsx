import { useState } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";

export default function SettingsPanel() {
  const { llmStatus } = useAppStore();
  const api = useApi();
  const [switching, setSwitching] = useState<string | null>(null);

  const handleSwitch = async (endpointId: string) => {
    setSwitching(endpointId);
    try {
      await api.switchLLM(endpointId);
    } catch (err: any) {
      alert("切换失败: " + err.message);
    } finally {
      setSwitching(null);
    }
  };

  const handleRefresh = async () => {
    try {
      await api.refreshLLM();
    } catch (err: any) {
      alert("刷新失败: " + err.message);
    }
  };

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <h2 className="text-lg font-bold">设置</h2>

      {/* LLM 状态 */}
      <section className="card">
        <h3 className="panel-title">LLM 后端</h3>

        <div className="space-y-3">
          {/* Primary */}
          <div>
            <span className="text-xs text-gray-500">主后端</span>
            {llmStatus?.primary ? (
              <div className="flex items-center justify-between mt-1">
                <div>
                  <span className="font-medium">{llmStatus.primary.name}</span>
                  <span className="text-xs text-gray-500 ml-2">
                    {llmStatus.primary.model}
                  </span>
                  {llmStatus.primary.latency_ms > 0 && (
                    <span className="text-xs text-gray-500 ml-2">
                      {llmStatus.primary.latency_ms}ms
                    </span>
                  )}
                </div>
                <span
                  className={`text-xs px-2 py-0.5 rounded ${
                    llmStatus.primary.available
                      ? "bg-green-800/50 text-green-300"
                      : "bg-red-800/50 text-red-300"
                  }`}
                >
                  {llmStatus.primary.available ? "可用" : "不可用"}
                </span>
              </div>
            ) : (
              <p className="text-sm text-gray-500 mt-1">未配置</p>
            )}
          </div>

          {/* Fallback */}
          {llmStatus?.fallback && (
            <div>
              <span className="text-xs text-gray-500">备用后端</span>
              <div className="flex items-center justify-between mt-1">
                <div>
                  <span className="font-medium">{llmStatus.fallback.name}</span>
                  <span className="text-xs text-gray-500 ml-2">
                    {llmStatus.fallback.model}
                  </span>
                </div>
                <span
                  className={`text-xs px-2 py-0.5 rounded ${
                    llmStatus.fallback.available
                      ? "bg-green-800/50 text-green-300"
                      : "bg-red-800/50 text-red-300"
                  }`}
                >
                  {llmStatus.fallback.available ? "可用" : "不可用"}
                </span>
              </div>
            </div>
          )}

          {/* All endpoints */}
          {llmStatus?.endpoints && llmStatus.endpoints.length > 0 && (
            <div className="mt-4">
              <span className="text-xs text-gray-500">可用端点</span>
              <div className="space-y-1 mt-1">
                {llmStatus.endpoints.map((ep) => (
                  <div
                    key={ep.id}
                    className="flex items-center justify-between px-3 py-2 bg-gray-700/30 rounded-lg text-sm"
                  >
                    <div className="min-w-0 flex-1">
                      <span className="font-medium truncate block">
                        {ep.name}
                      </span>
                      <span className="text-xs text-gray-500">
                        {ep.type === "cloud" ? "云端" : "本地"} · {ep.model}
                      </span>
                    </div>
                    <button
                      onClick={() => handleSwitch(ep.id)}
                      disabled={switching === ep.id || !ep.available}
                      className="ml-2 text-xs px-2 py-1 rounded bg-blue-600/30 text-blue-300 hover:bg-blue-600/50 disabled:opacity-50 shrink-0"
                    >
                      {switching === ep.id ? "切换中..." : "切换"}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          <button
            onClick={handleRefresh}
            className="btn-ghost text-sm mt-2"
          >
            刷新 LLM 列表
          </button>
        </div>
      </section>

      {/* 关于 */}
      <section className="card">
        <h3 className="panel-title">关于</h3>
        <div className="text-sm text-gray-400 space-y-1">
          <p>Arknights TXT v0.1.0</p>
          <p>基于 Electron + React + Python Flask</p>
          <p>
            LLM 后端:{" "}
            {llmStatus?.available ? "已连接" : "未连接"}
          </p>
        </div>
      </section>
    </div>
  );
}
