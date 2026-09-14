// 不启动浏览器：检验分类树工具和真实 React 组件的服务端渲染结构。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");
const root = path.resolve(__dirname, "..");
const fromFrontend = createRequire(path.join(root, "frontend/package.json"));
const ts = fromFrontend("typescript");
require.extensions[".css"] = () => {};
for (const extension of [".ts", ".tsx"]) {
  require.extensions[extension] = (module, filename) => {
    const { outputText } = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 },
    });
    module._compile(outputText, filename);
  };
}
const React = fromFrontend("react");
const { renderToStaticMarkup } = fromFrontend("react-dom/server");
const { categoryDescendants, flattenCategoryTree } = require(path.join(root, "frontend/src/utils/worldbookScope.ts"));
const { buildWorldBookGraph, layoutWorldBookGraph, spreadWorldBookGraph, worldBookEdgeGeometry, entryNodeId, categoryNodeId } = require(path.join(root, "frontend/src/utils/worldbookGraph.ts"));
const ScopeManager = require(path.join(root, "frontend/src/components/WorldBookScopeManager.tsx")).default;
const Preview = require(path.join(root, "frontend/src/components/WorldBookScopePreview.tsx")).default;
const categories = [
  { id: "world", name: "世界观", parent_id: null, scope_type: "worldview", sort_order: 1 },
  { id: "characters", name: "角色", parent_id: null, scope_type: "character", sort_order: 2 },
  { id: "rhodes", name: "罗德岛", parent_id: "characters", scope_type: "character", sort_order: 1 },
  { id: "squad", name: "小队", parent_id: "rhodes", scope_type: "character", sort_order: 1 },
];
assert.deepEqual([...categoryDescendants(categories, "characters")], ["characters", "rhodes", "squad"]);
assert.deepEqual(flattenCategoryTree(categories).map((row) => row.level), [0, 0, 1, 2]);
assert.equal(categoryDescendants([{ id: "a", parent_id: "b" }, { id: "b", parent_id: "a" }], "a").size, 2);
const detail = { id: "qa", name: "结构验收", categories, entries: [
  { uid: "world", name: "世界设定", category_id: "world", enabled: true, trigger_keys: [] },
  { uid: "amiya", name: "阿米娅", category_id: "squad", character_id: "阿米娅", enabled: true, trigger_keys: [] },
], scope_mode: "selective", dependency_edges: [{ from_uid: "amiya", to_uid: "world" }],
import_config: { revision: 1, fixed_entry_uids: ["world"], dependency_sources: [{ entry_uid: "amiya", max_depth: 2 }] } };
const policy = { ...detail.import_config, dependency_edges: detail.dependency_edges, scope_mode: detail.scope_mode };
const untouched = JSON.stringify(detail);
const data = buildWorldBookGraph(detail, policy, { view: "dependencies" });
assert.equal(data.entryCount, 2);
assert.equal(data.edges.filter((edge) => edge.kind === "dependency").length, 1);
assert.notEqual(entryNodeId("world"), categoryNodeId("world"), "category IDs and entry UIDs are separate namespaces");
assert.equal(data.nodes.find((node) => node.id === entryNodeId("world")).fixed, true);
const taxonomyData = buildWorldBookGraph(detail, policy, { view: "taxonomy", categoryId: "characters" });
assert.equal(taxonomyData.entryCount, 1);
assert.equal(taxonomyData.edges.filter((edge) => edge.kind === "dependency").length, 0);
assert.equal(buildWorldBookGraph(detail, policy, { view: "dependencies", query: "阿米娅" }).entryCount, 1);
assert.equal(buildWorldBookGraph(detail, policy, { view: "dependencies", query: "no-such-entry" }).nodes.length, 0);
const positions = layoutWorldBookGraph(data);
assert.deepEqual(positions, layoutWorldBookGraph(data), "layout must be deterministic");
assert.equal(Object.keys(positions).length, data.nodes.length);
assert.ok(Object.values(positions).every((point) => Number.isFinite(point.x) && Number.isFinite(point.y)));
assert.deepEqual(layoutWorldBookGraph({ nodes: [], edges: [] }), {});
const wide = spreadWorldBookGraph({ a: { x: -10, y: -40 }, b: { x: 10, y: 40 } }, 2);
assert.ok(wide.b.x - wide.a.x > 20);
assert.equal(wide.b.y, 40);
assert.deepEqual(spreadWorldBookGraph({}, 2), {});
const forward = worldBookEdgeGeometry({ x: 0, y: 0 }, { x: 200, y: 0 }, 25, 25, true);
const backward = worldBookEdgeGeometry({ x: 200, y: 0 }, { x: 0, y: 0 }, 25, 25, true);
assert.ok(forward.label.y > 0 && backward.label.y < 0, "reciprocal dependencies need separate arcs");
const zeroDepth = buildWorldBookGraph(detail, { ...policy, dependency_sources: [{ entry_uid: "amiya", max_depth: 0 }] }, { view: "dependencies" });
assert.equal(zeroDepth.nodes.find((node) => node.id === entryNodeId("amiya")).sourceDepth, 0);
const large = { ...detail, entries: Array.from({ length: 450 }, (_, i) => ({ uid: "entry-" + i, name: "条目 " + i, category_id: "world", enabled: true })) };
const bounded = buildWorldBookGraph(large, { ...policy, dependency_sources: [], fixed_entry_uids: [], dependency_edges: [] }, { view: "dependencies", focusedUid: "entry-449" });
assert.equal(bounded.entryCount, 400);
assert.equal(bounded.hiddenCount, 50);
assert.ok(bounded.nodes.some((node) => node.refId === "entry-449"), "selected entries remain visible in bounded graphs");
const started = performance.now();
assert.equal(Object.keys(layoutWorldBookGraph(bounded)).length, bounded.nodes.length);
const layoutMs = Math.round(performance.now() - started);
assert.equal(JSON.stringify(detail), untouched, "graph layout must not mutate book policy");
const graph = renderToStaticMarkup(React.createElement(ScopeManager, { detail, onChanged() {} }));
for (const expected of ["固定导入区", "世界书有向依赖图", "marker-end", "wbg-node-disc", "缩小图谱", "重新布局图谱", "导入预览"]) assert.ok(graph.includes(expected), expected);
assert.ok(!graph.includes("<fieldset"), "edit forms stay in a contextual inspector, not above the graph");
const taxonomy = renderToStaticMarkup(React.createElement(ScopeManager, { detail, view: "taxonomy", onChanged() {} }));
for (const expected of ["分类树", "小队", "世界书分类关系图", "选择分类 罗德岛", "打开内容中心"]) assert.ok(taxonomy.includes(expected), expected);
const preview = renderToStaticMarkup(React.createElement(Preview, { value: {
  scope: { resolved_entry_uids: ["a"], legacy_full_scope: false, excluded_entries: [{ uid: "x", name: "停用节点", reason: "已停用" }] },
  entry_count: 1, full_entry_count: 10, full_estimated_tokens: 1000, resolved_estimated_tokens: 100,
  saved_estimated_tokens: 900, saved_percent: 90, breakdown: { roster: { entry_count: 1, estimated_tokens: 100 } }, warnings: [],
} }));
assert.ok(preview.includes("不是每轮实际节省量") && preview.includes("停用节点"));
console.log("Worldbook UI: taxonomy, graph filtering/IDs/layout/reciprocal edges, SSR controls, and preview passed. Large layout: " + layoutMs + "ms.");
