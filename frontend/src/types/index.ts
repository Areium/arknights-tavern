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
  player_identity?: string;
  plot_id: string | null;
  worldbook_id?: string | null;
  worldbook_scope?: WorldBookScopeDTO | null;
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
  /** 是否存在可继续的战斗（内存中仍在，或磁盘上有挂起存档） */
  combat_resumable?: boolean;
  /** 挂起存档摘要（`in_combat` 为真时为 null，因为战斗未挂起） */
  combat_resume?: CombatResumeSummaryDTO | null;
  custom_prompt?: string;
}

/** 挂起战斗摘要 —— 「继续战斗」入口展示所需的最小信息 */
export interface CombatResumeSummaryDTO {
  encounter_id: string;
  suspended_at: number | null;
  round_num: number;
  phase: string;
  battle_over: boolean;
  player_alive: number;
  hand_size: number;
  pending_waves: number;
}

/** 可恢复的会话战（`/api/combat/resumes`） */
export interface CombatResumeSessionDTO {
  session_id: string;
  name: string;
  mode: string;
  /** 战斗是否仍在后端内存中（false = 已挂起落盘，需走 resume 重建） */
  in_memory: boolean;
  combat: CombatResumeSummaryDTO | null;
}

/** 可恢复的战斗测试（无会话） */
export interface CombatResumeTestDTO extends CombatResumeSummaryDTO {
  test_id: string;
}

export interface CombatResumesDTO {
  sessions: CombatResumeSessionDTO[];
  tests: CombatResumeTestDTO[];
}

/** Electron API （通过 preload 暴露） */
export interface ElectronAPI {
  getBackendUrl: () => Promise<string>;
  openDirectory: (dirPath: string) => Promise<{ success: boolean; error: string }>;
}

/** 聊天消息 */
export interface ChatMessage {
  role: "user" | "assistant" | "character" | "system" | "narrator";
  content: string;
  character?: string;
  choices?: string[];
  /** 结构化分支选项（含目标节拍），与 choices 并存 */
  branches?: BranchChoice[];
  round?: number;
  variants?: string[];
  variantIndex?: number;
  dialogueSegments?: { type: string; text: string; speaker?: string }[];
  /** 是否为正在流式生成的叙述消息（气泡模式下流式期间先显示纯文本） */
  streaming?: boolean;
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  reasoning?: string;
  rollData?: AttributeRollData;
}

/** 剧情分支选项（LLM 生成或作者预设） */
export interface BranchChoice {
  id: string;
  label: string;
  intent?: string | null;
  target_beat_id?: string | null;
  source?: "llm" | "author";
}

/** 剧情节点状态（路线图中的一个节拍） */
export interface StoryBeatNode {
  id: string;
  summary: string;
  keep_on_deviate?: boolean;
  state: "done" | "current" | "locked";
  round_start: number | null;
  round_end: number | null;
  has_combat?: boolean;
  authored_branches?: BranchChoice[];
}

/** 剧情章节（含节拍列表） */
export interface StoryRoad {
  chapter_idx: number;
  title: string;
  summary?: string;
  state: "done" | "current" | "locked";
  beats: StoryBeatNode[];
}

/** 剧情树节点（LLM 现场生成的场景节点；节点内容非作者节拍骨架） */
export interface StoryTreeNode {
  id: string;
  parent_id: string | null;
  depth: number;
  title: string;
  summary: string;
  intent?: string;
  branch_label?: string;
  children: string[];
  branches: (BranchChoice & { child_id?: string; taken?: boolean })[];
  round_start?: number | null;
  round_end?: number | null;
  has_state: boolean;
  state: "current" | "path" | "visited";
}

/** 剧情树视图（GET /story-state 的 tree 字段） */
export interface StoryTreeDTO {
  has_tree: boolean;
  root_id: string;
  current_id: string;
  path?: string[];
  nodes: StoryTreeNode[];
  current_node?: StoryTreeNode | null;
}

/** 剧情状态 DTO（GET /story-state） */
export interface StoryStateDTO {
  has_plot: boolean;
  plot_id?: string;
  plot_name?: string;
  chapter?: { idx: number; title: string; total: number; id: string } | null;
  beat?: {
    idx: number; total: number; id: string; summary: string; narrations_on_beat: number;
  } | null;
  roads: StoryRoad[];
  /** 动态剧情树（LLM 生成的节点结构） */
  tree?: StoryTreeDTO;
  completed_beats?: string[];
  pending_branch?: any;
  character_states?: Record<string, any>;
  quest_states?: Record<string, any>;
  node_history?: {
    node_id: string; title?: string; depth?: number;
    round_start: number | null; round_end: number | null;
  }[];
  combat_nodes?: Record<string, any>;
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
  initial_characters?: string[];
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
  /** 来源世界书标注（读实体 index.md frontmatter，未标注为空串） */
  worldbook_map?: { characters: Record<string, string>; classes: Record<string, string> };
}

/** 角色卡池（手牌 + 抽牌堆 + 弃牌堆 + 消耗堆） */
export interface PlayerPoolDTO {
  deck: CardDTO[];
  hand: CardDTO[];
  discard: CardDTO[];
  exhaust: CardDTO[];
}

/** 敌人意图的单段动作（v1：精英/Boss 每轮可有多个动作） */
export interface EnemyIntentActionDTO {
  type: "attack" | "heavy" | "aoe" | "move" | "defend";
  label: string;
  card_id: string;
  card_name: string;
  target_id: string;
  target_name: string;
  damage_min: number | null;
  damage_max: number | null;
}

/** 敌人意图（ROUND_START 计算，供玩家读取敌方计划）
 *
 * v1（balance_version 1）起包含行动槽与多段动作计划：首段动作同时平铺在
 * 顶层字段（向后兼容旧组件），完整计划见 `actions`。
 */
export interface EnemyIntentDTO {
  type: "attack" | "heavy" | "aoe" | "move" | "defend";
  label: string;
  target_id: string;
  target_name: string;
  card_id: string;
  card_name: string;
  damage_min: number | null;
  damage_max: number | null;
  /** 该敌人每轮行动槽数（普通 1，精英/Boss 2） */
  action_slots?: number;
  /** 每轮计划：预告与执行使用同一计划 */
  actions?: EnemyIntentActionDTO[];
  /** 计划生成时的剩余 AP */
  ap?: number;
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

/** 战场格子类型（服务端 `combat_map.TileType` 的镜像） */
export interface TileTypeDTO {
  tile_id: string;
  name: string;
  glyph: string;
  color: string;
  blocks_movement: boolean;
  blocks_los: boolean;
  move_cost: number;
  defense_bonus: number;
  evasion_bonus: number;
  damage_bonus: number;
  deployable_player: boolean;
  deployable_enemy: boolean;
  on_enter: Record<string, number | string>;
  on_round_start: Record<string, number | string>;
  tags: string[];
}

/** 战斗状态快照 */
export interface CombatStateDTO {
  round_num: number;
  phase: string;
  winner: string | null;
  /** 战场行列（自由尺寸，非正方形） */
  rows: number;
  cols: number;
  /** 每格的 tile_id（tiles[row][col]） */
  tiles: string[][];
  /** 地图上用到的格子定义 */
  tile_defs: Record<string, TileTypeDTO>;
  /** 部署区（已展开为坐标列表） */
  deploy: { player: [number, number][]; enemy: [number, number][] };
  /** 地图校验警告（软锁/越界等，非阻断） */
  map_warnings: string[];
  /** 距离度量（默认 manhattan） */
  range_metric: "manhattan" | "chebyshev";
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
  /** valid_moves 对应的单位（未选择时为行动中的单位） */
  valid_moves_unit?: string | null;
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

// ── 战斗结算（胜负判定成立后自动进入） ──

/** 单次升级记录 */
export interface LevelUpDTO {
  level: number;
  attribute: string;
  value: number;
  delta: number;
}

/** 升级导致的属性变化 */
export interface AttributeChangeDTO {
  name: string;
  before: number;
  after: number;
  delta: number;
}

/** 单个参战角色的结算条目 */
export interface CharacterSettlementDTO {
  name: string;
  in_battle: boolean;
  alive: boolean;
  xp_gained: number;
  level_before: number;
  level_after: number;
  level_delta: number;
  xp_before: number;
  xp_after: number;
  /** 升级前等级升到下一级所需经验 */
  xp_needed_before: number;
  /** 结算后等级升到下一级所需经验 */
  xp_needed: number;
  level_ups: LevelUpDTO[];
  attribute_changes: AttributeChangeDTO[];
  /** 本次升级发放的属性点（批次 3 起；默认自动分配到最低属性） */
  attribute_points_gained?: number;
  attribute_points_allocated?: number;
  /** 关闭自动分配时累积的待分配属性点 */
  attribute_points_pending?: number;
  specialization_points_gained?: number;
  specialization_points_after?: number;
  /** 属性已满值 → 无法继续成长 */
  capped: boolean;
  cap_reason: string;
}

/** 结算奖励汇总 */
export interface SettlementRewardsDTO {
  xp_total: number;
  enemy_xp: number;
  items: { name: string; count: number }[];
  cards: CardDTO[];
  /** 遭遇声明但尚未接入的奖励字段（如 unlock） */
  unwired: string[];
  xp_formula: string;
}

/** 战斗结算 DTO（GET/POST /combat/settlement、SSE battle_end.data.settlement） */
export interface CombatSettlementDTO {
  settlement_id: string;
  encounter_id: string;
  encounter_name: string;
  winner: string;
  rounds: number;
  reward_mult: number;
  victory: boolean;
  characters: CharacterSettlementDTO[];
  rewards: SettlementRewardsDTO;
  has_reward: boolean;
  /** 无经验无奖励时的明确提示文案 */
  empty_message: string | null;
  created_at: number;
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
  /** 来源：preinstalled（预装整合包）/ imported（用户导入）——统一管理，均可编辑 */
  source: "preinstalled" | "imported";
  /** 是否存在分发源（预装包可一键重装还原） */
  is_preinstalled: boolean;
  /** 书级启用开关，停用不参与解析 */
  enabled: boolean;
  budget_tokens: number;
  entry_count: number;
  created_at: number;
  updated_at: number;
  is_default: boolean;
}

/** 世界书检索命中（GET /api/worldbook/search） */
export interface WorldBookSearchHit {
  book: WorldBookSummary;
  matches: WorldBookEntryDTO[];
  match_count: number;
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
  category_id?: string;
  character_id?: string;
  /** 酒馆原始字段（导出回灌用） */
  raw?: Record<string, any>;
}

/** 世界书详情（含条目） */
export interface WorldBookDetail extends WorldBookSummary {
  entries: WorldBookEntryDTO[];
  schema_version?: number;
  scope_mode?: "legacy" | "selective";
  categories?: WorldBookCategoryDTO[];
  dependency_edges?: WorldBookDependencyEdgeDTO[];
  import_config?: WorldBookImportConfigDTO;
  /** v3：全书底层有向图的条件起点；null/缺省表示这本书仍是 v2 语义 */
  dependency_rules?: WorldBookRulesDTO | null;
  related_edges?: WorldBookDependencyEdgeDTO[];
  content_revision?: string;
  resolver_version?: number;
  policy_revisions?: WorldBookPolicyRevisionDTO[];
  /** 已应用 AI 根/边的正文证据在当前内容中失效；关系仍保留 */
  evidence_issues?: WorldBookIssueDTO[];
}

export type WorldBookScopeType = "worldview" | "character" | "other";
export interface WorldBookCategoryDTO {
  id: string;
  parent_id: string | null;
  name: string;
  scope_type: WorldBookScopeType;
  sort_order: number;
}
export interface WorldBookDependencyEdgeDTO { from_uid: string; to_uid: string; }
export interface SessionWorldbookDependenciesDTO {
  session_id: string;
  book_id: string;
  book_name: string;
  scope_revision: number;
  revision_hash: string;
  content_revision: string;
  inheritance: Record<string, any>;
  local_overrides: {
    requires_edges: WorldBookDependencyEdgeDTO[];
    related_edges: WorldBookDependencyEdgeDTO[];
    root_expansions?: Record<string, WorldBookExpansion>;
  };
  suppressed_edges: Array<WorldBookDependencyEdgeDTO & { relation: "requires" | "related" }>;
  effective_requires_edges: WorldBookDependencyEdgeDTO[];
  effective_related_edges: WorldBookDependencyEdgeDTO[];
  effective_rules: WorldBookRulesDTO;
  edge_origins: Record<string, "inherited" | "local">;
  conflicts: Array<WorldBookDependencyEdgeDTO & {
    inherited_relation: string; local_relation: string; resolution: string;
  }>;
  resolved_entry_uids: string[];
  selection_reasons: Record<string, string[]>;
  entries: Array<{ uid: string; name: string; selected: boolean; reasons: string[] }>;
}
export interface SessionInheritancePreviewDTO {
  expected_scope_revision: number;
  from_policy_revision: number;
  to_policy_revision: number;
  changes: Array<WorldBookDependencyEdgeDTO & { kind: "added" | "removed"; relation: string }>;
  rule_changes: Array<{ entry_uid: string; kind: "added" | "removed" | "changed"; before?: WorldBookRootDTO; after?: WorldBookRootDTO }>;
  scope_added: string[];
  scope_removed: string[];
  conflicts: SessionWorldbookDependenciesDTO["conflicts"];
  preview_hash: string;
}
export interface WorldBookImportConfigDTO {
  fixed_entry_uids: string[];
  dependency_sources: Array<{ entry_uid: string; max_depth: number }>;
  revision: number;
}

/** v3 起点激活方式：always 恒为候选 / roster_any 入队任一角色即候选 / manual 只手动追加 */
export type WorldBookActivation = "always" | "roster_any" | "manual";
/** v3 展开方式：none 只含自身 / requires_closure 完整必要闭包 / legacy_depth 旧深度语义 */
export type WorldBookExpansion = "none" | "requires_closure" | "legacy_depth";
export interface WorldBookRootDTO {
  entry_uid: string;
  activation: WorldBookActivation;
  expansion: WorldBookExpansion;
  character_ids?: string[];
  max_depth?: number;
  locked?: boolean;
  origin?: string;
  model?: string;
  prompt_version?: string;
  source_content_hash?: string;
  evidence?: string;
  review_status?: string;
  job_id?: string;
}
/** v3 规则集：分类只负责组织，起点与展开决定候选 */
export interface WorldBookRulesDTO {
  roots: WorldBookRootDTO[];
  root_rule?: { entry_uids: string[] };
  requires_edges?: WorldBookDependencyEdgeDTO[];
  related_edges?: WorldBookDependencyEdgeDTO[];
  /** 人工拒绝过的 AI 建议（持久化，防止「删掉又被重新应用」） */
  rejected?: WorldBookDependencyEdgeDTO[];
  /** 每条边的来源 / 证据 / 审阅状态，按 "from|to" 键控 */
  edge_meta?: Record<string, Record<string, string | boolean>>;
}
export interface WorldBookPolicyRevisionDTO {
  revision: number;
  resolver_version: number;
  created_at: number;
}
export interface WorldBookDisplayNodeDTO {
  uid: string;
  name: string;
  root_uid: string;
  depth: number;
  parent_uid: string | null;
  child_uids: string[];
  remaining: number | null;
  is_root: boolean;
}
export interface WorldBookIssueDTO {
  code: string;
  severity: "error" | "warning" | "info";
  uid?: string;
  message: string;
}
/** 统一配置写入（PUT /api/worldbook/<id>/configuration）的请求体 */
export interface WorldBookConfigurationDraft {
  expected_revision?: number;
  /**
   * 显式启用 v3 按需载入规则。**只有用户明确选择时才传**：
   * v2 书的普通分类 / 角色编辑不能顺手把书切成按需载入（预装书 fixed/sources
   * 都是空的，一旦隐式启用候选会被清成空集）。服务端也只认这个显式开关。
   */
  adopt_v3?: boolean;
  categories?: WorldBookCategoryDTO[];
  entry_moves?: Record<string, string>;
  entry_updates?: Record<string, { category_id?: string; character_id?: string }>;
  scope_mode?: "legacy" | "selective";
  roots?: WorldBookRootDTO[];
  requires_edges?: WorldBookDependencyEdgeDTO[];
  related_edges?: WorldBookDependencyEdgeDTO[];
  /**
   * AI 构建结果：与手写草稿在同一次原子写入中生效。
   * `job_id` 是**服务端复核**的依据（任务身份 + 正文哈希 + 证据可定位），
   * 客户端传的 accepted 只是「用户选了哪几条」的提示。
   */
  proposal?: {
    materialized?: boolean;
    materialized_root_uids?: string[];
    job_id: string;
    accepted_pairs?: Array<[string, string]>;
    accepted?: Array<{ from_uid: string; to_uid: string; relation?: string }>;
  } | null;
  /** 人工拒绝过的建议：再次应用同一份 AI 结果时不得复活 */
  rejected?: WorldBookDependencyEdgeDTO[];
}
export interface WorldBookConfigurationResultDTO {
  book: WorldBookDetail;
  policy_revision: number;
  content_revision: string;
  applied: { categories: number; roots: number; requires_edges: number; related_edges: number };
}
/** AI 依赖构建任务 */
export type DependencyJobStage =
  | "queued" | "metadata" | "cards" | "candidates" | "adjudication"
  | "validation" | "done" | "failed" | "cancelled";
export interface DependencyProposalRecordDTO {
  from_uid: string;
  to_uid: string;
  relation: "requires" | "related" | "none" | "unsure";
  confidence: number;
  reason: string;
  evidence: string;
  evidence_hash: string;
  source_content_hash: string;
  target_content_hash: string;
  origin: string;
  model: string;
  prompt_version: string;
  review_status: string;
}
export interface DependencyProposalResultDTO {
  proposal_version: string;
  model: string;
  content_revision: string;
  records: DependencyProposalRecordDTO[];
  records_total?: number;
  record_offset?: number;
  accepted: Array<{ from_uid: string; to_uid: string; relation: string; confidence: number }>;
  /** AI 建议的角色起点（只接受真实存在于角色目录的 id） */
  roots?: WorldBookRootDTO[];
  /** 完整可编辑根计划：含确定性分类根与已验证的 AI 根 */
  configuration_roots?: WorldBookRootDTO[];
  root_records?: WorldBookRootDTO[];
  root_issues?: WorldBookIssueDTO[];
  issues: WorldBookIssueDTO[];
  cycles: string[][];
  fanout: Record<string, number>;
  expansion_probe: Record<string, number>;
  stats: { records: number; requires: number; related: number; unsure: number; none: number; roots?: number };
}
/** 终态必须三态可区分：success 全部成功 / partial 部分批次失败 / failed 没有任何产出 */
export type DependencyJobOutcome = "" | "success" | "partial" | "failed";
export type WorldBookReadingMode = "adaptive" | "full";
export interface DependencyFailedBatchDTO {
  stage: string;
  code?: string;
  message?: string;
  uids?: string[];
  pairs?: string[][];
  chunk_ids?: string[];
  /** 预算耗尽等可续跑：重试只补这些批次 */
  resumable?: boolean;
}
export interface DependencyProposalJobDTO {
  job_id: string;
  book_id: string;
  input_hash: string;
  model: string;
  reading_mode: WorldBookReadingMode;
  stage: DependencyJobStage;
  progress: number;
  total: number;
  message: string;
  created_at: number;
  updated_at: number;
  cancelled: boolean;
  running?: boolean;
  context?: {
    session_id?: string;
    scope_revision?: number;
    scoped_complete?: boolean;
    pending_frontier?: string[];
  };
  error: { code: string; message: string } | null;
  calls: number;
  failed_batches: DependencyFailedBatchDTO[];
  card_count: number;
  judgment_count: number;
  /** 输入快照已变化：结果不得直接覆盖当前数据 */
  stale?: boolean;
  outcome?: DependencyJobOutcome;
  /** 预算耗尽 / 批次失败后可以续跑（重试只补缺失部分） */
  resumable?: boolean;
  /**
   * 开工前的**估算**（不是账单）：请求数、输入 token、预期输出 token。
   * `estimated_input_tokens` 由与执行同一个装箱器算出，因此与真实请求规模一致；
   * 真实用量见 `metrics.actual_*`。
   */
  workload?: {
    entries?: number;
    chunks?: number;
    candidates?: number;
    pairs?: number;
    card_calls?: number;
    adjudication_calls?: number;
    estimated_calls?: number;
    estimated_input_tokens?: number;
    estimated_analysis_input_tokens?: number;
    estimated_adjudication_input_tokens?: number;
    expected_output_tokens?: number;
    /** 估算是否走了真实规划器（false = 只有保守近似） */
    planned?: boolean;
    budget?: number;
    reading_mode?: WorldBookReadingMode;
    reading_coverage?: "full" | "partial";
    reading_read_chars?: number;
    reading_unread_chars?: number;
    analysis_supplement_requests?: number;
    possible_supplement_note?: string;
  };
  candidates?: { pairs?: number; candidates_total?: number; candidates_used?: number; deferred?: number; generic_aliases?: number };
  chunk_report?: { entries?: number; chunks?: number; dropped_chars?: number };
  /**
   * 运行计数。`actual_known=false` 表示 provider **没有报告**用量，
   * 此时 `actual_*` 是「未知」而不是 0 —— 界面必须区分这两者。
   * `usage_partial=true` 表示只有一部分请求上报了用量，`actual_*` 是**部分合计**，
   * 不能显示成「完整实测总量」。
   */
  metrics?: {
    planned_requests?: number;
    requests?: number;
    json_repair_calls?: number;
    cache_hits?: number;
    analysis_requests?: number;
    supplement_requests?: number;
    adjudication_requests?: number;
    actual_known?: boolean;
    usage_partial?: boolean;
    actual_prompt_tokens?: number;
    actual_completion_tokens?: number;
    actual_total_tokens?: number;
    estimated_sent_tokens?: number;
  };
  pending_pairs?: number;
  pending_card_uids?: number;
  pending_chunk_ids?: number;
  reading_report?: {
    mode?: WorldBookReadingMode;
    coverage: "full" | "partial";
    total_chars: number;
    read_chars: number;
    unread_chars: number;
    omitted_chars: number;
    partial_entries: number;
    full_entries: number;
    planned_selected_chars?: number;
    fallback_entries?: number;
    supplement_entries?: number;
  };
  supplement?: { escalated?: boolean; pending_entries?: string[]; complete_entries?: string[] };
  result: DependencyProposalResultDTO | null;
}

export interface WorldBookScopeDTO {
  book_id: string | null;
  policy_revision?: number;
  roster_character_ids?: string[];
  resolved_entry_uids: string[];
  legacy_full_scope?: boolean;
  resolved_at?: number;
  selection_reasons?: Record<string, string[]>;
  excluded_entries?: Array<{ uid: string; name: string; reason: string }>;
}
export interface WorldBookPolicyDraft {
  fixed_entry_uids: string[];
  dependency_sources: WorldBookImportConfigDTO["dependency_sources"];
  dependency_edges: WorldBookDependencyEdgeDTO[];
  scope_mode: "legacy" | "selective";
  expected_revision?: number;
}
/** 自动分类：单个候选分类（含条目数） */
export interface WorldBookClassificationCategoryDTO extends WorldBookCategoryDTO {
  count: number;
}
/** 自动分类方案（POST /api/worldbook/<id>/auto-classify，apply=false 时只读） */
export interface WorldBookClassificationDTO {
  matched: number;
  unmatched_count: number;
  total: number;
  /** 结论采用了哪类线索 → 条目数（uid-prefix / group / name-suffix） */
  signals: Record<string, number>;
  categories: WorldBookClassificationCategoryDTO[];
  character_links: number;
  /** 未识别出类别的条目 UID（截断） */
  unmatched: string[];
  /** 各线索给出不同结论的条目 */
  conflicts: Array<{ uid: string; votes: Record<string, string> }>;
  unlinked_characters: string[];
  /** 将要写入的完整分类数组 */
  proposal: WorldBookCategoryDTO[];
  /**
   * 统一草稿补丁：分类 + 条目归属 + 角色关联。统一模式下「应用分类」把这份补丁
   * 并进草稿，与其它改动共用同一次保存，而不是绕过草稿直接写盘。
   */
  draft_patch?: {
    categories: WorldBookCategoryDTO[];
    entry_moves: Record<string, string>;
    entry_updates: Record<string, { category_id?: string; character_id?: string }>;
  } | null;
  apply: boolean;
  reason?: string;
}
export interface WorldBookClassificationAppliedDTO {
  classification: WorldBookClassificationDTO;
  book: WorldBookDetail;
}

export interface WorldBookScopePreviewDTO {
  scope: WorldBookScopeDTO;
  entry_count: number;
  full_entry_count: number;
  full_estimated_tokens: number;
  resolved_estimated_tokens: number;
  saved_estimated_tokens: number;
  saved_percent: number;
  breakdown: Record<string, { entry_count: number; estimated_tokens: number }>;
  source_expansions?: Array<{ entry_uid: string; name: string; max_depth: number; entries: Array<{ uid: string; name: string }> }>;
  warnings: string[];
  // ── v3 解释字段（未启用 v3 的书不返回）──
  schema_version?: number;
  resolver_version?: number;
  /** 本次会话是否显式选择「全量兼容」（只影响本会话） */
  full_scope?: boolean;
  active_roots?: WorldBookRootDTO[];
  resolved_edges?: Array<WorldBookDependencyEdgeDTO & { relation: string; active: boolean }>;
  selection_reasons?: Record<string, string[]>;
  display_tree?: WorldBookDisplayNodeDTO[];
  cross_references?: WorldBookDependencyEdgeDTO[];
  issues?: WorldBookIssueDTO[];
  /** 草稿指纹：创建会话时用它校验「预览与创建一致」 */
  draft_hash?: string;
  policy_revision?: number;
  content_revision?: string;
  manual_entry_uids?: string[];
  unselected_entries?: Array<{ uid: string; name: string; category_id: string }>;
  unselected_count?: number;
  entry_names?: Record<string, string>;
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
  book: WorldBookSummary | null;
  report: WorldBookImportReport;
  /** 角色卡导入时连带创建的角色（PNG/JSON 角色卡） */
  character?: { name: string; slug: string; path: string; source: string; has_avatar: boolean } | null;
}

/** 会话当前生效世界书查询结果 */
export interface WorldBookResolveResult {
  book: WorldBookSummary | null;
  default_book_id: string | null;
}

// ── 战斗节点编辑器（batch 2）─────────────────────────────────────────────────

/** 节点里的一波敌人条目 */
export interface BattleWaveEntryDTO {
  enemy: string;
  count: number;
  /** 声明站位；缺失会自动落到部署区空格 */
  positions?: [number, number][];
  /** 逐实例数值覆盖（如 {hp: 150}） */
  stats?: Record<string, number>;
}

export interface BattleWaveDTO {
  enemies: BattleWaveEntryDTO[];
}

/** 地图部署区写法（rect 为 [r0,c0,r1,c1] 对角；cells 为显式坐标） */
export interface DeployZoneDTO {
  rect?: [number, number, number, number];
  cells?: [number, number][];
}

export interface BattleMapDTO {
  rows: number;
  cols: number;
  /** 二维 tile_id 数组，或整图统一填充的字符串简写 */
  tiles: string[][] | string;
  tile_defs?: Record<string, Partial<TileTypeDTO>>;
  deploy?: {
    player?: DeployZoneDTO;
    enemy?: DeployZoneDTO;
    enemy_random_shift?: boolean;
  };
}

/** 战斗节点 JSON（与后端 data/combat/nodes/<id>.json 一一对应） */
export interface BattleNodeDTO {
  schema_version?: number;
  node_id: string;
  name: string;
  summary?: string;
  description?: string;
  bind?: { plot_id?: string; chapter_id?: string; beat_id?: string };
  rules?: { range_metric?: "manhattan" | "chebyshev"; allow_corner_cut?: boolean };
  map: BattleMapDTO;
  waves: BattleWaveDTO[];
  enemies_def?: Record<string, any>;
  conditions?: { max_rounds?: number; escape_enabled?: boolean };
  rewards?: { xp?: number; items?: string[]; unlock?: string[] };
  difficulty?: {
    category?: string; encounter_type?: string; band?: string;
    threat_budget?: number; target_rounds?: number; difficulty?: number;
  };
  background?: string;
  balance_version?: number;
  source?: { type?: string; book_id?: string; entry_uid?: string };
  /** 归属世界书（节点图按书组织；世界书导入的节点自动标注） */
  worldbook_id?: string;
  _hash?: string;
  warnings?: string[];
}

/** 节点列表行（含剧情节拍绑定与会话进度） */
export interface BattleNodeOverviewDTO {
  node_id: string;
  name: string;
  summary: string;
  rows: number | null;
  cols: number | null;
  wave_count: number;
  unit_total: number;
  bind: { plot_id?: string; chapter_id?: string; beat_id?: string };
  markers: { plot_id: string; chapter_id?: string; beat_id?: string }[];
  progress?: {
    state: "done" | "current" | "locked";
    plot_id: string;
    chapter_idx: number;
    chapter_title?: string;
    beat_id: string;
    beat_summary?: string;
  } | null;
  source_worldbook?: string;
  /** 归属世界书 id（空串 = 未标注） */
  worldbook_id?: string;
  hash?: string;
  /** 剧情引用了但注册表里还没有配置 → 编辑器可一键创建 */
  missing?: boolean;
}

/** 节点图剧情节拍（来自 data/plots/<id>/index.md 的叙述区） */
export interface PlotFlowBeatDTO {
  id: string;
  keep_on_deviate: boolean;
  summary: string;
  combat_nodes: string[];
}

/** 节点图剧情章节 */
export interface PlotFlowChapterDTO {
  idx: number;
  title: string;
  combat_nodes: string[];
  beats: PlotFlowBeatDTO[];
}

/** 节点图剧情流程（一个 plot = 一条横向分支） */
export interface PlotFlowDTO {
  plot_id: string;
  name: string;
  summary: string;
  worldbook_id: string;
  combat_nodes: string[];
  chapters: PlotFlowChapterDTO[];
}

/** 节点图数据（GET /api/combat/nodes/graph?book_id=） */
export interface CombatNodeGraphDTO {
  book_id: string;
  plots: PlotFlowDTO[];
  nodes: BattleNodeOverviewDTO[];
  meta: { plot: any; bindings: number; plot_count: number; node_count: number };
}

/** ── 剧情节点图（自由画布布局；保存为世界书条目 plot_graph_<plot_id>） ── */

export type PlotGraphNodeType = "plot" | "chapter" | "beat" | "combat" | "note";

/** 图节点：引用型节点（beat/combat）通过 ref 指向底层数据，note 承载自由文本 */
export interface PlotGraphNodeDTO {
  id: string;
  type: PlotGraphNodeType;
  title: string;
  content?: string;
  x: number;
  y: number;
  ref?: { chapter_idx?: number; beat_id?: string; node_id?: string } | null;
}

/** 有向连线（一个节点允许分出多条路线：from 可重复出现） */
export interface PlotGraphEdgeDTO {
  id: string;
  from: string;
  to: string;
}

/** 图文档（一剧情一张图，整图存入世界书条目） */
export interface PlotGraphDocDTO {
  schema_version: number;
  plot_id: string;
  title?: string;
  worldbook_id?: string;
  nodes: PlotGraphNodeDTO[];
  edges: PlotGraphEdgeDTO[];
  updated_at?: number;
}

/** 资产实体组（一个实体目录的图片集合；parent_dir = 上级目录，worldbook_id = 来源世界书） */
export interface AssetEntityGroupDTO {
  category: string;
  entity: string;
  entity_name: string;
  parent_dir: string;
  worldbook_id: string;
  images: {
    name: string;
    path: string;
    url: string;
    size: number;
    subdir: string;
    parent_dir?: string;
  }[];
}

/** 校验报告（只读，不阻断保存以外的行为） */
export interface ValidationReportDTO {
  errors: string[];
  warnings: string[];
}

/** 敌人图鉴条目 */
export interface EnemyCatalogEntryDTO {
  name: string;
  summary: string;
  race: string;
  faction: string;
  class: string;
  level: number;
  power_tier: string;
  role: string;
  action_slots: number;
  threat_points: number;
  ai_behavior: string;
  ai_skills: string[];
  drop_items: string[];
  drop_rate: number;
  xp_reward: number;
  derived_from_attributes: boolean;
  combat_stats: Record<string, number>;
}
