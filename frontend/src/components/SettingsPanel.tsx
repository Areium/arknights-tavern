import { useState, useEffect, useCallback } from "react";
import { audioManager } from "../audio/audioManager";
import { useAppStore, type SkinId } from "../stores/appStore";
import { useApi } from "../hooks/useApi";

/** 皮肤清单：id 与后端 config.skin 白名单一致；swatch 用真实色值（行内样式），
    保证在任意皮肤下都能看到各皮肤本来的配色。 */
const SKINS: { id: SkinId; name: string; desc: string; swatch: string[] }[] = [
  {
    id: "default",
    name: "默认",
    desc: "现有界面，可自由切换明暗",
    swatch: ["#0f1117", "#1a1d27", "#f59e0b"],
  },
  {
    id: "prts",
    name: "PRTS 全息终端",
    desc: "深空底 · 全息青 · 静态扫描线",
    swatch: ["#04070d", "#0b1524", "#38bdf8", "#f0c060"],
  },
  {
    id: "tavern",
    name: "酒馆手札",
    desc: "羊皮纸 · 墨水棕 · 火漆红",
    swatch: ["#ece1c9", "#fbf6e9", "#a03d2d", "#e8a33d"],
  },
];

export default function SettingsPanel() {
  const { llmStatus, theme, toggleTheme, skin, setSkin, setEditBeforeSend, setDialogueBubbleMode } = useAppStore();
  const api = useApi();
  const [switching, setSwitching] = useState<string | null>(null);
  const [bgmMuteOnBlur, setBgmMuteOnBlurState] = useState(audioManager.getSettings().bgmMuteOnBlur);
  const [bgmVol, setBgmVolState] = useState(audioManager.getSettings().bgmVolume);
  const [sfxVol, setSfxVolState] = useState(audioManager.getSettings().sfxVolume);
  const [muted, setMutedState] = useState(audioManager.getSettings().muted);

  // LLM 配置表单
  const [config, setConfig] = useState({
    api_key: "",
    base_url: "",
    cloud_model: "",
    ollama_url: "",
    ollama_model: "",
    provider: "auto",
    enable_thinking: false,
    reasoning_effort: "medium",
    narration_reasoning_effort: "none",
    auto_generate_choices: false,
    choice_count: 3,
    memory_interval: 5,
    max_output_tokens: 16384,
    word_limit: 500,
    edit_before_send: false,
    dialogue_bubble_mode: false,
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
        provider: data.provider || "auto",
        enable_thinking: data.enable_thinking || false,
        reasoning_effort: data.reasoning_effort || "medium",
        narration_reasoning_effort: data.narration_reasoning_effort || "none",
        auto_generate_choices: data.auto_generate_choices || false,
        choice_count: data.choice_count || 3,
        memory_interval: data.memory_interval || 5,
        max_output_tokens: data.max_output_tokens ?? 16384,
        word_limit: data.word_limit ?? 500,
        edit_before_send: data.edit_before_send ?? false,
        dialogue_bubble_mode: data.dialogue_bubble_mode ?? false,
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
        provider: config.provider,
        enable_thinking: config.enable_thinking,
        reasoning_effort: config.reasoning_effort,
        narration_reasoning_effort: config.narration_reasoning_effort,
        auto_generate_choices: config.auto_generate_choices,
        choice_count: config.choice_count,
        memory_interval: config.memory_interval,
        max_output_tokens: config.max_output_tokens,
        word_limit: config.word_limit,
        edit_before_send: config.edit_before_send,
        dialogue_bubble_mode: config.dialogue_bubble_mode,
      });
      await api.refreshLLM();
      setEditBeforeSend(config.edit_before_send);
      setDialogueBubbleMode(config.dialogue_bubble_mode);
      setConfigMsg({ type: "ok", text: "配置已保存" });
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

  const handleSkinChange = async (next: SkinId) => {
    if (next === skin) return;
    setSkin(next); // 立即更新 UI
    // 异步持久化到后端配置文件（静默，与 handleToggleTheme 一致）
    try {
      await api.updateLLMConfig({ skin: next });
    } catch {
      /* 非关键 */
    }
  };

  const handleToggleBgmMuteOnBlur = () => {
    const v = !bgmMuteOnBlur;
    setBgmMuteOnBlurState(v);
    audioManager.setBgmMuteOnBlur(v);
  };

  const handleBgmVol = (v: number) => { setBgmVolState(v); audioManager.setBgmVolume(v); };
  const handleSfxVol = (v: number) => { setSfxVolState(v); audioManager.setSfxVolume(v); };
  const handleToggleMuted = () => {
    const m = !muted;
    setMutedState(m);
    audioManager.setMuted(m);
    if (!m) audioManager.resumeMenuBgmAfterUnmute();
  };

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <h2 className="text-lg font-bold">设置</h2>

      {/* 主题切换 */}
      <section className="card">
        <h3 className="panel-title">外观</h3>

        {/* 皮肤选择 */}
        <div>
          <p className="text-sm font-medium">界面皮肤</p>
          <p className="text-xs text-gray-500 mt-0.5 mb-3">
            皮肤自带完整色板；激活后明暗开关交由皮肤接管
          </p>
          <div className="grid grid-cols-3 gap-2">
            {SKINS.map((s) => {
              const active = skin === s.id;
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => handleSkinChange(s.id)}
                  aria-pressed={active}
                  title={s.desc}
                  className={`text-left rounded-lg border p-2.5 transition-colors ${
                    active
                      ? "border-amber-500 bg-amber-500/20"
                      : "border-gray-700 bg-gray-800/50 hover:border-gray-600"
                  }`}
                >
                  {/* 色板条（真实色值，不随皮肤变化） */}
                  <div className="flex h-4 rounded overflow-hidden mb-2">
                    {s.swatch.map((c) => (
                      <div key={c} className="flex-1" style={{ backgroundColor: c }} />
                    ))}
                  </div>
                  <p className="text-xs font-semibold">{s.name}</p>
                  <p className="text-[10px] text-gray-500 mt-0.5 leading-snug">{s.desc}</p>
                </button>
              );
            })}
          </div>
        </div>

        {/* 明暗切换：皮肤激活时置灰 */}
        <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-700">
          <div>
            <p className="text-sm font-medium">
              {skin !== "default"
                ? "明暗模式（由皮肤接管）"
                : theme === "dark"
                  ? "深色模式"
                  : "浅色模式"}
            </p>
            <p className="text-xs text-gray-500 mt-0.5">
              {skin !== "default"
                ? "当前皮肤自带完整色板，如需切换明暗请先选回「默认」"
                : theme === "dark"
                  ? "护眼暗色界面"
                  : "明亮清晰界面"}
            </p>
          </div>
          <button
            onClick={handleToggleTheme}
            disabled={skin !== "default"}
            aria-disabled={skin !== "default"}
            title={skin !== "default" ? "皮肤激活时明暗开关不可用" : undefined}
            className={`relative w-12 h-6 rounded-full transition-colors duration-200 ${
              skin !== "default"
                ? "bg-gray-600 opacity-50 cursor-not-allowed"
                : theme === "dark"
                  ? "bg-blue-600"
                  : "bg-gray-300"
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

      {/* 音频 */}
      <section className="card">
        <h3 className="panel-title">音频</h3>
        <div className="space-y-5">
          {/* BGM 音量 */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <p className="text-sm font-medium">背景音乐音量</p>
              <span className="text-xs text-gray-500">{Math.round(bgmVol * 100)}%</span>
            </div>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={bgmVol}
              onChange={(e) => handleBgmVol(parseFloat(e.target.value))}
              className="w-full accent-amber-500 cursor-pointer"
            />
          </div>
          {/* SFX 音量 */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <p className="text-sm font-medium">音效音量（战斗/UI）</p>
              <span className="text-xs text-gray-500">{Math.round(sfxVol * 100)}%</span>
            </div>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={sfxVol}
              onChange={(e) => handleSfxVol(parseFloat(e.target.value))}
              className="w-full accent-blue-500 cursor-pointer"
            />
          </div>
          {/* 静音开关 */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">静音</p>
              <p className="text-xs text-gray-500 mt-0.5">暂停全部声音（BGM 记住进度，再次点击继续播放）</p>
            </div>
            <button
              onClick={handleToggleMuted}
              className={`relative w-12 h-6 rounded-full transition-colors duration-200 ${
                muted ? "bg-blue-600" : "bg-gray-300"
              }`}
            >
              <span
                className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform duration-200 ${
                  muted ? "left-6" : "left-0.5"
                }`}
              />
            </button>
          </div>
          {/* 失焦暂停 */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">窗口失焦时暂停 BGM</p>
              <p className="text-xs text-gray-500 mt-0.5">切到其他窗口/程序时暂停背景音乐，回来自动恢复</p>
            </div>
            <button
              onClick={handleToggleBgmMuteOnBlur}
              className={`relative w-12 h-6 rounded-full transition-colors duration-200 ${
                bgmMuteOnBlur ? "bg-blue-600" : "bg-gray-300"
              }`}
            >
              <span
                className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform duration-200 ${
                  bgmMuteOnBlur ? "left-6" : "left-0.5"
                }`}
              />
            </button>
          </div>
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
                <label className="text-xs text-gray-500">接口类型</label>
                <select
                  className="input text-sm"
                  value={config.provider}
                  onChange={(e) => setConfig({ ...config, provider: e.target.value })}
                >
                  <option value="auto">自动（OpenAI 兼容）</option>
                  <option value="openai">OpenAI</option>
                  <option value="deepseek">DeepSeek</option>
                  <option value="anthropic">Anthropic（开发中）</option>
                  <option value="gemini">Gemini（开发中）</option>
                </select>
              </div>
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
              {["auto", "openai", "deepseek"].includes(config.provider) && (
                <div className="space-y-2">
                  <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={config.enable_thinking}
                      onChange={(e) =>
                        setConfig({ ...config, enable_thinking: e.target.checked })
                      }
                      className="rounded"
                    />
                    启用思考模式
                  </label>
                  {config.enable_thinking && (
                    <div className="flex items-center gap-2 ml-6">
                      <label className="text-xs text-gray-500 shrink-0">推理强度</label>
                      <select
                        className="input text-sm"
                        value={config.reasoning_effort}
                        onChange={(e) =>
                          setConfig({ ...config, reasoning_effort: e.target.value })
                        }
                      >
                        <option value="low">低（快速）</option>
                        <option value="medium">中（均衡）</option>
                        <option value="high">高（深度）</option>
                      </select>
                    </div>
                  )}
                    <div className="flex items-center gap-2 ml-6">
                      <label className="text-xs text-gray-500 shrink-0">叙述思考档位</label>
                      <select
                        className="input text-sm"
                        value={config.narration_reasoning_effort}
                        onChange={(e) =>
                          setConfig({ ...config, narration_reasoning_effort: e.target.value })
                        }
                      >
                        <option value="none">关闭（最快）</option>
                        <option value="low">低（快速）</option>
                        <option value="medium">中（均衡）</option>
                        <option value="high">高（深度）</option>
                      </select>
                    </div>
                    <p className="text-xs text-gray-500 ml-6">作用于剧情叙述与角色对话；选项/回忆等分类任务始终关闭思考。</p>
                </div>
              )}
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
              <div className="flex items-center gap-2 mt-2">
                <label className="text-xs text-gray-500 shrink-0">回忆间隔</label>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={config.memory_interval}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      memory_interval: Math.max(1, Math.min(20, parseInt(e.target.value) || 5)),
                    })
                  }
                  className="input text-sm w-20 text-center"
                />
                <span className="text-xs text-gray-500">轮（1-20）</span>
              </div>
              <p className="text-xs text-gray-600 mt-1">
                每隔这么多轮对话自动生成一次剧情回忆
              </p>
              <div className="flex items-center gap-2 mt-2">
                <label className="text-xs text-gray-500 shrink-0">输出上限</label>
                <input
                  type="number"
                  min={256}
                  max={32768}
                  step={256}
                  value={config.max_output_tokens}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      max_output_tokens: Math.max(256, Math.min(32768, parseInt(e.target.value) || 16384)),
                    })
                  }
                  className="input text-sm w-24 text-center"
                />
                <span className="text-xs text-gray-500">token（256-32768）</span>
              </div>
              <p className="text-xs text-gray-600 mt-1">
                API 硬上限：模型输出超过此 token 数时强制截断
              </p>
              <div className="flex items-center gap-2 mt-2">
                <label className="text-xs text-gray-500 shrink-0">每轮字数</label>
                <input
                  type="number"
                  min={100}
                  max={3000}
                  step={100}
                  value={config.word_limit}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      word_limit: Math.max(100, Math.min(3000, parseInt(e.target.value) || 500)),
                    })
                  }
                  className="input text-sm w-24 text-center"
                />
                <span className="text-xs text-gray-500">字（100-3000）</span>
              </div>
              <p className="text-xs text-gray-600 mt-1">
                每轮叙述/角色回复的目标字数上限，提示词与输出 token 预算都会按此约束
              </p>
              <div className="border-t border-gray-700/50 pt-2 mt-2">
                <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={config.edit_before_send}
                    onChange={(e) =>
                      setConfig({ ...config, edit_before_send: e.target.checked })
                    }
                    className="rounded"
                  />
                  选项填充到输入框（可编辑后再发送）
                </label>
                <p className="text-xs text-gray-600 mt-0.5 ml-6">
                  开启后点击选项将填入输入框而非直接发送，关闭则立即发送
                </p>
              </div>
              <div className="border-t border-gray-700/50 pt-2 mt-2">
                <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={config.dialogue_bubble_mode}
                    onChange={(e) =>
                      setConfig({ ...config, dialogue_bubble_mode: e.target.checked })
                    }
                    className="rounded"
                  />
                  对话气泡模式
                </label>
                <p className="text-xs text-gray-600 mt-0.5 ml-6">
                  将角色对话以头像 + 聊天气泡形式展示，叙述文字保持原样
                </p>
              </div>
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
            {saving ? "保存中..." : "保存配置"}
          </button>
        </div>
      </section>

      {/* 关于 */}
      <section className="card">
        <h3 className="panel-title">关于</h3>
        <div className="text-sm text-gray-400 space-y-1">
          <p>Arknights Tavern v0.1.0</p>
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
