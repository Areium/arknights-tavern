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
  /** 是否为正在流式生成的叙述消息（气泡模式下流式期间先显示纯文本） */
  streaming?: boolean;
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
  hash?: string;
  /** 剧情引用了但注册表里还没有配置 → 编辑器可一键创建 */
  missing?: boolean;
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
