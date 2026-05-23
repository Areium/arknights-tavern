/**
 * API 客户端 Hook — 封装所有后端调用
 *
 * 自动检测 Electron 环境（通过 preload）或纯浏览器环境。
 */

import { useMemo } from "react";

const FALLBACK_URL = "";

async function getBaseUrl(): Promise<string> {
  if (window.electronAPI) {
    return await window.electronAPI.getBackendUrl();
  }
  return FALLBACK_URL;
}

const REQUEST_TIMEOUT = 15000; // 15s

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const base = await getBaseUrl();
  const url = `${base}${path}`;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);

  try {
    const res = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
      signal: controller.signal,
      ...options,
    });

    if (!res.ok) {
      const body = await res.text();
      let message: string;
      try {
        message = JSON.parse(body).error || body;
      } catch {
        message = body;
      }
      throw new Error(message || `HTTP ${res.status}`);
    }

    return res.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

export function useApi() {
  return useMemo(() => ({
    // ── 状态 ──
    getStatus: () => request<any>("/api/status"),

    // ── 会话 ──
    listSessions: () => request<any[]>("/api/sessions"),
    listPlots: () => request<any[]>("/api/plots"),
    createSession: (mode: "free" | "story" = "free", name = "", plotId = "") =>
      request<any>("/api/sessions", {
        method: "POST",
        body: JSON.stringify({ mode, name, plot_id: plotId }),
      }),
    getSession: (id: string) => request<any>(`/api/sessions/${id}`),
    deleteSession: (id: string) =>
      request<any>(`/api/sessions/${id}`, { method: "DELETE" }),
    renameSession: (id: string, name: string) =>
      request<any>(`/api/sessions/${id}/rename`, {
        method: "PUT",
        body: JSON.stringify({ name }),
      }),

    // ── 场景角色 ──
    getSceneCharacters: (sessionId: string) =>
      request<any>(`/api/sessions/${sessionId}/characters`),
    loadCharacter: (sessionId: string, character: string) =>
      request<any>(`/api/sessions/${sessionId}/characters/load`, {
        method: "POST",
        body: JSON.stringify({ character }),
      }),
    unloadCharacter: (sessionId: string, character: string) =>
      request<any>(`/api/sessions/${sessionId}/characters/unload`, {
        method: "POST",
        body: JSON.stringify({ character }),
      }),
    switchCharacter: (sessionId: string, character: string) =>
      request<any>(`/api/sessions/${sessionId}/characters/switch`, {
        method: "POST",
        body: JSON.stringify({ character }),
      }),

    // ── 对话 ──
    chat: (sessionId: string, input: string, identity = "博士") =>
      request<any>(`/api/sessions/${sessionId}/chat`, {
        method: "POST",
        body: JSON.stringify({ input, identity }),
      }),
    groupChat: (sessionId: string, input: string, identity = "博士") =>
      request<any>(`/api/sessions/${sessionId}/group-chat`, {
        method: "POST",
        body: JSON.stringify({ input, identity }),
      }),
    narrateContinue: (sessionId: string, identity = "博士", action = "") =>
      request<any>(`/api/sessions/${sessionId}/narrate-continue`, {
        method: "POST",
        body: JSON.stringify({ identity, action }),
      }),
    narrateVariant: (sessionId: string, prompt: string, identity = "博士") =>
      request<any>(`/api/sessions/${sessionId}/narrate-variant`, {
        method: "POST",
        body: JSON.stringify({ identity, prompt }),
      }),
    narrateUpdate: (sessionId: string, round: number, narrative: string) =>
      request<any>(`/api/sessions/${sessionId}/narrate-update`, {
        method: "POST",
        body: JSON.stringify({ round, narrative }),
      }),

    // ── 环境 ──
    getEnvironment: (sessionId: string) =>
      request<any>(`/api/sessions/${sessionId}/environment`),
    updateEnvironment: (
      sessionId: string,
      data: { location?: string; weather?: string; time?: string }
    ) =>
      request<any>(`/api/sessions/${sessionId}/environment`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    getEnvironmentPresets: () =>
      request<{
        locations: { name: string; region: string; summary: string; tags: string[] }[];
        weathers: { name: string; id: string; icon: string; category: string }[];
        times: string[];
      }>("/api/environment/presets"),

    getMemories: (sessionId: string) =>
      request<{
        memories: { id: string; title: string; summary: string; round_start: number; round_end: number; created_at: number }[];
        narration_count: number;
        last_memory_end: number;
      }>(`/api/sessions/${sessionId}/memories`),
    regenerateMemories: (sessionId: string) =>
      request<{
        memories: { id: string; title: string; summary: string; round_start: number; round_end: number; created_at: number }[];
        narration_count: number;
      }>(`/api/sessions/${sessionId}/memories/regenerate`, { method: "POST" }),
    rollbackSession: (sessionId: string, round: number) =>
      request<{
        target_round: number;
        narration_count: number;
        deleted_rounds: number;
        deleted_memories: number;
        memories: any[];
      }>(`/api/sessions/${sessionId}/rollback`, {
        method: "POST",
        body: JSON.stringify({ round }),
      }),

    // ── 文档 ──
    getDocumentTree: () => request<any[]>("/api/documents/tree"),
    getDocumentCategories: () => request<any[]>("/api/documents/categories"),
    listDocuments: (category: string) =>
      request<any[]>(`/api/documents/${category}`),
    readDocument: (category: string, id: string) =>
      request<any>(`/api/documents/${category}/${encodeURIComponent(id)}`),
    saveDocument: (
      category: string,
      id: string,
      content: string,
      metadata?: Record<string, any>,
      expectedHash?: string
    ) =>
      request<any>(`/api/documents/${category}/${encodeURIComponent(id)}`, {
        method: "PUT",
        body: JSON.stringify({
          content,
          metadata,
          expected_hash: expectedHash,
        }),
      }),

    // ── 资产（图像等）──
    getAssetImages: () => request<any[]>("/api/assets/images"),
    getDataDir: () => request<{ path: string }>("/api/assets/data-dir"),

    // ── LLM ──
    getLLMStatus: () => request<any>("/api/llm/status"),
    refreshLLM: () =>
      request<any>("/api/llm/refresh", { method: "POST" }),
    switchLLM: (endpointId: string) =>
      request<any>("/api/llm/switch", {
        method: "POST",
        body: JSON.stringify({ endpoint: endpointId }),
      }),
    getLLMConfig: () => request<any>("/api/llm/config"),
    updateLLMConfig: (config: Record<string, any>) =>
      request<any>("/api/llm/config", {
        method: "PUT",
        body: JSON.stringify(config),
      }),
    testLLMConnection: (type: "cloud" | "ollama", params: Record<string, string>) =>
      request<any>("/api/llm/test", {
        method: "POST",
        body: JSON.stringify({ type, ...params }),
      }),

    // ── 角色库 ──
    getCharacters: () => request<any[]>("/api/characters"),
    getCharacter: (id: string) => request<any>(`/api/characters/${encodeURIComponent(id)}`),

    // ── 物品库 ──
    getItems: () => request<any[]>("/api/items"),
    getItem: (id: string) => request<any>(`/api/items/${encodeURIComponent(id)}`),
    getSceneItems: (sessionId: string) =>
      request<any>(`/api/sessions/${sessionId}/items`),
    addSceneItem: (sessionId: string, itemId: string) =>
      request<any>(`/api/sessions/${sessionId}/items/add`, {
        method: "POST",
        body: JSON.stringify({ item_id: itemId }),
      }),
    removeSceneItem: (sessionId: string, itemId: string) =>
      request<any>(`/api/sessions/${sessionId}/items/remove`, {
        method: "POST",
        body: JSON.stringify({ item_id: itemId }),
      }),

    // ── 任务系统 ──
    getQuests: (sessionId: string) =>
      request<{ plot_id: string | null; quests: any[] }>(
        `/api/sessions/${sessionId}/quests`
      ),
    loadQuests: (sessionId: string, plotId: string) =>
      request<{ plot_id: string; quests: any[] }>(
        `/api/sessions/${sessionId}/quests/load`,
        { method: "PUT", body: JSON.stringify({ plot_id: plotId }) }
      ),
    updateQuestState: (sessionId: string, questId: string, status: string) =>
      request<{ quest_id: string; status: string }>(
        `/api/sessions/${sessionId}/quests/${encodeURIComponent(questId)}`,
        { method: "PATCH", body: JSON.stringify({ status }) }
      ),

    // ── 会话覆盖 ──
    getOverrides: (sessionId: string) =>
      request<any>(`/api/sessions/${sessionId}/overrides`),
    getCharacterMerged: (sessionId: string, name: string) =>
      request<any>(`/api/sessions/${sessionId}/overrides/characters/${encodeURIComponent(name)}`),
    setCharacterOverride: (sessionId: string, name: string, overrides: Record<string, any>) =>
      request<any>(`/api/sessions/${sessionId}/overrides/characters/${encodeURIComponent(name)}`, {
        method: "PUT",
        body: JSON.stringify(overrides),
      }),
    deleteCharacterOverride: (sessionId: string, name: string) =>
      request<any>(`/api/sessions/${sessionId}/overrides/characters/${encodeURIComponent(name)}`, {
        method: "DELETE",
      }),
    getItemMerged: (sessionId: string, itemId: string) =>
      request<any>(`/api/sessions/${sessionId}/overrides/items/${encodeURIComponent(itemId)}`),
    setItemOverride: (sessionId: string, itemId: string, overrides: Record<string, any>) =>
      request<any>(`/api/sessions/${sessionId}/overrides/items/${encodeURIComponent(itemId)}`, {
        method: "PUT",
        body: JSON.stringify(overrides),
      }),
    deleteItemOverride: (sessionId: string, itemId: string) =>
      request<any>(`/api/sessions/${sessionId}/overrides/items/${encodeURIComponent(itemId)}`, {
        method: "DELETE",
      }),

    // ── 文档创建 ──
    createDocument: (
      category: string,
      id: string,
      content: string = "",
      metadata?: Record<string, any>
    ) =>
      request<any>(`/api/documents/${category}`, {
        method: "POST",
        body: JSON.stringify({ id, content, metadata }),
      }),

    // ── 文档删除 ──
    deleteDocument: (category: string, id: string) =>
      request<any>(`/api/documents/${category}/${encodeURIComponent(id)}`, {
        method: "DELETE",
      }),

    // ── 文件夹操作 ──
    createFolder: (category: string, path: string) =>
      request<any>(`/api/documents/${category}/folders`, {
        method: "POST",
        body: JSON.stringify({ path }),
      }),

    deleteFolder: (category: string, path: string) =>
      request<any>(
        `/api/documents/${category}/folders/${encodeURIComponent(path)}`,
        { method: "DELETE" }
      ),

    // ── 移动/重命名 ──
    moveDocument: (category: string, id: string, newPath: string) =>
      request<any>(`/api/documents/${category}/${encodeURIComponent(id)}/move`, {
        method: "POST",
        body: JSON.stringify({ new_path: newPath }),
      }),

    moveFolder: (category: string, path: string, newPath: string) =>
      request<any>(
        `/api/documents/${category}/folders/${encodeURIComponent(path)}/move`,
        {
          method: "POST",
          body: JSON.stringify({ new_path: newPath }),
        }
      ),

    // ── Combat ──
    combatStart: (sessionId: string, encounterId: string, characters: string[]) =>
      request<any>(`/api/sessions/${sessionId}/combat/start`, {
        method: "POST",
        body: JSON.stringify({ encounter_id: encounterId, characters }),
      }),

    combatState: (sessionId: string) =>
      request<any>(`/api/sessions/${sessionId}/combat/state`),

    combatAction: (sessionId: string, action: { action: string; card_index?: number; target: [number, number] }) =>
      request<any>(`/api/sessions/${sessionId}/combat/action`, {
        method: "POST",
        body: JSON.stringify(action),
      }),

    combatEndTurn: (sessionId: string) =>
      request<any>(`/api/sessions/${sessionId}/combat/end-turn`, {
        method: "POST",
      }),

    combatComplete: (sessionId: string, data: {
      encounter_id: string;
      winner: string;
      survivors: string[];
      rounds: number;
      character_stats: Record<string, any>;
    }) =>
      request<any>(`/api/sessions/${sessionId}/combat/complete`, {
        method: "POST",
        body: JSON.stringify(data),
      }),

    // ── Combat Test (no session required) ──
    combatTestStart: (encounterId?: string) =>
      request<{ test_id: string; state: any }>("/api/combat/test/start", {
        method: "POST",
        body: JSON.stringify(encounterId ? { encounter_id: encounterId } : {}),
      }),

    combatTestState: (testId: string) =>
      request<any>(`/api/combat/test/${testId}/state`),

    combatTestAction: (testId: string, action: { action: string; card_index?: number; target: [number, number] }) =>
      request<any>(`/api/combat/test/${testId}/action`, {
        method: "POST",
        body: JSON.stringify(action),
      }),

    combatTestEndTurn: (testId: string) =>
      request<any>(`/api/combat/test/${testId}/end-turn`, {
        method: "POST",
      }),
  }), []);
}

/**
 * 创建 GET SSE 连接
 */
export function createSSE(
  path: string,
  handlers: {
    onText?: (token: string) => void;
    onSceneEvent?: (event: any) => void;
    onMemoryEvent?: (event: any) => void;
    onChoice?: (options: string[]) => void;
    onError?: (message: string) => void;
    onDone?: () => void;
  }
): { close: () => void } {
  return connectSSE(path, "GET", undefined, handlers);
}

/**
 * 创建 POST SSE 连接 — 发送 JSON body，以流式读取 SSE 响应
 */
export function createPostSSE(
  path: string,
  body: Record<string, any>,
  handlers: {
    onText?: (token: string) => void;
    onSceneEvent?: (event: any) => void;
    onMemoryEvent?: (event: any) => void;
    onChoice?: (options: string[]) => void;
    onError?: (message: string) => void;
    onDone?: () => void;
  }
): { close: () => void } {
  return connectSSE(path, "POST", body, handlers);
}

/**
 * 创建战斗 SSE 连接
 */
export function createCombatSSE(
  sessionId: string,
  handlers: {
    onEvent?: (event: { type: string; data: Record<string, any> }) => void;
    onError?: (message: string) => void;
    onDone?: () => void;
  }
): { close: () => void } {
  const path = `/api/sessions/${sessionId}/combat/events`;
  return connectCombatSSE(path, handlers);
}

/**
 * 创建战斗测试 SSE 连接
 */
export function createCombatTestSSE(
  testId: string,
  handlers: {
    onEvent?: (event: { type: string; data: Record<string, any> }) => void;
    onError?: (message: string) => void;
    onDone?: () => void;
  }
): { close: () => void } {
  const path = `/api/combat/test/${testId}/events`;
  return connectCombatSSE(path, handlers);
}

function connectCombatSSE(
  path: string,
  handlers: {
    onEvent?: (event: { type: string; data: Record<string, any> }) => void;
    onError?: (message: string) => void;
    onDone?: () => void;
  }
): { close: () => void } {
  let closed = false;

  async function connect() {
    const base = await getBaseUrl();
    const url = `${base}${path}`;

    try {
      const res = await fetch(url, {
        headers: { "Accept": "text/event-stream" },
      });

      if (!res.ok) {
        handlers.onError?.(`SSE error: ${res.status}`);
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let buffer = "";

      while (!closed) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const eventData = JSON.parse(line.slice(6));
              if (eventData.type === "done") {
                handlers.onDone?.();
                closed = true;
                return;
              } else if (eventData.type === "error") {
                handlers.onError?.(eventData.data?.message || "Unknown error");
              } else if (eventData.type !== "heartbeat") {
                handlers.onEvent?.(eventData);
              }
            } catch {
              // skip parse errors
            }
          }
        }
      }
    } catch (err: any) {
      if (!closed) {
        handlers.onError?.(err.message || "SSE connection failed");
      }
    }
  }

  connect();

  return {
    close: () => {
      closed = true;
    },
  };
}

function connectSSE(
  path: string,
  method: "GET" | "POST",
  body: Record<string, any> | undefined,
  handlers: {
    onText?: (token: string) => void;
    onSceneEvent?: (event: any) => void;
    onMemoryEvent?: (event: any) => void;
    onChoice?: (options: string[]) => void;
    onError?: (message: string) => void;
    onDone?: () => void;
  }
): { close: () => void } {
  let closed = false;

  async function connect() {
    const base = await getBaseUrl();
    const url = `${base}${path}`;
    const controller = new AbortController();

    try {
      const init: RequestInit = {
        method,
        headers: { Accept: "text/event-stream" },
        signal: controller.signal,
      };
      if (body) {
        (init.headers as Record<string, string>)["Content-Type"] = "application/json";
        init.body = JSON.stringify(body);
      }

      const response = await fetch(url, init);

      if (!response.ok) {
        const text = await response.text();
        let msg = text;
        try { msg = JSON.parse(text).error || text; } catch {}
        handlers.onError?.(msg);
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No reader");

      const decoder = new TextDecoder();
      let buffer = "";

      while (!closed) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const jsonStr = line.slice(6);
          if (jsonStr.trim() === "[DONE]") {
            handlers.onDone?.();
            continue;
          }

          try {
            const event = JSON.parse(jsonStr);
            switch (event.type) {
              case "text":
                handlers.onText?.(event.data.token);
                break;
              case "scene_event":
                handlers.onSceneEvent?.(event.data);
                break;
              case "memory_event":
                handlers.onMemoryEvent?.(event.data);
                break;
              case "choice":
                handlers.onChoice?.(event.data.options);
                break;
              case "error":
                handlers.onError?.(event.data.message);
                break;
              case "done":
                handlers.onDone?.();
                break;
            }
          } catch {}
        }
      }
    } catch (err: any) {
      if (!closed) {
        handlers.onError?.(err.message);
      }
    }
  }

  connect();

  return {
    close: () => {
      closed = true;
    },
  };
}
