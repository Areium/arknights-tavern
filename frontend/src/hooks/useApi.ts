/**
 * API 客户端 Hook — 封装所有后端调用
 *
 * 自动检测 Electron 环境（通过 preload）或纯浏览器环境。
 */

import { useMemo } from "react";
import { getBaseUrl } from "../utils/baseUrl";

async function uploadMultipart(path: string, fields: Record<string, string>, file: File): Promise<any> {
  const base = await getBaseUrl();
  const formData = new FormData();
  for (const [k, v] of Object.entries(fields)) formData.append(k, v);
  formData.append("file", file);
  const res = await fetch(`${base}${path}`, { method: "POST", body: formData });
  if (!res.ok) {
    const body = await res.text();
    let message: string;
    try { message = JSON.parse(body).error || body; } catch { message = body; }
    throw new Error(message || `HTTP ${res.status}`);
  }
  return res.json();
}

const REQUEST_TIMEOUT = 60000; // 60s — needs headroom for dual LLM calls (narrate + dialogue restructure)

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
      const err = new Error(message || `HTTP ${res.status}`) as Error & { status?: number };
      err.status = res.status;
      throw err;
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
    createSession: (mode: "free" | "story" = "free", name = "", plotId = "",
      combatMode: "narrative" | "tactical" = "narrative", identity = "博士") =>
      request<any>("/api/sessions", {
        method: "POST",
        body: JSON.stringify({ mode, name, plot_id: plotId, combat_mode: combatMode, identity }),
      }),
    getSession: (id: string) => request<any>(`/api/sessions/${id}`),
    deleteSession: (id: string) =>
      request<any>(`/api/sessions/${id}`, { method: "DELETE" }),
    renameSession: (id: string, name: string) =>
      request<any>(`/api/sessions/${id}/rename`, {
        method: "PUT",
        body: JSON.stringify({ name }),
      }),
    saveCustomPrompt: (id: string, prompt: string) =>
      request<any>(`/api/sessions/${id}/custom-prompt`, {
        method: "PUT",
        body: JSON.stringify({ prompt }),
      }),

    // ── 会话资源空间（背景覆盖 + 角色形象覆盖 + 文档副本） ──
    getSessionResources: (sessionId: string) =>
      request<import("../types").SessionResourcesDTO>(`/api/sessions/${sessionId}/resources`),
    uploadSessionBackground: (sessionId: string, bgId: string, file: File) =>
      uploadMultipart(`/api/sessions/${sessionId}/resources/backgrounds`, { bg_id: bgId }, file),
    deleteSessionBackground: (sessionId: string, bgId: string) =>
      request<any>(`/api/sessions/${sessionId}/resources/backgrounds/${encodeURIComponent(bgId)}`, { method: "DELETE" }),
    uploadSessionCharacterMedia: (sessionId: string, name: string, mediaType: string, file: File) =>
      uploadMultipart(`/api/sessions/${sessionId}/resources/characters/${encodeURIComponent(name)}/${mediaType}`, {}, file),
    deleteSessionCharacterMedia: (sessionId: string, name: string, mediaType: string) =>
      request<any>(`/api/sessions/${sessionId}/resources/characters/${encodeURIComponent(name)}/${mediaType}`, { method: "DELETE" }),
    exportSession: async (sessionId: string) => {
      // 导出会话存档 zip 并触发浏览器下载
      const base = await getBaseUrl();
      const res = await fetch(`${base}/api/sessions/${sessionId}/export`);
      if (!res.ok) {
        const body = await res.text();
        let message: string;
        try { message = JSON.parse(body).error || body; } catch { message = body; }
        throw new Error(message || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition") || "";
      const m = disposition.match(/filename="?([^";]+)"?/i);
      const filename = m?.[1] || `session-${sessionId}.zip`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    },
    importSession: (file: File) =>
      uploadMultipart("/api/sessions/import", {}, file),

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
    getDocumentCategories: () => request<{ categories: any[]; hierarchy: { level: number; label: string; categories: string[] }[] }>("/api/documents/categories"),
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

    // ── 索引管理 ──
    getEntities: (categories?: string[]) => {
      const params = categories?.length ? `?categories=${categories.join(",")}` : "";
      return request<any>(`/api/entities${params}`);
    },

    // ── 文档依赖导入 ──
    searchDocuments: async (q: string, category?: string, docId?: string) => {
      const params = new URLSearchParams({ q });
      if (category) params.set("category", category);
      if (docId) params.set("exclude_doc_id", docId);
      const data = await request<{ results: any[]; total: number }>(`/api/documents/search?${params.toString()}`);
      return data.results || [];
    },
    getDocImports: (category: string, id: string) =>
      request<{ imports: { path: string; name: string }[] }>(`/api/documents/${category}/${encodeURIComponent(id)}/imports`),
    updateDocImports: (category: string, id: string, imports: string[]) =>
      request<{ imports: { path: string; name: string }[] }>(`/api/documents/${category}/${encodeURIComponent(id)}/imports`, {
        method: "PUT",
        body: JSON.stringify({ imports }),
      }),
    scanDocImports: (category: string, id: string) =>
      request<{ suggestions: any[]; existing: any[] }>(`/api/documents/${category}/${encodeURIComponent(id)}/imports/scan`, {
        method: "POST",
      }),
    verifyDocImports: (category: string, id: string) =>
      request<{ total: number; valid: number; invalid: number; results: { path: string; valid: boolean; category?: string; id?: string; error?: string }[] }>(`/api/documents/${category}/${encodeURIComponent(id)}/imports/verify`),

    getAssetImages: () => request<any[]>("/api/assets/images"),
    getDataDir: () => request<{ path: string }>("/api/assets/data-dir"),

    uploadAssetImage: async (category: string, file: File, subdir?: string) => {
      const base = await getBaseUrl();
      const formData = new FormData();
      formData.append("file", file);
      if (subdir) formData.append("subdir", subdir);
      const res = await fetch(`${base}/api/assets/${category}/upload`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const body = await res.text();
        let message = body;
        try { message = JSON.parse(body).error || body; } catch {}
        throw new Error(message);
      }
      return res.json();
    },
    deleteAssetImage: (category: string, filePath: string) =>
      request<any>(`/api/assets/${category}/${encodeURIComponent(filePath)}`, {
        method: "DELETE",
      }),
    getDefaultImage: (category: string, entity: string) =>
      request<{ default_avatar: string; default_skin: string; card_face: string; card_face_crop: import("../types").SkinCrop | null }>(`/api/assets/${category}/${encodeURIComponent(entity)}/default-image`),
    setDefaultImage: (category: string, entity: string, type: "avatar" | "skin" | "card_face", filename: string, crop?: import("../types").SkinCrop | null) =>
      request<any>(`/api/assets/${category}/${encodeURIComponent(entity)}/default-image`, {
        method: "PUT",
        body: JSON.stringify({ type, filename, ...(crop !== undefined ? { crop } : {}) }),
      }),
    getCardFaceCrop: (name: string) =>
      request<import("../types").SkinCrop | null>(`/api/characters/${encodeURIComponent(name)}/card-face-crop`),

    // ── 索引管理（基于 imports 的新系统） ──
    getIndexOverview: () =>
      request<import("../types").IndexOverview>("/api/index/overview"),
    getSessionIndexConfig: (sessionId: string) =>
      request<import("../types").SessionIndexConfig>(`/api/sessions/${sessionId}/index-config`),
    saveSessionIndexConfig: (sessionId: string, config: import("../types").SessionIndexConfig) =>
      request<any>(`/api/sessions/${sessionId}/index-config`, {
        method: "PUT",
        body: JSON.stringify(config),
      }),
    resetSessionIndexConfig: (sessionId: string) =>
      request<any>(`/api/sessions/${sessionId}/index-config`, {
        method: "DELETE",
      }),
    exportIndexYaml: () => request<{ yaml: string }>("/api/index/export"),
    importIndexYaml: (yaml: string) =>
      request<any>("/api/index/import", {
        method: "POST",
        body: JSON.stringify({ yaml }),
      }),
    verifyIndex: () =>
      request<import("../types").IndexVerifyResult>("/api/index/verify"),
    verifySessionIndex: (sessionId: string) =>
      request<import("../types").IndexVerifyResult>(`/api/sessions/${sessionId}/index/verify`),

    // ── 世界书（酒馆 Lorebook 兼容） ──
    listWorldbooks: () =>
      request<{ books: import("../types").WorldBookSummary[] }>("/api/worldbook"),
    createWorldbook: (name: string, budgetTokens = 0) =>
      request<{ book: import("../types").WorldBookSummary }>("/api/worldbook", {
        method: "POST",
        body: JSON.stringify({ name, budget_tokens: budgetTokens }),
      }),
    getWorldbook: (id: string) =>
      request<import("../types").WorldBookDetail>(`/api/worldbook/${encodeURIComponent(id)}`),
    updateWorldbook: (id: string, data: { name?: string; budget_tokens?: number; enabled?: boolean }) =>
      request<{ book: import("../types").WorldBookSummary }>(`/api/worldbook/${encodeURIComponent(id)}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    deleteWorldbook: (id: string) =>
      request<any>(`/api/worldbook/${encodeURIComponent(id)}`, { method: "DELETE" }),
    duplicateWorldbook: (id: string, name?: string) =>
      request<{ book: import("../types").WorldBookSummary }>(
        `/api/worldbook/${encodeURIComponent(id)}/duplicate`, {
          method: "POST",
          body: JSON.stringify({ name: name || "" }),
        }),
    reinstallWorldbook: (id: string) =>
      request<{ book: import("../types").WorldBookSummary }>(
        `/api/worldbook/${encodeURIComponent(id)}/reinstall`, { method: "POST" }),
    searchWorldbooks: (q: string, limit = 30) =>
      request<{ results: import("../types").WorldBookSearchHit[] }>(
        `/api/worldbook/search?q=${encodeURIComponent(q)}&limit=${limit}`),
    importWorldbookJson: (name: string, data: any) =>
      request<import("../types").WorldBookImportResult>("/api/worldbook/import", {
        method: "POST",
        body: JSON.stringify({ name, data }),
      }),
    importWorldbookFile: (name: string, file: File) =>
      uploadMultipart("/api/worldbook/import", { name }, file),
    exportWorldbook: (id: string) =>
      request<{ name: string; format: string; data: any }>(
        `/api/worldbook/${encodeURIComponent(id)}/export`),
    createWorldbookEntry: (bookId: string, entry: Partial<import("../types").WorldBookEntryDTO>) =>
      request<{ entry: import("../types").WorldBookEntryDTO }>(
        `/api/worldbook/${encodeURIComponent(bookId)}/entries`, {
          method: "POST",
          body: JSON.stringify(entry),
        }),
    updateWorldbookEntry: (bookId: string, entryId: string, entry: Partial<import("../types").WorldBookEntryDTO>) =>
      request<{ entry: import("../types").WorldBookEntryDTO }>(
        `/api/worldbook/${encodeURIComponent(bookId)}/entries/${encodeURIComponent(entryId)}`, {
          method: "PUT",
          body: JSON.stringify(entry),
        }),
    deleteWorldbookEntry: (bookId: string, entryId: string) =>
      request<any>(
        `/api/worldbook/${encodeURIComponent(bookId)}/entries/${encodeURIComponent(entryId)}`, {
          method: "DELETE",
        }),
    setDefaultWorldbook: (id: string, isDefault: boolean) =>
      request<{ default_book_id: string | null }>(`/api/worldbook/${encodeURIComponent(id)}/default`, {
        method: "POST",
        body: JSON.stringify({ default: isDefault }),
      }),
    bindWorldbook: (id: string, sessionId: string, bound: boolean) =>
      request<{ session_id: string; worldbook_id: string | null }>(
        `/api/worldbook/${encodeURIComponent(id)}/bind`, {
          method: "POST",
          body: JSON.stringify({ session_id: sessionId, bound }),
        }),
    resolveWorldbook: (sessionId?: string) =>
      request<import("../types").WorldBookResolveResult>(
        `/api/worldbook/resolve${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ""}`),

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
    importCharacterCard: (file: File) =>
      uploadMultipart("/api/characters/import", {}, file),

    // ── 玩家身份角色 ──
    getPlayerIdentities: () => request<{ id: string; name: string; summary: string; tags: string[] }[]>("/api/player-identities"),
    savePlayerIdentity: (name: string, metadata: Record<string, any>, content: string) =>
      request<any>(`/api/player-identities/${encodeURIComponent(name)}`, {
        method: "PUT",
        body: JSON.stringify({ metadata, content }),
      }),
    deletePlayerIdentity: (name: string) =>
      request<any>(`/api/player-identities/${encodeURIComponent(name)}`, { method: "DELETE" }),
    setPlayerIdentity: (sessionId: string, identity: string) =>
      request<{ message: string; player_identity: string }>(`/api/sessions/${sessionId}/identity`, {
        method: "PUT",
        body: JSON.stringify({ identity }),
      }),

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


    // ── 卡牌 CRUD ──
    getCharacterCards: (name: string) =>
      request<any>(`/api/cards/${encodeURIComponent(name)}`),
    saveCharacterCards: (name: string, data: Record<string, any>) =>
      request<any>(`/api/cards/${encodeURIComponent(name)}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    getClassCards: (className: string) =>
      request<any>(`/api/cards/classes/${encodeURIComponent(className)}`),
    saveClassCards: (className: string, data: Record<string, any>) =>
      request<any>(`/api/cards/classes/${encodeURIComponent(className)}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    listCharactersWithCards: () =>
      request<{ characters: string[] }>("/api/cards"),
    listClassesWithCards: () =>
      request<{ classes: string[] }>("/api/cards/classes"),
    getCardsTree: () =>
      request<import("../types").CardsTreeDTO>("/api/cards/tree"),
    deleteCharacterCard: (name: string, cardId: string) =>
      request<any>(`/api/cards/${encodeURIComponent(name)}/cards/${encodeURIComponent(cardId)}`, {
        method: "DELETE",
      }),
    deleteClassCard: (className: string, cardId: string) =>
      request<any>(`/api/cards/classes/${encodeURIComponent(className)}/cards/${encodeURIComponent(cardId)}`, {
        method: "DELETE",
      }),
    createCharacterCard: (name: string, card: Record<string, any>) =>
      request<any>(`/api/cards/${encodeURIComponent(name)}/cards`, {
        method: "POST",
        body: JSON.stringify(card),
      }),
    createClassCard: (className: string, card: Record<string, any>) =>
      request<any>(`/api/cards/classes/${encodeURIComponent(className)}/cards`, {
        method: "POST",
        body: JSON.stringify(card),
      }),

    // ── 物品永久保存 ──
    saveItem: (itemId: string, content: string, metadata?: Record<string, any>, hash?: string) =>
      request<any>(`/api/items/${encodeURIComponent(itemId)}`, {
        method: "PUT",
        body: JSON.stringify({ content, metadata, hash }),
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
    combatStart: (sessionId: string, encounterId: string, characters: string[], approachId?: string) =>
      request<any>(`/api/sessions/${sessionId}/combat/start`, {
        method: "POST",
        body: JSON.stringify({ encounter_id: encounterId, characters, approach_id: approachId }),
      }),

    combatState: (sessionId: string) =>
      request<any>(`/api/sessions/${sessionId}/combat/state`),

    combatAction: (sessionId: string, action: { action: string; card_index?: number; target?: [number, number]; item_name?: string; unit_id?: string }) =>
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

    combatAbandon: (sessionId: string) =>
      request<{ message: string; auto_narrate_action: string }>(
        `/api/sessions/${sessionId}/combat/abandon`,
        { method: "POST" },
      ),

    combatCardPick: (sessionId: string, cardId: string) =>
      request<{ ok: boolean; card_id: string; deck_size: number }>(
        `/api/sessions/${sessionId}/combat/card-pick`,
        { method: "POST", body: JSON.stringify({ card_id: cardId }) },
      ),

    // ── Combat Test (no session required) ──
    combatTestStart: (encounterId?: string) =>
      request<{ test_id: string; state: any }>("/api/combat/test/start", {
        method: "POST",
        body: JSON.stringify(encounterId ? { encounter_id: encounterId } : {}),
      }),

    combatTestState: (testId: string) =>
      request<any>(`/api/combat/test/${testId}/state`),

    combatTestAction: (testId: string, action: { action: string; card_index?: number; target?: [number, number]; item_name?: string; unit_id?: string }) =>
      request<any>(`/api/combat/test/${testId}/action`, {
        method: "POST",
        body: JSON.stringify(action),
      }),

    combatTestEndTurn: (testId: string) =>
      request<any>(`/api/combat/test/${testId}/end-turn`, {
        method: "POST",
      }),

    combatTestDelete: (testId: string) =>
      request<{ ok: boolean }>(`/api/combat/test/${testId}`, {
        method: "DELETE",
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
    onReasoning?: (token: string) => void;
    onSceneEvent?: (event: any) => void;
    onMemoryEvent?: (event: any) => void;
    onChoice?: (options: string[]) => void;
    onDialogueSegments?: (segments: { type: string; text: string; speaker?: string }[]) => void;
    onTokenUsage?: (usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number }) => void;
    onCombatTrigger?: (data: { encounter_id: string; session_id: string }) => void;
    onCombatBriefing?: (data: { encounter_id: string; session_id: string; name: string; approaches: { id: string; label: string; hint: string; kind: "combat" | "check" | "avoid" }[] }) => void;
    onAttributeRoll?: (data: {
      attribute: string; character: string; roll: number;
      modifier: number; total: number; dc: number;
      success: boolean; text: string; source: string; stream_id: string;
    }) => void;
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
    onReasoning?: (token: string) => void;
    onSceneEvent?: (event: any) => void;
    onMemoryEvent?: (event: any) => void;
    onChoice?: (options: string[]) => void;
    onDialogueSegments?: (segments: { type: string; text: string; speaker?: string }[]) => void;
    onTokenUsage?: (usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number }) => void;
    onCombatTrigger?: (data: { encounter_id: string; session_id: string }) => void;
    onCombatBriefing?: (data: { encounter_id: string; session_id: string; name: string; approaches: { id: string; label: string; hint: string; kind: "combat" | "check" | "avoid" }[] }) => void;
    onAttributeRoll?: (data: {
      attribute: string; character: string; roll: number;
      modifier: number; total: number; dc: number;
      success: boolean; text: string; source: string; stream_id: string;
    }) => void;
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
  const controller = new AbortController();

  async function connect() {
    const base = await getBaseUrl();
    const url = `${base}${path}`;

    try {
      const res = await fetch(url, {
        headers: { "Accept": "text/event-stream" },
        signal: controller.signal,
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
      controller.abort();
    },
  };
}

function connectSSE(
  path: string,
  method: "GET" | "POST",
  body: Record<string, any> | undefined,
  handlers: {
    onText?: (token: string) => void;
    onReasoning?: (token: string) => void;
    onSceneEvent?: (event: any) => void;
    onMemoryEvent?: (event: any) => void;
    onChoice?: (options: string[]) => void;
    onDialogueSegments?: (segments: { type: string; text: string; speaker?: string }[]) => void;
    onTokenUsage?: (usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number }) => void;
    onCombatTrigger?: (data: { encounter_id: string; session_id: string }) => void;
    onCombatBriefing?: (data: { encounter_id: string; session_id: string; name: string; approaches: { id: string; label: string; hint: string; kind: "combat" | "check" | "avoid" }[] }) => void;
    onAttributeRoll?: (data: {
      attribute: string; character: string; roll: number;
      modifier: number; total: number; dc: number;
      success: boolean; text: string; source: string; stream_id: string;
    }) => void;
    onError?: (message: string) => void;
    onDone?: () => void;
  }
): { close: () => void } {
  let closed = false;
  let finished = false;
  const controller = new AbortController();

  async function connect() {
    const base = await getBaseUrl();
    const url = `${base}${path}`;

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
            finished = true;
            continue;
          }

          try {
            const event = JSON.parse(jsonStr);
            switch (event.type) {
              case "text":
                handlers.onText?.(event.data.token);
                break;
              case "reasoning":
                handlers.onReasoning?.(event.data.token);
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
              case "dialogue_segments":
                handlers.onDialogueSegments?.(event.data.segments);
                break;
              case "token_usage":
                handlers.onTokenUsage?.(event.data.usage);
                break;
              case "combat_trigger":
                handlers.onCombatTrigger?.(event.data);
                break;
              case "combat_briefing":
                handlers.onCombatBriefing?.(event.data);
                break;
              case "attribute_roll":
                handlers.onAttributeRoll?.(event.data);
                break;
              case "error":
                handlers.onError?.(event.data.message);
                break;
              case "done":
                handlers.onDone?.();
                finished = true;
                break;
            }
          } catch {}
        }
      }

      // 服务端未发送 done 就关闭连接时，也结束流式状态，避免一直“思考中”
      if (!closed && !finished) {
        handlers.onDone?.();
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
      controller.abort();
    },
  };
}
