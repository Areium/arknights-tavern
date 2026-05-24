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

/** 战斗单位 */
export interface CombatUnitDTO {
  unit_id: string;
  name: string;
  team: "player" | "enemy";
  char_class: string;
  hp: number;
  max_hp: number;
  personal_ap: number;
  max_personal_ap: number;
  patk: number;
  matk: number;
  def: number;
  res: number;
  spd: number;
  hit: number;
  eva: number;
  mobility: number;
  pos: [number, number];
  is_alive: boolean;
  attributes?: Record<string, number>;
}

/** 卡牌 */
export interface CardDTO {
  card_id: string;
  name: string;
  damage_type: "physical" | "arts" | "healing" | "mixed";
  min_damage: number;
  max_damage: number;
  atk_scale: number;
  target: string;
  range: number;
  cost: number;
  tier: "basic" | "elite";
  class_required: string;
  owner: string | null;
}

/** 角色卡池（手牌 + 抽牌堆 + 弃牌堆 + 消耗堆） */
export interface PlayerPoolDTO {
  deck: CardDTO[];
  hand: CardDTO[];
  discard: CardDTO[];
  exhaust: CardDTO[];
}

/** 战斗状态快照 */
export interface CombatStateDTO {
  round_num: number;
  phase: string;
  winner: string | null;
  grid_size: number;
  units: CombatUnitDTO[];
  shared_hand: CardDTO[];
  player_hands: Record<string, CardDTO[]>;
  shared_pool: PlayerPoolDTO;
  shared_ap: number;
  shared_ap_max: number;
  valid_targets: [number, number][];
  valid_moves: [number, number][];
  active_unit_id: string | null;
  grid: Record<string, string>;
  battle_over: boolean;
}

/** 战斗操作 */
export interface CombatAction {
  action: "play_card" | "move";
  card_index?: number;
  unit_id?: string;
  target: [number, number];
}

/** 战斗 SSE 事件 */
export interface CombatEventDTO {
  type: "battle_start" | "round_start" | "turn_start" | "damage" | "heal"
    | "death" | "battle_end" | "move" | "card_played" | "turn_end"
    | "error" | "block_attempt" | "block_success" | "block_fail"
    | "intercept_prompt" | "meta" | "heartbeat" | "done";
  data: Record<string, any>;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

// ── 索引管理（基于 imports 的新系统） ──

export interface IndexDocSummary {
  path: string;
  id: string;
  name: string;
  imports: { path: string; name: string }[];
  imported_by: { path: string; name: string; category: string }[];
}

export interface IndexOverviewCategory {
  category: string;
  label: string;
  level: number;
  docs: IndexDocSummary[];
}

export interface IndexOverview {
  categories: IndexOverviewCategory[];
  hierarchy: { level: number; label: string; categories: string[] }[];
}

export interface IndexGraphNode {
  id: string;
  category: string;
  name: string;
  level: number;
}

export interface IndexGraphEdge {
  source: string;
  target: string;
}

export interface IndexGraph {
  nodes: IndexGraphNode[];
  edges: IndexGraphEdge[];
}

export interface SessionIndexConfig {
  mode: "all" | "whitelist";
  enabled_categories: string[];
  enabled_entities: Record<string, string[]>;
}

export interface BrokenImport {
  import_path: string;
  name: string;
  type?: "missing" | "broken";
}

export interface BrokenRefDoc {
  doc_path: string;
  doc_name: string;
  broken_imports: BrokenImport[];
}

export interface IndexVerifyResult {
  total_docs: number;
  total_imports: number;
  broken_refs: BrokenRefDoc[];
  mode?: string;
}
