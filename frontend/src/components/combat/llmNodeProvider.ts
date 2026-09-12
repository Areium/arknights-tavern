/**
 * LLM 节点提供方 —— 骨架实现（**当前不发起真实 LLM 调用**，只固定接入契约）。
 *
 * 为什么要单独一层：节点工厂（nodeFactory.ts）已经定好「输入 / 输出 / 异步 / 失败 / 超时」
 * 的通道，本文件只负责「把请求发给模型、把模型结果翻译成节点规格」。接入真实模型时：
 *   1) 实现或替换 LlmNodeGenTransport（fetch / electron IPC / 既有后端 LLM 接口皆可）；
 *   2) 在应用启动处调用一次 registerLlmNodeGen(transport)；
 * 之后所有调用方（PlotGraphPage / GraphCanvas / 未来的工具栏按钮）都无需改动 ——
 * 它们调用的仍是 createNodes({ source: "llm", prompt, position, context }, doc)。
 *
 * 错误约定：传输层抛出的错误由工厂归类为 provider_failed / timeout / aborted；
 * 本层只负责把「模型返回了但结构不对」的情况标成 invalid_result（绝不当成成功结果）。
 */
import type {
  NodeGenEdgeSpec, NodeGenNodeSpec, NodeGenProvider, NodeGenProviderContext, NodeGenRequest,
} from "./nodeFactory";
import { NodeGenError, registerNodeGenProvider } from "./nodeFactory";

export const LLM_NODE_PROVIDER_ID = "llm";

/** 发给模型的载荷（后端据此拼系统提示词：剧情结构 / 现有节点 / 世界书条目…） */
export interface LlmNodeGenPayload {
  prompt: string;
  plot_id?: string;
  book_id?: string;
  context: NonNullable<NodeGenRequest["context"]>;
  options: NonNullable<NodeGenRequest["options"]>;
}

/** 模型返回的原始结果（节点规格与连线规格，id/坐标由工厂补齐） */
export interface LlmNodeGenResponse {
  nodes: NodeGenNodeSpec[];
  edges?: NodeGenEdgeSpec[];
  /** 模型自述的降级说明（如「信息不足，只生成了 2 个节点」） */
  warnings?: string[];
}

/** 传输层：任何把 payload 变成 response 的方式（HTTP / IPC / 直接调本地 SDK） */
export interface LlmNodeGenTransport {
  /** 必须透传 signal：工厂用它在超时/取消时中断底层请求 */
  generate(payload: LlmNodeGenPayload, init: { signal: AbortSignal }): Promise<LlmNodeGenResponse>;
}

export function createLlmNodeGenProvider(transport: LlmNodeGenTransport): NodeGenProvider {
  return {
    id: LLM_NODE_PROVIDER_ID,
    sources: ["llm"],
    async generate(req: NodeGenRequest, ctx: NodeGenProviderContext): Promise<LlmNodeGenResponse> {
      const prompt = req.prompt?.trim();
      if (!prompt) throw new NodeGenError("invalid_request", "LLM 生成缺少 prompt", { provider: LLM_NODE_PROVIDER_ID });
      const res = await transport.generate(
        {
          prompt,
          plot_id: req.context?.plotId,
          book_id: req.context?.bookId,
          context: { ...req.context, existingNodes: req.context?.existingNodes ?? ctx.doc.nodes },
          options: req.options ?? {},
        },
        { signal: ctx.signal },
      );
      if (!res || !Array.isArray(res.nodes)) {
        throw new NodeGenError("invalid_result", "LLM 返回结构不合法（缺少 nodes 数组）", {
          provider: LLM_NODE_PROVIDER_ID,
          detail: res,
        });
      }
      return res;
    },
  };
}

/**
 * 一行接入：应用启动处调用 registerLlmNodeGen(transport) 即可让 source:"llm" 生效。
 * 未调用时，createNodes({ source: "llm" }) 会抛 NodeGenError("no_provider")——这是预期行为，
 * 调用方按 code 提示「LLM 生成尚未接入」，而不是静默失败。
 */
export function registerLlmNodeGen(transport: LlmNodeGenTransport): void {
  registerNodeGenProvider(createLlmNodeGenProvider(transport));
}

/**
 * HTTP 传输层骨架：接口路径与字段尚未与后端对齐，**默认不注册、不调用**。
 * 后端接口确定后：核对 endpoint / 字段名（必要时改 payload 映射）→ registerLlmNodeGen(createHttpLlmNodeGenTransport())
 */
export function createHttpLlmNodeGenTransport(
  opts: { endpoint?: string; fetchImpl?: typeof fetch } = {},
): LlmNodeGenTransport {
  const endpoint = opts.endpoint ?? "/api/plot-graph/generate-nodes";
  return {
    async generate(payload, init) {
      const doFetch = opts.fetchImpl ?? fetch;
      const resp = await doFetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: init.signal,
      });
      if (!resp.ok) {
        throw new Error(`LLM 节点生成接口失败：HTTP ${resp.status}`);
      }
      return (await resp.json()) as LlmNodeGenResponse;
    },
  };
}
