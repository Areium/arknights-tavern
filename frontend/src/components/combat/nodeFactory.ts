/**
 * 节点工厂 —— 剧情节点图**唯一的节点生成入口**（创建 API）。
 *
 * 目标：调用方只描述「要什么节点、放在哪、怎么连」，不关心节点从哪来。
 *   - 手动创建（自由节点 / 战斗节点 / 剧情节拍引用 / 锚点拖出的分支）
 *   - LLM 生成（source:"llm"，由提供方实现；本文件只预留契约与异步/失败/超时通道）
 *   - 以后新增来源（模板、导入、批量脚本…）只需注册一个 NodeGenProvider。
 *
 * 调用方代码（示例，接入 LLM 前后完全一致）：
 *   const res = await createNodes({
 *     source: "llm",
 *     prompt: "为「风雪过境」补一段雪原伏击的节拍链",
 *     position: { x, y, anchor: "center" },
 *     context: { plotId, bookId, plot, existingNodes: doc.nodes },
 *     options: { maxNodes: 6, connect: "chain" },
 *   }, doc);
 *   commit(res.doc);                     // res.doc 已合并好节点与连线
 *
 * 分工：提供方只产出「节点规格」；id 生成、坐标落位、连线解析、文档合并、
 * 结果校验统一由本文件负责 —— 这样任何来源产出的结果都满足同一套图文档约束。
 */
import type {
  PlotFlowDTO, PlotGraphDocDTO, PlotGraphEdgeDTO, PlotGraphNodeDTO, PlotGraphNodeType,
} from "../../types";
import { LAYOUT_H_GAP, NODE_META, NODE_TYPE_ORDER, NODE_W, estimateNodeH, genId } from "./graphModel";

// ── 输入定义（可扩展：未知字段一律透传给提供方） ──

export type NodeSource = "manual" | "layout" | "llm";

/** 生成上下文：手动路径可省略；LLM 路径通常需要剧情结构 + 现有图（避让/去重） */
export interface NodeGenContext {
  plotId?: string;
  bookId?: string;
  /** 剧情结构（章节 / 节拍 / 战斗引用），LLM 生成的重要依据 */
  plot?: PlotFlowDTO | null;
  /** 现有图节点（提供方用于避让与去重） */
  existingNodes?: PlotGraphNodeDTO[];
  /** 尚未上图的剧情节拍 */
  availableBeats?: { chapterIdx: number; beatId: string; label: string }[];
  /** 尚未上图的战斗节点 */
  availableCombats?: { nodeId: string; label: string }[];
  sessionId?: string | null;
  /** 预留：世界书条目 / 记忆 / 玩家进度等任意附加上下文 */
  extra?: Record<string, unknown>;
}

/** 落点语义：topleft = position 指节点左上角；center = position 指节点中心 */
export type NodePlaceAnchor = "topleft" | "center";

export interface NodeGenNodeSpec {
  /** 缺省 note；非法类型会被丢弃并记入 warnings */
  type?: PlotGraphNodeType;
  title?: string;
  content?: string;
  ref?: PlotGraphNodeDTO["ref"];
  /** 单个节点的显式坐标（图内坐标，左上角） */
  x?: number;
  y?: number;
  /** 可选稳定 id（如按 beat_id 派生）；缺省由工厂生成并保证唯一 */
  id?: string;
  /** 预留：提供方附加信息（模型名 / 置信度 / 来源提示词…），不写入图文档 */
  meta?: Record<string, unknown>;
}

/** 连线端点：字符串 = 已有节点 id 或本次生成节点的 id；数字 = 本次生成节点的下标 */
export interface NodeGenEdgeSpec { from: string | number; to: string | number }

export interface NodeGenOptions {
  /** 位置策略：at=放在 position（多节点轻微错开）；chain=自 position 起向右串联；auto=提供方自定 */
  place?: "at" | "chain" | "auto";
  /** 连线策略：provide=只用 request.edges；chain=新节点按序串联；none=不连 */
  connect?: "none" | "chain" | "provide";
  /** 把新节点接到已有节点上（如从某节点锚点拖出的分支） */
  attach?: { fromNodeId?: string; toNodeId?: string };
  anchor?: NodePlaceAnchor;
  /** 上限保护（超出的节点被丢弃并记入 warnings） */
  maxNodes?: number;
  /** 预留：透传给提供方的自定义参数 */
  [key: string]: unknown;
}

export interface NodeGenRequest {
  source: NodeSource;
  /** 目标位置（图内坐标）；anchor 决定该点代表节点左上角还是中心（缺省 topleft） */
  position?: { x: number; y: number; anchor?: NodePlaceAnchor };
  /** 提示词（source:"llm" 必填） */
  prompt?: string;
  context?: NodeGenContext;
  /** 手动 / 布局来源：直接给出节点与连线 */
  nodes?: NodeGenNodeSpec[];
  edges?: NodeGenEdgeSpec[];
  options?: NodeGenOptions;
  /** 超时毫秒数；缺省 DEFAULT_TIMEOUT_MS（LLM 接入后通常调大） */
  timeoutMs?: number;
  /** 外部取消（组件卸载 / 用户点取消） */
  signal?: AbortSignal;
}

// ── 输出定义 ──

export interface NodeGenMeta {
  source: NodeSource;
  provider: string;
  elapsedMs: number;
  /** 被丢弃/降级的项（调用方可提示用户，不阻断生成） */
  warnings: string[];
}

export interface NodeGenResult {
  /** 已合并进现有文档的结果：调用方直接 commit(doc) 即可（一次提交 = 一步撤销） */
  doc: PlotGraphDocDTO;
  /** 本次新增的节点（含最终 id 与坐标） */
  nodes: PlotGraphNodeDTO[];
  /** 本次新增的连线（含新节点 → 已有节点的连线） */
  edges: PlotGraphEdgeDTO[];
  meta: NodeGenMeta;
}

export type NodeGenErrorCode =
  | "no_provider"      // 该来源还没有提供方（LLM 尚未接入时的正常路径）
  | "invalid_request"  // 请求本身不合法
  | "invalid_result"   // 提供方返回的数据不合法
  | "timeout"
  | "aborted"
  | "provider_failed";

export class NodeGenError extends Error {
  readonly code: NodeGenErrorCode;
  readonly provider?: string;
  readonly detail?: unknown;

  constructor(code: NodeGenErrorCode, message: string, opts?: { provider?: string; detail?: unknown }) {
    super(message);
    this.name = "NodeGenError";
    this.code = code;
    this.provider = opts?.provider;
    this.detail = opts?.detail;
  }
}

// ── 提供方契约（LLM 接入点） ──

export interface NodeGenProviderContext {
  /** 现有图文档（避让 / 去重 / 决定挂接点） */
  doc: PlotGraphDocDTO;
  /** 超时与取消信号：提供方应把它透传给网络请求 */
  signal: AbortSignal;
  timeoutMs: number;
}

/** 提供方只产出规格，不碰 id / 坐标落位 / 文档合并 */
export interface NodeGenProviderOutput {
  nodes: NodeGenNodeSpec[];
  edges?: NodeGenEdgeSpec[];
  warnings?: string[];
}

export interface NodeGenProvider {
  id: string;
  /** 该提供方接管哪些来源 */
  sources: NodeSource[];
  generate(req: NodeGenRequest, ctx: NodeGenProviderContext): Promise<NodeGenProviderOutput> | NodeGenProviderOutput;
}

export const DEFAULT_TIMEOUT_MS = 8000;

const providers: NodeGenProvider[] = [];

/** 注册提供方：同 id 覆盖；同来源后注册者优先（后接入的真实实现可顶掉占位实现） */
export function registerNodeGenProvider(provider: NodeGenProvider): void {
  const idx = providers.findIndex((p) => p.id === provider.id);
  if (idx >= 0) providers[idx] = provider;
  else providers.push(provider);
}

export function listNodeGenProviders(): string[] {
  return providers.map((p) => p.id);
}

/** 解析提供方：从后往前找，保证后注册的实现接管它声明的来源 */
export function resolveNodeGenProvider(source: NodeSource): NodeGenProvider | null {
  for (let i = providers.length - 1; i >= 0; i--) {
    if (providers[i].sources.includes(source)) return providers[i];
  }
  return null;
}

// ── 手动来源的提供方（现有全部手动创建入口都走这里） ──

export const manualNodeGenProvider: NodeGenProvider = {
  id: "manual",
  sources: ["manual"],
  generate: (req) => ({ nodes: req.nodes ?? [], edges: req.edges, warnings: [] }),
};

providers.push(manualNodeGenProvider);

// ── 统一入口 ──

/**
 * 唯一的节点生成 API：异步、可超时、可取消，任何来源都从这里进。
 * 抛出的 NodeGenError 带 code，调用方可按 code 决定提示文案（不要把错误伪装成成功结果）。
 */
export async function createNodes(req: NodeGenRequest, doc: PlotGraphDocDTO): Promise<NodeGenResult> {
  const source = req.source;
  if (!source) throw new NodeGenError("invalid_request", "缺少 source：无法确定节点来源");
  if (source === "manual" && (!req.nodes || req.nodes.length === 0)) {
    throw new NodeGenError("invalid_request", "手动来源必须提供 nodes", { provider: "manual" });
  }
  if (source === "llm" && !req.prompt?.trim()) {
    throw new NodeGenError("invalid_request", "LLM 来源必须提供 prompt", { provider: "llm" });
  }

  const provider = resolveNodeGenProvider(source);
  if (!provider) {
    throw new NodeGenError(
      "no_provider",
      `尚未注册「${source}」来源的节点提供方（已注册：${listNodeGenProviders().join(", ") || "无"}）`,
      { provider: source },
    );
  }

  const timeoutMs = Number.isFinite(req.timeoutMs) && (req.timeoutMs as number) > 0
    ? (req.timeoutMs as number)
    : DEFAULT_TIMEOUT_MS;
  const started = now();
  const { signal, dispose } = createDeadline(timeoutMs, req.signal, provider.id);

  let out: NodeGenProviderOutput;
  try {
    out = await provider.generate(req, { doc, signal, timeoutMs });
  } catch (e) {
    dispose();
    if (e instanceof NodeGenError) throw e;
    // 超时 / 外部取消 / 提供方自身异常：分门别类抛出，便于调用方分别处理
    if (signal.aborted) {
      throw new NodeGenError(
        req.signal?.aborted ? "aborted" : "timeout",
        req.signal?.aborted ? "节点生成已取消" : `节点生成超时（${timeoutMs}ms）`,
        { provider: provider.id, detail: e },
      );
    }
    throw new NodeGenError("provider_failed", `节点提供方「${provider.id}」执行失败`, { provider: provider.id, detail: e });
  }
  dispose();

  if (!out || !Array.isArray(out.nodes)) {
    throw new NodeGenError("invalid_result", `节点提供方「${provider.id}」未返回 nodes`, { provider: provider.id, detail: out });
  }

  const result = buildNodes(req, out, doc, {
    source,
    provider: provider.id,
    elapsedMs: Math.round(now() - started),
    warnings: [...(out.warnings ?? [])],
  });
  if (result.nodes.length === 0) {
    throw new NodeGenError("invalid_result", `节点提供方「${provider.id}」没有产出有效节点`, {
      provider: provider.id,
      detail: result.meta.warnings,
    });
  }
  return result;
}

const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());

/** 统一把「超时」与「外部取消」合成一个 AbortSignal（提供方只需监听它） */
function createDeadline(timeoutMs: number, outer: AbortSignal | undefined, providerId: string) {
  const ctrl = new AbortController();
  const onAbort = () => ctrl.abort(outer?.reason);
  if (outer) {
    if (outer.aborted) ctrl.abort(outer.reason);
    else outer.addEventListener("abort", onAbort, { once: true });
  }
  const timer = setTimeout(() => ctrl.abort(new NodeGenError("timeout", `${providerId} 超时`, { provider: providerId })), timeoutMs);
  return {
    signal: ctrl.signal,
    dispose: () => {
      clearTimeout(timer);
      outer?.removeEventListener("abort", onAbort);
    },
  };
}

/**
 * 纯函数：把提供方产出的规格落成图节点并合并进现有文档。
 * 手动路径同样走这里 —— 保证「id 唯一 / 坐标合法 / 上限保护 / 连线可解析」在所有来源上一致。
 */
export function buildNodes(
  req: NodeGenRequest,
  out: NodeGenProviderOutput,
  doc: PlotGraphDocDTO,
  meta: NodeGenMeta,
): NodeGenResult {
  const options: NodeGenOptions = { ...req.options };
  const place = options.place === "chain" ? "chain" : "at";
  const anchor: NodePlaceAnchor = req.position?.anchor ?? options.anchor ?? "topleft";
  const maxNodes = Number.isFinite(options.maxNodes) ? Math.max(1, options.maxNodes as number) : Infinity;

  const origin = req.position ?? autoOrigin(doc);
  const specs = out.nodes.slice(0, maxNodes === Infinity ? out.nodes.length : maxNodes);
  if (specs.length < out.nodes.length) {
    meta.warnings.push(`超出上限 maxNodes=${maxNodes}，已丢弃 ${out.nodes.length - specs.length} 个节点`);
  }

  // working = 增量合并中的文档（id 去重与连线去重都基于它，避免与 doc 分叉）
  let working = doc;
  const nodes: PlotGraphNodeDTO[] = [];

  specs.forEach((spec, i) => {
    const raw = spec.type as string | undefined;
    const type: PlotGraphNodeType = raw && (NODE_TYPE_ORDER as string[]).includes(raw) ? (raw as PlotGraphNodeType) : "note";
    if (raw && type !== raw) meta.warnings.push(`节点类型「${raw}」不合法，已降级为 note`);
    const content = spec.content ?? "";
    const x = Number.isFinite(spec.x) ? (spec.x as number) : place === "chain" ? origin.x + i * (NODE_W + LAYOUT_H_GAP) : origin.x + i * 28;
    const y = Number.isFinite(spec.y) ? (spec.y as number) : place === "chain" ? origin.y : origin.y + i * 28;
    const node: PlotGraphNodeDTO = {
      id: allocateId(spec.id, working),
      type,
      title: spec.title?.trim() || NODE_META[type].label,
      content,
      x: Math.round(anchor === "center" ? x - NODE_W / 2 : x),
      y: Math.round(anchor === "center" ? y - estimateNodeH({ id: "", type, title: "", content, x: 0, y: 0 }) / 2 : y),
      ref: spec.ref ?? null,
    };
    nodes.push(node);
    working = { ...working, nodes: [...working.nodes, node] };
  });

  const specEdges = out.edges ?? req.edges ?? [];
  const connect = options.connect ?? (specEdges.length > 0 ? "provide" : "none");
  const edges: PlotGraphEdgeDTO[] = [];
  const edgeKeys = new Set(working.edges.map((e) => `${e.from}->${e.to}`));

  const resolve = (end: string | number): string | null => {
    if (typeof end === "number") return nodes[end]?.id ?? null;
    if (working.nodes.some((n) => n.id === end)) return end;
    meta.warnings.push(`连线端点「${end}」不存在，已忽略该连线`);
    return null;
  };
  const link = (from: string | number, to: string | number) => {
    const a = resolve(from), b = resolve(to);
    if (!a || !b) return;
    if (a === b) { meta.warnings.push("连线两端为同一节点，已忽略"); return; }
    const key = `${a}->${b}`;
    if (edgeKeys.has(key)) return;
    edgeKeys.add(key);
    const edge: PlotGraphEdgeDTO = { id: genId("e", working), from: a, to: b };
    edges.push(edge);
    working = { ...working, edges: [...working.edges, edge] };
  };

  if (connect === "provide") specEdges.forEach((e) => link(e.from, e.to));
  else if (connect === "chain") nodes.forEach((n, i) => { if (i > 0) link(nodes[i - 1].id, n.id); });
  if (nodes.length > 0 && options.attach?.fromNodeId) link(options.attach.fromNodeId, nodes[0].id);
  if (nodes.length > 0 && options.attach?.toNodeId) link(nodes[nodes.length - 1].id, options.attach.toNodeId);

  return { doc: working, nodes, edges, meta };
}

/** id：优先用规格里给的稳定 id，冲突或缺失则按图内已有 id 生成唯一 id */
function allocateId(preferred: string | undefined, working: PlotGraphDocDTO): string {
  const base = preferred?.trim();
  if (base && !working.nodes.some((n) => n.id === base)) return base;
  return genId("n", working);
}

/** 未给 position 时的兜底落点：现有图包围盒右侧一列（不与既有节点重叠） */
function autoOrigin(doc: PlotGraphDocDTO): { x: number; y: number } {
  if (doc.nodes.length === 0) return { x: 0, y: 0 };
  let maxX = -Infinity, minY = Infinity;
  for (const n of doc.nodes) {
    maxX = Math.max(maxX, n.x + NODE_W);
    minY = Math.min(minY, n.y);
  }
  return { x: Math.round(maxX + LAYOUT_H_GAP * 2), y: Math.round(minY) };
}
