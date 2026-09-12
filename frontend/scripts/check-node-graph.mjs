/**
 * 节点图回归自检 —— 直接跑真实模块（graphModel / nodeFactory），不依赖浏览器。
 *
 * 用法（在 frontend/ 目录下）：
 *   node scripts/check-node-graph.mjs
 *
 * 覆盖：
 *   A. 坐标系换算往返（图内 ⇄ 屏幕）
 *   B. 节点拖拽严格跟手：任意缩放/平移下「屏幕位移 → 图内位移」与旧实现对照
 *   C. 「重置节点位置」基准 = 剧情结构默认布局：坐标命中、节点与连线保留、自由节点排到右侧
 *   D. 节点工厂：手动来源合并、id 唯一、挂接连线、上限保护、LLM 未接入时报 no_provider、超时/失败归类
 */
import { build } from "esbuild";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const combatDir = path.resolve(here, "../src/components/combat");

let failures = 0;
const ok = (name, cond, extra = "") => {
  if (cond) console.log(`  ✓ ${name}`);
  else { failures += 1; console.log(`  ✗ ${name} ${extra}`); }
};
const near = (a, b, eps = 1e-9) => Math.abs(a - b) <= eps;

/** 用 esbuild 把 TS 模块打成一个临时 ESM 文件后 import（真模块，不是重写实现） */
async function loadModules() {
  const dir = await mkdtemp(path.join(tmpdir(), "ng-check-"));
  const outfile = path.join(dir, "bundle.mjs");
  await build({
    stdin: {
      contents: 'export * from "./graphModel"; export * from "./nodeFactory";',
      resolveDir: combatDir,
      loader: "ts",
      sourcefile: "ng-check-entry.ts",
    },
    bundle: true, format: "esm", platform: "neutral", target: "es2020", outfile, logLevel: "silent",
  });
  const mod = await import(pathToFileURL(outfile).href);
  return { mod, cleanup: () => rm(dir, { recursive: true, force: true }) };
}

const { mod, cleanup } = await loadModules();
const {
  screenToWorld, worldToScreen, dragGrabOffset, dragWorldPos,
  resetNodePositions, nodeIdentity, importLayoutFromFlow,
  createNodes, registerNodeGenProvider, NodeGenError, listNodeGenProviders, NODE_W,
} = mod;

try {
  // ── A. 坐标换算 ──
  console.log("A. 坐标系换算往返");
  for (const view of [{ x: 0, y: 0, zoom: 1 }, { x: -320.5, y: 88.25, zoom: 0.25 }, { x: 1024, y: -640, zoom: 2 }, { x: 37, y: 12, zoom: 1.37 }]) {
    const w = { x: 123.5, y: -456.25 };
    const s = worldToScreen(w.x, w.y, view);
    const back = screenToWorld(s.x, s.y, view);
    ok(`往返一致 zoom=${view.zoom}`, near(back.x, w.x, 1e-9) && near(back.y, w.y, 1e-9), JSON.stringify(back));
  }

  // ── B. 拖拽跟手 ──
  console.log("B. 节点拖拽（屏幕偏移恒定参考系）");
  {
    const views = [
      { name: "100% 未平移", view: { x: 0, y: 0, zoom: 1 } },
      { name: "25% 且已平移", view: { x: -900, y: 300, zoom: 0.25 } },
      { name: "200% 且已平移", view: { x: 512, y: -256, zoom: 2 } },
    ];
    for (const { name, view } of views) {
      const node = { x: 400, y: 260 };
      // 在节点内部任意点按下（屏幕坐标）
      const grabScreen = worldToScreen(node.x + 40, node.y + 18, view);
      const grab = dragGrabOffset(grabScreen.x, grabScreen.y, node, view);
      // 指针依次移动若干帧：每帧节点屏幕位置应严格等于「指针屏幕位置 - 恒定偏移」
      let maxErr = 0;
      let nodePos = node;
      for (let i = 1; i <= 40; i++) {
        const pointer = { x: grabScreen.x + i * 7.5, y: grabScreen.y + i * -4.25 };
        nodePos = dragWorldPos(pointer.x, pointer.y, grab, view);
        const drawn = worldToScreen(nodePos.x, nodePos.y, view);
        maxErr = Math.max(maxErr, Math.abs(drawn.x - (pointer.x - grab.x)), Math.abs(drawn.y - (pointer.y - grab.y)));
      }
      ok(`${name}：40 帧内节点屏幕位置 = 指针 - 恒定偏移（误差 ${maxErr.toExponential(2)}）`, maxErr < 1e-9);
      const expected = { x: node.x + 300 / view.zoom, y: node.y + -170 / view.zoom };
      ok(`${name}：总位移 = 屏幕位移 / zoom`, near(nodePos.x, expected.x, 1e-9) && near(nodePos.y, expected.y, 1e-9),
        `got ${JSON.stringify(nodePos)} want ${JSON.stringify(expected)}`);
    }

    // 旧实现（每帧把总位移加到已被改写的坐标上）必然发散 —— 复现根因
    const view = { x: 0, y: 0, zoom: 1 };
    const node = { x: 400, y: 260 };
    const startW = { x: 440, y: 278 };              // 按下点（图内）
    let legacy = { x: node.x, y: node.y };
    for (let i = 1; i <= 40; i++) {
      const w = { x: startW.x + i * 7.5, y: startW.y + i * -4.25 };
      legacy = { x: Math.round(legacy.x + (w.x - startW.x)), y: Math.round(legacy.y + (w.y - startW.y)) };
    }
    const fixed = dragWorldPos(440 + 300, 278 - 170, dragGrabOffset(440, 278, node, view), view);
    ok(`旧实现 40 帧后偏离指针 ${Math.round(legacy.x - fixed.x)}px（新实现偏离 0px）`, legacy.x - fixed.x > 1000);
  }

  // ── C. 重置节点位置 ──
  console.log("C. 重置节点位置（基准 = 剧情结构默认布局）");
  {
    const plot = {
      plot_id: "p1", name: "测试剧情", summary: "", worldbook_id: "wb",
      combat_nodes: [],
      chapters: [
        { idx: 1, title: "雪原", combat_nodes: ["enc_a"], beats: [
          { id: "b1", summary: "开场", combat_nodes: [], keep_on_deviate: false },
          { id: "b2", summary: "伏击", combat_nodes: [], keep_on_deviate: false },
        ] },
        { idx: 2, title: "回城", combat_nodes: [], beats: [{ id: "b3", summary: "", combat_nodes: [], keep_on_deviate: false }] },
      ],
    };
    const layout = importLayoutFromFlow(plot, new Map([["enc_a", { name: "遭遇A" }]]));
    const posOf = (type, ref) => layout.nodes.find((n) => nodeIdentity(n) === nodeIdentity({ id: "x", type, ref }));
    // 用户把节点拖得到处都是 + 一个默认布局里没有的自由节点
    const doc = {
      schema_version: 1, plot_id: "p1", nodes: [
        { id: "n1", type: "plot", title: "测试剧情", x: -999, y: -999, ref: null },
        { id: "n2", type: "beat", title: "b1", x: 5000, y: 12, ref: { chapter_idx: 1, beat_id: "b1" } },
        { id: "n3", type: "combat", title: "遭遇A", x: 0, y: 7777, ref: { node_id: "enc_a" } },
        { id: "n4", type: "note", title: "笔记", x: 10, y: 10, ref: null },
      ],
      edges: [{ id: "e1", from: "n1", to: "n2" }, { id: "e2", from: "n2", to: "n3" }],
    };
    const r = resetNodePositions(doc, layout);
    const got = (id) => r.doc.nodes.find((n) => n.id === id);
    const want = (type, ref) => { const n = posOf(type, ref); return { x: n.x, y: n.y }; };
    ok("plot 节点回到默认布局坐标", JSON.stringify({ x: got("n1").x, y: got("n1").y }) === JSON.stringify(want("plot", null)),
      JSON.stringify({ x: got("n1").x, y: got("n1").y }));
    ok("beat 节点回到默认布局坐标", JSON.stringify({ x: got("n2").x, y: got("n2").y }) === JSON.stringify(want("beat", { chapter_idx: 1, beat_id: "b1" })));
    ok("combat 节点回到默认布局坐标", JSON.stringify({ x: got("n3").x, y: got("n3").y }) === JSON.stringify(want("combat", { node_id: "enc_a" })));
    ok("节点集合与连线全部保留（只改坐标）", r.doc.nodes.length === 4 && r.doc.edges.length === 2 && got("n2").title === "b1");
    ok("自由节点排到默认布局右侧空位", got("n4").x > Math.max(...layout.nodes.map((n) => n.x + NODE_W)), `x=${got("n4").x}`);
    ok("统计：matched=3 placed=1", r.matched === 3 && r.placed === 1, `matched=${r.matched} placed=${r.placed}`);
    ok("默认布局中未上图的项只统计不新增", r.missing >= 1 && r.doc.nodes.length === doc.nodes.length, `missing=${r.missing}`);
    ok("重复引用不会重叠（第二个 combat 引用排到空位）", (() => {
      const dup = { ...doc, nodes: [...doc.nodes, { id: "n5", type: "combat", title: "遭遇A", x: 1, y: 1, ref: { node_id: "enc_a" } }] };
      const rr = resetNodePositions(dup, layout);
      const a = rr.doc.nodes.find((n) => n.id === "n3"), b = rr.doc.nodes.find((n) => n.id === "n5");
      return a.x !== b.x || a.y !== b.y;
    })());
  }

  // ── D. 节点工厂 ──
  console.log("D. 节点工厂（统一生成入口）");
  {
    console.log(`  已注册提供方：${listNodeGenProviders().join(", ")}`);
    const doc = { schema_version: 1, plot_id: "p1", nodes: [{ id: "n_root", type: "plot", title: "入口", x: 0, y: 0, ref: null }], edges: [] };

    // D1 手动来源：落位 / 连线 / 挂接
    const r1 = await createNodes({
      source: "manual",
      position: { x: 300, y: 200, anchor: "center" },
      nodes: [{ type: "note", title: "笔记A" }, { type: "beat", title: "b1", ref: { chapter_idx: 1, beat_id: "b1" } }],
      edges: [{ from: 0, to: 1 }],
      options: { place: "chain", connect: "provide", attach: { fromNodeId: "n_root" }, maxNodes: 8 },
    }, doc);
    ok("返回合并后的文档（调用方直接 commit）", r1.doc.nodes.length === 3 && r1.doc.edges.length === 2);
    ok("新增节点带唯一 id 与合法坐标", r1.nodes.every((n) => n.id && Number.isFinite(n.x) && Number.isFinite(n.y)) && new Set(r1.doc.nodes.map((n) => n.id)).size === 3);
    ok("anchor=center 时按中心落位", r1.nodes[0].x === 300 - NODE_W / 2);
    ok("request.edges（下标端点）解析成内部连线", r1.edges.some((e) => e.from === r1.nodes[0].id && e.to === r1.nodes[1].id));
    ok("attach 把新节点接到已有节点", r1.edges.some((e) => e.from === "n_root"));
    ok("原有节点与文档字段未被改动", r1.doc.nodes[0].id === "n_root" && r1.doc.plot_id === "p1");

    // D2 上限保护 + 非法类型降级（不阻断）
    const r2 = await createNodes({ source: "manual", nodes: [{ type: "note" }, { type: "note" }, { type: "note" }], options: { maxNodes: 2 } }, doc);
    ok("maxNodes 上限生效并记入 warnings", r2.nodes.length === 2 && r2.meta.warnings.some((w) => w.includes("maxNodes")));
    const r3 = await createNodes({ source: "manual", nodes: [{ type: "bogus", title: "x" }] }, doc);
    ok("非法类型降级为 note 且给出 warning", r3.nodes[0].type === "note" && r3.meta.warnings.some((w) => w.includes("不合法")));

    // D3 必填校验
    await createNodes({ source: "manual", nodes: [] }, doc).then(
      () => ok("空 nodes 应报错", false),
      (e) => ok("手动来源缺 nodes → invalid_request", e instanceof NodeGenError && e.code === "invalid_request", e?.code),
    );

    // D4 LLM 未接入：调用方无需改代码，拿到结构化错误
    await createNodes({ source: "llm", prompt: "补一段伏击节拍" }, doc).then(
      () => ok("未注册 LLM 提供方应报错", false),
      (e) => ok("LLM 未接入 → no_provider（不伪装成成功）", e instanceof NodeGenError && e.code === "no_provider", e?.code),
    );

    // D5 注册一个假 LLM 提供方：验证「接入后调用方代码完全不变」
    registerNodeGenProvider({
      id: "llm-test", sources: ["llm"],
      generate: (req) => ({
        nodes: [{ type: "beat", title: `${req.prompt}-1` }, { type: "beat", title: `${req.prompt}-2` }],
        warnings: ["测试提供方"],
      }),
    });
    const r5 = await createNodes({
      source: "llm", prompt: "伏击", position: { x: 900, y: 100 },
      context: { plotId: "p1", existingNodes: doc.nodes }, options: { connect: "chain" },
    }, doc);
    ok("注册提供方后 source:'llm' 走同一 createNodes 路径", r5.nodes.length === 2 && r5.edges.length === 1 && r5.meta.provider === "llm-test");
    ok("meta 带来源/耗时/warnings", r5.meta.source === "llm" && Number.isFinite(r5.meta.elapsedMs) && r5.meta.warnings.length >= 1);

    // D6 超时归类
    registerNodeGenProvider({
      id: "llm-slow", sources: ["layout"],
      generate: (_req, ctx) => new Promise((_res, rej) => {
        ctx.signal.addEventListener("abort", () => rej(new Error("aborted")), { once: true });
      }),
    });
    const t0 = Date.now();
    await createNodes({ source: "layout", nodes: [{ type: "note" }], timeoutMs: 120 }, doc).then(
      () => ok("超时应报错", false),
      (e) => ok("超时 → timeout（含耗时保护）", e instanceof NodeGenError && e.code === "timeout" && Date.now() - t0 < 2000, `${e?.code} ${Date.now() - t0}ms`),
    );

    // D7 提供方抛错归类 + 结果结构不合法归类
    registerNodeGenProvider({ id: "llm-bad", sources: ["layout"], generate: () => { throw new Error("boom"); } });
    await createNodes({ source: "layout", nodes: [{ type: "note" }] }, doc).then(
      () => ok("提供方抛错应报错", false),
      (e) => ok("提供方抛错 → provider_failed", e instanceof NodeGenError && e.code === "provider_failed", e?.code),
    );
    registerNodeGenProvider({ id: "llm-shape", sources: ["layout"], generate: () => ({ nodes: "nope" }) });
    await createNodes({ source: "layout", nodes: [{ type: "note" }] }, doc).then(
      () => ok("非法结果应报错", false),
      (e) => ok("返回结构不合法 → invalid_result", e instanceof NodeGenError && e.code === "invalid_result", e?.code),
    );
  }
} finally {
  await cleanup();
}

console.log(failures === 0 ? "\n全部通过 ✅" : `\n失败 ${failures} 项 ❌`);
process.exit(failures === 0 ? 0 : 1);
