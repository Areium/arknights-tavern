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
  plot_id: string | null;
  worldbook_id?: string | null;
  created_at: number;
  usable: boolean;
  characters: string[];
  character_colors: Record<string, string>;
  active_character: string | null;
  environment: {
    location: string;
    weather: string;
    time: string;
    atmosphere: string[];
  };
  scene_log: string[];
  narration_count?: number;
  total_usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
  in_combat?: boolean;
  combat_mode: "narrative" | "tactical";
  custom_prompt?: string;
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
  type: "text" | "scene_event" | "choice" | "heartbeat" | "error" | "done" | "meta" | "combat_trigger" | "combat_briefing";
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

/** 聊天消息 */
export interface ChatMessage {
  role: "user" | "assistant" | "character" | "system" | "narrator";
  content: string;
  character?: string;
  choices?: string[];
  round?: number;
  variants?: string[];
  variantIndex?: number;
  dialogueSegments?: { type: string; text: string; speaker?: string }[];
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  reasoning?: string;
  rollData?: AttributeRollData;
}

/** 属性检定结果 */
export interface AttributeRollData {
  attribute: string;
  character: string;
  roll: number;
  modifier: number;
  total: number;
  dc: number;
  success: boolean;
  text: string;
  source: string;
  stream_id: string;
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
  /** 运行时状态效果：shield/slow/bind/weaken/strengthen */
  status?: Record<string, number>;
  skin_url: string;
  skin_crop: SkinCrop | null;
}

/** 卡面裁剪参数（百分比，0-100） */
export interface SkinCrop {
  x: number;
  y: number;
  w: number;
  h: number;
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
  description: string;
}

/** 战斗卡牌（扩展字段 — combat.json schema） */
export interface CombatCardDTO extends CardDTO {
  rarity: number;
  category: "exclusive" | "class";
  card_type: string[];
  cost_type: "sp" | "passive";
  base_value: number | null;
  base_value_formula: string | null;
  effect: string;
  check: {
    description?: string;
    roll?: string;
    vs?: string;
  } | null;
  plot_impact: string | null;
  usage_limit: { scope: string; count: number } | null;
  condition: string | null;
  tags: string[];
  _needs_review?: boolean;
  _review_reasons?: string[];
}

/** 角色卡牌集合（combat.json 结构） */
export interface CombatCardsDTO {
  version: number;
  exclusive_cards: CombatCardDTO[];
  class_cards: CombatCardDTO[];
  class_name: string | null;
  _hash: string;
}

/** 职业卡牌（cards.json 简化 schema） */
export interface ClassCardDTO {
  card_id: string;
  name: string;
  description: string;
  damage_type: string;
  min_damage: number;
  max_damage: number;
  atk_scale: number;
  target: string;
  range: number;
  cost: number;
  tier: string;
  class_required: string;
  owner: string | null;
}

/** 职业卡牌集合（cards.json 结构） */
export interface ClassCardsDTO {
  version: number;
  class_name: string;
  cards: ClassCardDTO[];
  _hash: string;
}

/** 卡牌管理导航树 */
export interface CardsTreeDTO {
  characters: string[];
  classes: string[];
  character_class_map: Record<string, string>;
}

/** 角色卡池（手牌 + 抽牌堆 + 弃牌堆 + 消耗堆） */
export interface PlayerPoolDTO {
  deck: CardDTO[];
  hand: CardDTO[];
  discard: CardDTO[];
  exhaust: CardDTO[];
}

/** 敌人意图（ROUND_START 计算，供玩家读取敌方计划） */
export interface EnemyIntentDTO {
  type: "attack" | "heavy" | "aoe" | "move" | "defend";
  label: string;
  target_id: string;
  target_name: string;
  card_id: string;
  card_name: string;
  damage_min: number | null;
  damage_max: number | null;
}

/** 战前打法（Approach）选项 */
export interface ApproachDTO {
  id: string;
  label: string;
  hint: string;
  kind: "combat" | "check" | "avoid";
}

/** 战前简报（含打法列表，SSE combat_briefing 事件） */
export interface CombatBriefingDTO {
  encounter_id: string;
  session_id: string;
  name: string;
  approaches: ApproachDTO[];
}

/** 战斗状态快照 */
export interface CombatStateDTO {
  round_num: number;
  phase: string;
  winner: string | null;
  grid_size: number;
  /** 战斗背景图 URL（无图时为 null，前端回退纯色背景） */
  background_url?: string | null;
  units: CombatUnitDTO[];
  shared_hand: CardDTO[];
  player_hands: Record<string, CardDTO[]>;
  shared_pool: PlayerPoolDTO;
  shared_ap: number;
  shared_ap_max: number;
  /** 回合上限（0 = 无限制） */
  max_rounds: number;
  /** 是否允许撤退（fail-forward） */
  escape_enabled: boolean;
  valid_targets: [number, number][];
  valid_moves: [number, number][];
  active_unit_id: string | null;
  grid: Record<string, string>;
  /** 敌人意图：unit_id → intent（玩家回合内读取敌方计划） */
  enemy_intents: Record<string, EnemyIntentDTO>;
  battle_over: boolean;
  inventory: { name: string; count: number }[];
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

// ── 会话资源空间 ──

/** 会话资源条目（背景覆盖 / 角色形象覆盖） */
export interface SessionResourceDTO {
  type: "background" | "character_media";
  key: string;
  /** character_media 时存在：avatar | skin | card_face */
  media_type?: string;
  name: string;
  /** 会话覆盖图 URL（带 session_id，覆盖优先于全局） */
  url: string;
  /** 全局原图 URL（不带 session_id） */
  global_url: string | null;
  size: number;
  has_global: boolean;
}

/** 会话资源总览（GET /api/sessions/<id>/resources） */
export interface SessionResourcesDTO {
  session_id: string;
  backgrounds: SessionResourceDTO[];
  available_background_ids: string[];
  character_media: SessionResourceDTO[];
  scene_characters: string[];
  resources_dir: string;
  backgrounds_dir: string;
}

// ── 世界书（酒馆 Lorebook 兼容） ──

/** 世界书摘要（列表项） */
export interface WorldBookSummary {
  id: string;
  name: string;
  source_format: string;
  budget_tokens: number;
  entry_count: number;
  created_at: number;
  updated_at: number;
  is_default: boolean;
}

/** 世界书条目（规范化格式） */
export interface WorldBookEntryDTO {
  uid: string;
  name: string;
  content: string;
  trigger_keys: string[];
  secondary_keys: string[];
  always_active: boolean;
  selective: boolean;
  enabled: boolean;
  position: number;
  depth: number;
  scan_depth: number;
  probability: number;
  group: string;
  group_weight: number;
  case_sensitive: boolean;
  match_whole_words: boolean;
  /** 酒馆原始字段（导出回灌用） */
  raw?: Record<string, any>;
}

/** 世界书详情（含条目） */
export interface WorldBookDetail extends WorldBookSummary {
  entries: WorldBookEntryDTO[];
}

/** 导入报告 */
export interface WorldBookImportReport {
  source_format: string;
  imported: number;
  skipped: number;
  warnings: string[];
}

/** 导入结果 */
export interface WorldBookImportResult {
  book: WorldBookSummary;
  report: WorldBookImportReport;
}

/** 会话当前生效世界书查询结果 */
export interface WorldBookResolveResult {
  book: WorldBookSummary | null;
  default_book_id: string | null;
}
