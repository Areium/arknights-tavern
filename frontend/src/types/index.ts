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

/** 文档树节点（来自后端） */
export interface DocTreeNode {
  name: string;
  type: "folder" | "document";
  id?: string;
  hash?: string;
  mtime?: number;
  summary?: string;
  category_id?: string;
  children?: DocTreeNode[];
}

/** 文档树类别分组 */
export interface DocTreeCategory {
  category: string;
  category_info: DocumentCategory;
  children: DocTreeNode[];
}

/** 移动/重命名操作结果 */
export interface MoveResult {
  old_path: string;
  new_path: string;
  category: string;
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
  openDirectory: (dirPath: string) => Promise<{ success: boolean; error: string }>;
  onBackendStatus: (cb: (status: { status: string; url: string }) => void) => () => void;
}

/** 任务 */
export interface Quest {
  id: string;
  name: string;
  type: "main" | "side" | "deep";
  chapter: string;
  objective: string;
  trigger: string;
  completion: string;
  reward: string;
  failure: string;
  status: "hidden" | "locked" | "visible" | "active" | "completed" | "failed";
  updated_at: number;
  task_id?: string;
  subtype?: string;
}

/** 任务列表响应 */
export interface QuestsResponse {
  plot_id: string | null;
  quests: Quest[];
}

/** 可用剧情 */
export interface PlotInfo {
  id: string;
  name: string;
  category: string;
  priority: number;
  trigger_location: string[];
  trigger_character: string[];
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}
