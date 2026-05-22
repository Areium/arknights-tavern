import { useState, useEffect, useCallback } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";

export default function SettingsPanel() {
  const { llmStatus, theme, toggleTheme } = useAppStore();
  const api = useApi();
  const [switching, setSwitching] = useState<string | null>(null);

  // LLM 配置表单
  const [config, setConfig] = useState({
    api_key: "",
    base_url: "",
    cloud_model: "",
    ollama_url: "",
    ollama_model: "",
    auto_generate_choices: false,
    choice_count: 3,
  });
  const [configLoaded, setConfigLoaded] = useState(false);
  const [configError, setConfigError] = useState("");
  const [saving, setSaving] = useState(false);
  const [configMsg, setConfigMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [showKey, setShowKey] = useState(false);

  // 连接测试状态
  const [testResult, setTestResult] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [testing, setTesting] = useState<string | null>(null); // "cloud" | "ollama" | null

  const handleTest = async (type: "cloud" | "ollama") => {
    // 校验必填字段
    const missing: string[] = [];
    if (type === "cloud") {
      if (!config.api_key.trim()) missing.push("API Key");
      if (!config.base_url.trim()) missing.push("API 地址");
    } else {
      if (!config.ollama_url.trim()) missing.push("Ollama 地址");
    }
    if (missing.length > 0) {
      setTestResult({ type: "err", text: `请先填写: ${missing.join("、")}` });
      return;
    }

    setTesting(type);
    setTestResult(null);
    try {
      const params: Record<string, string> =
        type === "cloud"
          ? { api_key: config.api_key, base_url: config.base_url, model: config.cloud_model }
          : { ollama_url: config.ollama_url, model: config.ollama_model };
      const result = await api.testLLMConnection(type, params);
      if (result.ok) {
        setTestResult({
          type: "ok",
          text: `连接成功 — ${result.model || "未知模型"} · ${result.latency_ms}ms`,
        });
      } else {
        setTestResult({ type: "err", text: `连接失败: ${result.detail || "未知错误"}` });
      }
    } catch (err: any) {
      setTestResult({ type: "err", text: `测试异常: ${err.message}` });
    } finally {
      setTesting(null);
    }
  };

  const loadConfig = useCallback(async () => {
    setConfigError("");
    try {
      const data = await api.getLLMConfig();
      setConfig({
        api_key: data.api_key || "",
        base_url: data.base_url || "",
        cloud_model: data.cloud_model || "",
        ollama_url: data.ollama_url || "",
        ollama_model: data.ollama_model || "",
        auto_generate_choices: data.auto_generate_choices || false,
        choice_count: data.choice_count || 3,
      });
      setConfigLoaded(true);
    } catch (err: any) {
      setConfigError(err.message || "无法加载配置");
    }
  }, [api]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const handleSaveConfig = async () => {
    setSaving(true);
    setConfigMsg(null);
    try {
      await api.updateLLMConfig({
        api_key: config.api_key,
        base_url: config.base_url,
        cloud_model: config.cloud_model,
        ollama_url: config.ollama_url,
        ollama_model: config.ollama_model,
        auto_generate_choices: config.auto_generate_choices,
        choice_count: config.choice_count,
      });
      setConfigMsg({ type: "ok", text: "配置已保存，端点已重新检测" });
    } catch (err: any) {
      setConfigMsg({ type: "err", text: "保存失败: " + err.message });
    } finally {
      setSaving(false);
    }
  };

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

  const handleToggleTheme = async () => {
    const newTheme = theme === "dark" ? "light" : "dark";
    toggleTheme(); // 立即更新 UI
    // 异步持久化到后端配置文件
    try {
      await api.updateLLMConfig({ theme: newTheme });
    } catch {
      /* 非关键 */
    }
  };

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <h2 className="text-lg font-bold">设置</h2>

      {/* 主题切换 */}
      <section className="card">
        <h3 className="panel-title">外观</h3>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">
              {theme === "dark" ? "深色模式" : "浅色模式"}
            </p>
            <p className="text-xs text-gray-500 mt-0.5">
              {theme === "dark" ? "护眼暗色界面" : "明亮清晰界面"}
            </p>
          </div>
          <button
            onClick={handleToggleTheme}
            className={`relative w-12 h-6 rounded-full transition-colors duration-200 ${
              theme === "dark" ? "bg-blue-600" : "bg-gray-300"
            }`}
          >
            <span
              className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform duration-200 ${
                theme === "dark" ? "left-6" : "left-0.5"
              }`}
            />
          </button>
        </div>
      </section>

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

      {/* LLM 配置 */}
      <section className="card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="panel-title mb-0">LLM 配置</h3>
          {configError && (
            <button onClick={loadConfig} className="text-xs text-blue-400 hover:text-blue-300">
              重试加载
            </button>
          )}
        </div>

        {configError ? (
          <p className="text-red-400 text-sm mb-3">{configError}</p>
        ) : !configLoaded ? (
          <p className="text-gray-500 text-sm mb-3">加载配置中...</p>
        ) : null}

        <div className="space-y-3">
          {/* 云端 API */}
          <fieldset className="border border-gray-700 rounded-lg p-3">
            <legend className="text-xs text-gray-400 px-1">云端 API</legend>
            <div className="space-y-2">
              <div>
                <label className="text-xs text-gray-500">API Key</label>
                <div className="flex gap-1">
                  <input
                    className="input text-sm flex-1"
                    type={showKey ? "text" : "password"}
                    value={config.api_key}
                    onChange={(e) => setConfig({ ...config, api_key: e.target.value })}
                    placeholder="sk-..."
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey(!showKey)}
                    className="text-xs text-gray-500 hover:text-gray-300 px-2 shrink-0"
                  >
                    {showKey ? "隐藏" : "显示"}
                  </button>
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-500">API 地址</label>
                <input
                  className="input text-sm"
                  value={config.base_url}
                  onChange={(e) => setConfig({ ...config, base_url: e.target.value })}
                  placeholder="https://api.deepseek.com/v1"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">模型名称</label>
                <input
                  className="input text-sm"
                  value={config.cloud_model}
                  onChange={(e) => setConfig({ ...config, cloud_model: e.target.value })}
                  placeholder="deepseek-v4-flash"
                />
              </div>
              <button
                type="button"
                onClick={() => handleTest("cloud")}
                disabled={testing !== null}
                className="text-xs px-3 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600 disabled:opacity-50"
              >
                {testing === "cloud" ? "测试中..." : "测试连接"}
              </button>
            </div>
          </fieldset>

          {/* 本地 Ollama */}
          <fieldset className="border border-gray-700 rounded-lg p-3">
            <legend className="text-xs text-gray-400 px-1">Ollama 本地</legend>
            <div className="space-y-2">
              <div>
                <label className="text-xs text-gray-500">Ollama 地址</label>
                <input
                  className="input text-sm"
                  value={config.ollama_url}
                  onChange={(e) => setConfig({ ...config, ollama_url: e.target.value })}
                  placeholder="http://localhost:11434"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">默认模型</label>
                <input
                  className="input text-sm"
                  value={config.ollama_model}
                  onChange={(e) => setConfig({ ...config, ollama_model: e.target.value })}
                  placeholder="qwen2.5:latest"
                />
              </div>
              <button
                type="button"
                onClick={() => handleTest("ollama")}
                disabled={testing !== null}
                className="text-xs px-3 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600 disabled:opacity-50"
              >
                {testing === "ollama" ? "测试中..." : "测试连接"}
              </button>
            </div>
          </fieldset>

          {/* 剧情选项生成 */}
          <fieldset className="border border-gray-700 rounded-lg p-3">
            <legend className="text-xs text-gray-400 px-1">剧情选项</legend>
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={config.auto_generate_choices}
                  onChange={(e) =>
                    setConfig({ ...config, auto_generate_choices: e.target.checked })
                  }
                  className="rounded"
                />
                启用 LLM 自动生成剧情选项
              </label>
              {config.auto_generate_choices && (
                <div className="flex items-center gap-2">
                  <label className="text-xs text-gray-500 shrink-0">生成选项个数</label>
                  <input
                    type="number"
                    min={1}
                    max={5}
                    value={config.choice_count}
                    onChange={(e) =>
                      setConfig({
                        ...config,
                        choice_count: Math.max(1, Math.min(5, parseInt(e.target.value) || 3)),
                      })
                    }
                    className="input text-sm w-20 text-center"
                  />
                  <span className="text-xs text-gray-500">（1-5）</span>
                </div>
              )}
            </div>
          </fieldset>

          {testResult && (
            <p className={`text-xs ${testResult.type === "ok" ? "text-green-300" : "text-red-400"}`}>
              {testResult.text}
            </p>
          )}
          {configMsg && (
            <p className={`text-xs ${configMsg.type === "ok" ? "text-green-300" : "text-red-400"}`}>
              {configMsg.text}
            </p>
          )}

          <button
            onClick={handleSaveConfig}
            disabled={saving || !configLoaded}
            className="btn-primary text-sm w-full"
          >
            {saving ? "保存中..." : "保存并重新检测"}
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
