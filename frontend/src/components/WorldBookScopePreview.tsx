import type { WorldBookScopePreviewDTO } from "../types";

const LABELS: Record<string, string> = { worldview: "世界观", roster: "入队角色", fixed: "固定导入", dependency: "依赖展开", legacy: "旧书兼容" };

export default function WorldBookScopePreview({ value }: { value: WorldBookScopePreviewDTO }) {
  return <div className="rounded-lg border border-gray-700 bg-gray-900/60 p-3 space-y-2 text-xs" aria-label="导入范围预览">
    <p className="text-gray-200">候选条目 <strong>{value.entry_count}</strong> / {value.full_entry_count}，估算 token {value.resolved_estimated_tokens.toLocaleString()} / {value.full_estimated_tokens.toLocaleString()}</p>
    <p className="text-cyan-300">候选规模减少 {value.saved_estimated_tokens.toLocaleString()} token（{value.saved_percent}%）</p>
    <div className="flex flex-wrap gap-3 text-gray-400">{Object.entries(value.breakdown).filter(([, v]) => v.entry_count > 0).map(([key, v]) => <span key={key}>{LABELS[key] || key}：{v.entry_count} 条 / ~{v.estimated_tokens} token</span>)}</div>
    {value.scope.legacy_full_scope && <p className="text-amber-300">当前保留旧书全量兼容模式；完成分类后，可在内容中心预览并启用按需模式。</p>}
    {value.warnings.map((warning) => <p key={warning} className="text-amber-300">{warning}</p>)}
    {value.source_expansions?.map((source) => <details key={source.entry_uid} className="text-gray-400"><summary>{source.name || source.entry_uid} · 深度 {source.max_depth} · 展开 {source.entries.length} 条</summary><p>{source.entries.map((e) => e.name || e.uid).join("、") || "无可用条目"}</p></details>)}
    {!!value.scope.excluded_entries?.length && <details className="text-gray-400"><summary>已排除 {value.scope.excluded_entries.length} 条（不会注入）</summary>{value.scope.excluded_entries.map((e) => <p key={e.uid}>{e.name || e.uid}：{e.reason}</p>)}</details>}
    <p className="text-gray-500">这是候选内容估算，不是每轮实际节省量；分类间可能重叠，合计已去重。关键词、常驻、概率和预算仍决定实际注入。</p>
  </div>;
}
