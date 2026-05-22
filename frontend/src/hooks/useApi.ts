/**
 * API 客户端 Hook — 封装所有后端调用
 *
 * 自动检测 Electron 环境（通过 preload）或纯浏览器环境。
 */

const FALLBACK_URL = "http://127.0.0.1:5000";

async function getBaseUrl(): Promise<string> {
  if (window.electronAPI) {
    return await window.electronAPI.getBackendUrl();
  }
  return FALLBACK_URL;
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const base = await getBaseUrl();
  const url = `${base}${path}`;

  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
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
}

export function useApi() {
  return {
    // ── 状态 ──
    getStatus: () => request<any>("/api/status"),

    // ── 会话 ──
    listSessions: () => request<any[]>("/api/sessions"),
    createSession: (mode: "free" | "story" = "free", name = "") =>
      request<any>("/api/sessions", {
        method: "POST",
        body: JSON.stringify({ mode, name }),
      }),
    getSession: (id: string) => request<any>(`/api/sessions/${id}`),
    deleteSession: (id: string) =>
      request<any>(`/api/sessions/${id}`, { method: "DELETE" }),

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

    // ── LLM ──
    getLLMStatus: () => request<any>("/api/llm/status"),
    refreshLLM: () =>
      request<any>("/api/llm/refresh", { method: "POST" }),
    switchLLM: (endpointId: string) =>
      request<any>("/api/llm/switch", {
        method: "POST",
        body: JSON.stringify({ endpoint: endpointId }),
      }),
  };
}

/**
 * 创建 GET SSE 连接
 */
export function createSSE(
  path: string,
  handlers: {
    onText?: (token: string) => void;
    onSceneEvent?: (event: any) => void;
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
    onChoice?: (options: string[]) => void;
    onError?: (message: string) => void;
    onDone?: () => void;
  }
): { close: () => void } {
  return connectSSE(path, "POST", body, handlers);
}

function connectSSE(
  path: string,
  method: "GET" | "POST",
  body: Record<string, any> | undefined,
  handlers: {
    onText?: (token: string) => void;
    onSceneEvent?: (event: any) => void;
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
