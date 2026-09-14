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
const {
  buildDependencyTree, classifyDependencyRoles, defaultTreeDepthLimit, dependencyDescendants, dependencyPath, layoutDependencyTree,
} = require(path.join(root, "frontend/src/utils/worldbookDependency.ts"));
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

// ── 依赖角色分类与依赖树 ────────────────────────────────────────────────────
// A/B 为导入源；X 同时被两个源到达（取更大的剩余深度，父节点归 A）；
// Z→X 与 X→Y→Z 构成三节点环，Y→Z 因深度用尽不会展开；Z 不可达；L 完全未配置。
const depCategories = [
  { id: "world", name: "世界观", parent_id: null, scope_type: "worldview", sort_order: 1 },
  { id: "characters", name: "角色", parent_id: null, scope_type: "character", sort_order: 2 },
];
const depEntries = [["A", "world"], ["B", "world"], ["F", "world"], ["X", "characters"],
  ["Y", "characters"], ["Z", "characters"], ["W", "characters"], ["L", "world"]]
  .map(([uid, category_id]) => ({ uid, name: uid + " 条目", category_id, enabled: true, trigger_keys: [] }));
const depDetail = {
  id: "dep", name: "依赖树验收", categories: depCategories, entries: depEntries, scope_mode: "selective",
  dependency_edges: [
    { from_uid: "A", to_uid: "X" }, { from_uid: "X", to_uid: "Y" }, { from_uid: "Y", to_uid: "Z" },
    { from_uid: "Z", to_uid: "X" }, { from_uid: "A", to_uid: "F" }, { from_uid: "B", to_uid: "X" }, { from_uid: "B", to_uid: "W" },
  ],
  import_config: { revision: 3, fixed_entry_uids: ["F"], dependency_sources: [{ entry_uid: "A", max_depth: 2 }, { entry_uid: "B", max_depth: 1 }] },
};
const depPolicy = { ...depDetail.import_config, dependency_edges: depDetail.dependency_edges, scope_mode: depDetail.scope_mode };
const depUntouched = JSON.stringify(depDetail);
const roles = classifyDependencyRoles(depDetail, depPolicy);
assert.deepEqual(Object.fromEntries(roles), {
  A: "source", B: "source", F: "fixed", X: "bridge", Y: "bridge", Z: "bridge", W: "leaf", L: "orphan",
});
const tree = buildDependencyTree(depDetail, depPolicy);
assert.deepEqual(tree.roots, ["A", "B"]);
assert.deepEqual([...tree.reachable].sort(), ["A", "B", "F", "W", "X", "Y"]);
assert.deepEqual([...tree.loose].sort(), ["L", "Z"], "未配置与不可达条目都要落进未覆盖带");
assert.deepEqual(tree.fixedOnly, [], "F 已被展开，不再算固定但未覆盖");
assert.deepEqual(tree.cycleUids.sort(), ["X", "Y", "Z"]);
assert.deepEqual(tree.stats, {
  sourceCount: 2, fixedCount: 1, reachableCount: 6, looseCount: 2, fixedOnlyCount: 0, maxDepth: 2,
  activeEdges: 5, cappedEdges: 1, idleEdges: 1, loopEdges: 3, cycleCount: 3, depthCounts: [2, 3, 1],
});
const at = (uid) => tree.byUid.get(uid);
assert.deepEqual([at("X").depth, at("X").parentUid, at("X").remaining, at("X").sourceUid], [1, "A", 1, "A"], "多源到达时保留剩余深度更大的那条路径");
assert.deepEqual([at("W").depth, at("W").parentUid, at("W").remaining], [1, "B", 0]);
assert.deepEqual([at("Y").depth, at("Y").parentUid, at("Y").remaining], [2, "X", 0]);
assert.deepEqual([at("A").depth, at("A").remaining, at("A").sourceUid], [0, 2, "A"]);
assert.deepEqual(at("A").childUids, ["F", "X"]);
const status = (from, to) => tree.edgeStates.get(JSON.stringify([from, to]));
assert.deepEqual([status("A", "X").status, status("A", "X").skeleton], ["active", true]);
assert.deepEqual([status("B", "X").status, status("B", "X").skeleton], ["active", false], "被更强路径覆盖的边保留为交叉依赖");
assert.equal(status("Y", "Z").status, "capped", "上游已到达但预算用尽");
assert.equal(status("Z", "X").status, "idle", "上游没进候选范围");
assert.deepEqual([status("Z", "X").loop, status("X", "Y").loop], [true, true]);
assert.deepEqual(dependencyPath(tree, "Y"), ["A", "X", "Y"]);
assert.deepEqual(dependencyPath(tree, "nowhere"), []);
assert.equal(dependencyDescendants(tree, "A"), 3);
assert.equal(dependencyDescendants(tree, "B"), 1);
assert.equal(defaultTreeDepthLimit(tree, 3), 1);
assert.equal(defaultTreeDepthLimit(tree, 60), 2);
assert.equal(JSON.stringify(depDetail), depUntouched, "依赖建模不得修改策略草稿");

const depLayout = layoutDependencyTree(tree);
assert.deepEqual(depLayout, layoutDependencyTree(tree), "依赖树布局必须确定性");
assert.equal(Object.keys(depLayout.positions).length, 6, "默认不画未覆盖带");
assert.equal(depLayout.hidden, 0);
assert.deepEqual(depLayout.levels.map((level) => [level.depth, level.y, level.count]), [[0, 0, 2], [1, 162, 3], [2, 324, 1]]);
assert.deepEqual(depLayout.bands, []);
assert.ok(Object.values(depLayout.positions).every((point) => Number.isFinite(point.x) && Number.isFinite(point.y)));
assert.equal(depLayout.positions.X.y, 162);
assert.equal(depLayout.positions.Y.y, 324);
const limited = layoutDependencyTree(tree, { depthLimit: 1 });
assert.equal(Object.keys(limited.positions).length, 5);
assert.equal(limited.hidden, 1);
assert.equal(limited.hasDeeper, true);
const folded = layoutDependencyTree(tree, { collapsed: new Set(["X"]) });
assert.equal(Object.keys(folded.positions).length, 5);
assert.ok(!folded.positions.Y, "折叠的分支不产出位置");
const withLoose = layoutDependencyTree(tree, { showLoose: true });
assert.equal(Object.keys(withLoose.positions).length, 8);
assert.deepEqual(withLoose.bands.map((band) => [band.kind, band.count]), [["loose", 2]], "空分组不占带");
assert.ok(withLoose.bands[0].y > 324);
const filteredTree = layoutDependencyTree(tree, { allowed: new Set(["A", "B", "X"]), showLoose: true });
assert.deepEqual(Object.keys(filteredTree.positions).sort(), ["A", "B", "X"]);
assert.deepEqual(filteredTree.bands, [], "角色筛选掉的条目不出现在未覆盖带");

const depGraph = buildWorldBookGraph(depDetail, depPolicy, { view: "tree" });
assert.equal(depGraph.entryCount, 8);
assert.equal(depGraph.nodes.filter((node) => node.kind === "category").length, 0, "依赖树视图不混入分类层级");
assert.equal(depGraph.edges.filter((edge) => edge.kind !== "dependency").length, 0);
assert.deepEqual(depGraph.roles, { source: 2, fixed: 1, bridge: 3, leaf: 1, orphan: 1 });
assert.deepEqual([depGraph.nodes.find((node) => node.refId === "X").role, depGraph.nodes.find((node) => node.refId === "X").treeDepth], ["bridge", 1]);
assert.equal(depGraph.nodes.find((node) => node.refId === "Z").inCycle, true);
assert.equal(depGraph.nodes.find((node) => node.refId === "Z").unreached, true);
assert.equal(depGraph.nodes.find((node) => node.refId === "F").childCount, 0);
assert.equal(buildWorldBookGraph(depDetail, depPolicy, { view: "tree", roles: ["source"] }).entryCount, 2);
assert.equal(buildWorldBookGraph(depDetail, depPolicy, { view: "tree", roles: ["orphan"] }).entryCount, 1);
assert.equal(buildWorldBookGraph(depDetail, depPolicy, { view: "dependencies" }).nodes.filter((node) => node.kind === "category").length, 2);
assert.equal(buildWorldBookGraph(depDetail, depPolicy, { view: "taxonomy" }).stats, null, "分类结构视图不做依赖建模");

const treeMarkup = renderToStaticMarkup(React.createElement(ScopeManager, { detail: depDetail, view: "tree", onChanged() {} }));
for (const expected of ["世界书依赖树", "世界书依赖分层树", "wbg-toolbar-sub", "wbg-role-chip", "按角色", "按类型",
  "展开层级", "重置折叠", "未覆盖条目", "导入源 · 2 节点", "第 1 层 · 3 节点", "wbg-role-badge", "wbg-collapse-handle", "wbg-tree-level-label"]) {
  assert.ok(treeMarkup.includes(expected), expected);
}
assert.ok(!treeMarkup.includes("wbg-node-category"), "依赖树不渲染分类节点");
const bareMarkup = renderToStaticMarkup(React.createElement(ScopeManager, { detail: {
  ...depDetail, import_config: { revision: 1, fixed_entry_uids: [], dependency_sources: [] },
}, view: "tree", onChanged() {} }));
assert.ok(bareMarkup.includes("还没有可展开的导入源"));
console.log("Worldbook UI: taxonomy, graph filtering/IDs/layout/reciprocal edges, SSR controls, preview, dependency roles and tree passed. Large layout: " + layoutMs + "ms.");
