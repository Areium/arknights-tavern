/** 后端状态 */
export interface BackendStatus {
  status: "connecting" | "connected" | "disconnected" | "error";
  url: string;
}

/** LLM 后端信息 */
export interface LLMEndpoint {
  id: string;
  name: string;
  type: "cloud" | "local";
  model: string;
  available: boolean;
  latency_ms: number;
  detail: string;
}

export interface LLMStatus {
  primary: LLMEndpoint | null;
  fallback: LLMEndpoint | null;
  endpoints: LLMEndpoint[];
  available: boolean;
}

/** 会话 */
export interface Session {
  id: string;
  name: string;
  mode: "free" | "story";
  created_at: number;
  usable: boolean;
  characters: string[];
  active_character: string | null;
  environment: {
    location: string;
    weather: string;
    time: string;
  };
  scene_log: string[];
}

/** 文档类别 */
export interface DocumentCategory {
  id: string;
  index_path: string;
  directory: string;
  ref_by: string[];
  refs: string[];
}

/** 文档信息 */
export interface DocumentInfo {
  category_id: string;
  id: string;
  title: string;
  hash: string;
  mtime: number;
  summary: string;
}

/** 文档内容 */
export interface DocumentContent {
  metadata: Record<string, any>;
  content: string;
  hash: string;
  path: string;
  filepath: string;
}

/** SSE 事件 */
export interface SSEEvent {
  type: "text" | "scene_event" | "choice" | "heartbeat" | "error" | "done" | "meta";
  data: Record<string, any>;
}

/** 群聊回复 */
export interface GroupChatResponse {
  character: string;
  response: string;
  env_updates: Record<string, any>;
}

/** Electron API （通过 preload 暴露） */
export interface ElectronAPI {
  getBackendUrl: () => Promise<string>;
  getBackendStatus: () => Promise<{ status: string; url: string }>;
  restartBackend: () => Promise<{ status: string }>;
  onBackendStatus: (cb: (status: { status: string; url: string }) => void) => () => void;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}
