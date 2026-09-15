import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "../../hooks/useApi";
import { useAppStore } from "../../stores/appStore";
import type { DependencyProposalJobDTO, WorldBookDetail, WorldBookRootDTO } from "../../types";
import WorldBookGraphIcon from "../WorldBookGraphIcon";

const STAGE_LABELS: Record<string, string> = {
  queued: "排队中", metadata: "提取条目元数据", cards: "生成条目分析卡",
  candidates: "检索明确引用", adjudication: "判定候选关系", validation: "校验建议",
  done: "已完成", failed: "失败", cancelled: "已取消",
};
const RELATION_LABELS: Record<string, string> = {
  requires: "必要依赖", related: "关联补充", none: "无关系", unsure: "待复核",
};
const OUTCOME_LABELS: Record<string, string> = {
  success: "全部批次成功", partial: "部分批次失败（结果可用，可只重试失败批次）",
  failed: "没有任何产出（模型全部失败）",
};

/** 终态：只有这三个 stage 才算跑完，其余都还在跑。 */
const TERMINAL = ["done", "failed", "cancelled"];

/**
 * 「AI 自动构建依赖」：选书后一次点击，后台用当前已配置的 LLM 自行读取条目、
 * 分析并构建完整依赖配置。用户不写提示词、不复制 JSON、不手工连线。
 *
 * 生成后展示图谱与预览，一次「应用构建结果」把建议并入统一草稿并保存；
 * 疑问关系单独列出，允许审阅但不强制逐条确认。
 *
 * 任务入口**按书恢复**（审核反证 P2-13）：jobID 不再只存在面板状态里，
 * 切视图 / 卸载重开都会用 `listDependencyProposals` 找回这本书正在跑的任务，
 * 因此后台不会白跑，用户也不会因为看不见入口而重复点一次。
 */
export default function DependencyBuildPanel({ detail, onApply, busy }: {
  detail: WorldBookDetail;
  /** 把建议并入统一草稿（由页面统一保存，不是这里直接写盘）；job_id 供服务端复核 */
  onApply: (proposal: {
    job_id: string;
    roots: WorldBookRootDTO[];
    accepted: Array<{ from_uid: string; to_uid: string; relation: string }>;
  }) => void;
  busy?: boolean;
}) {
  const api = useApi();
  const store = useAppStore();
  const [job, setJob] = useState<DependencyProposalJobDTO | null>(null);
  const [error, setError] = useState("");
  const [needsSettings, setNeedsSettings] = useState(false);
  const [starting, setStarting] = useState(false);
  const [showAllRecords, setShowAllRecords] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const timer = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; }
  }, []);
  useEffect(() => stopPolling, [stopPolling]);

  const poll = useCallback((jobId: string) => {
    const tick = async () => {
      try {
        const { job: value } = await api.getDependencyProposal(detail.id, jobId, 0, 200);
        setJob(value);
        if (TERMINAL.includes(value.stage)) { stopPolling(); return; }
      } catch (e) {
        setError(e instanceof Error ? e.message : "查询任务失败");
        stopPolling();
        return;
      }
      timer.current = window.setTimeout(tick, 900);
    };
    stopPolling();
    timer.current = window.setTimeout(tick, 300);
  }, [api, detail.id, stopPolling]);

  // 打开面板 / 换书时找回这本书的任务入口：正在跑的继续轮询，跑完的直接展示结果。
  useEffect(() => {
    let cancelled = false;
    setRestoring(true);
    stopPolling();
    setJob(null);
    api.listDependencyProposals(detail.id)
      .then(({ jobs, active_job_id, latest_job_id }) => {
        if (cancelled) return;
        const jobId = active_job_id || latest_job_id || jobs[0]?.job_id;
        if (!jobId) { setRestoring(false); return; }
        const known = jobs.find((item) => item.job_id === jobId);
        if (known) setJob(known);
        poll(jobId);
        setRestoring(false);
      })
      .catch(() => { if (!cancelled) setRestoring(false); });
    return () => { cancelled = true; stopPolling(); };
  }, [api, detail.id, poll, stopPolling]);

  const start = async () => {
    if (starting || busy) return;
    setStarting(true); setError(""); setNeedsSettings(false); setJob(null); setShowAllRecords(false);
    try {
      const { job: created } = await api.createDependencyProposal(detail.id);
      setJob(created);
      poll(created.job_id);
    } catch (e) {
      const message = e instanceof Error ? e.message : "无法启动构建";
      setError(message);
      // 没有可用模型：给出进入设置的入口，而不是让用户猜
      if (/设置|LLM|503/.test(message)) setNeedsSettings(true);
    } finally {
      setStarting(false);
    }
  };

  const cancel = async () => {
    if (!job) return;
    try { await api.cancelDependencyProposal(detail.id, job.job_id); stopPolling(); poll(job.job_id); }
    catch (e) { setError(e instanceof Error ? e.message : "取消失败"); }
  };
  const retry = async () => {
    if (!job) return;
    try {
      setError("");
      const { job: restarted } = await api.retryDependencyProposal(detail.id, job.job_id);
      setJob(restarted); poll(job.job_id);
    } catch (e) { setError(e instanceof Error ? e.message : "重试失败"); }
  };

  const result = job?.result || null;
  const records = result?.records || [];
  const visible = showAllRecords ? records : records.slice(0, 40);
  const acceptedCount = result?.accepted?.length || 0;
  const suggestedRoots = result?.roots || [];
  const uncertain = records.filter((r) => r.relation === "unsure");
  const running = !!job && !TERMINAL.includes(job.stage);
  const nameOf = (uid: string) => detail.entries.find((e) => e.uid === uid)?.name || uid;
  // 结果过期（书在构建后被改过）时不允许直接应用：由服务端兜底复核，界面先挡住。
  const staleBlocked = !!job?.stale;
  const canApply = !busy && !running && !staleBlocked && acceptedCount + suggestedRoots.length > 0;

  return <section className="wbg-build" aria-label="AI 自动构建依赖">
    <header className="wbg-build-head">
      <div>
        <p className="wbg-eyebrow">AI BUILD</p>
        <h4>AI 自动构建依赖</h4>
        <p className="wbg-help">
          一次点击即可：后台会自行读取条目、分析并构建完整的起点与依赖配置。
          你不需要写提示词、复制 JSON 或手工连线。
        </p>
      </div>
      <div className="wbg-build-actions">
        {!running && <button className="wbg-button wbg-button-primary" disabled={starting || busy || restoring}
          onClick={() => void start()}>
          <WorldBookGraphIcon name="graph" size={14} />
          {starting ? "正在启动…" : result ? "重新构建" : "AI 自动构建依赖"}
        </button>}
        {running && <>
          <span className="wbg-build-stage" role="status">
            {STAGE_LABELS[job!.stage] || job!.stage}
            {job!.total > 0 && ` · ${job!.progress}/${job!.total}`}
          </span>
          <button className="wbg-button wbg-button-quiet" onClick={() => void cancel()}>取消</button>
        </>}
        {!!job?.failed_batches?.length && !running &&
          <button className="wbg-button wbg-button-quiet" onClick={() => void retry()}>
            {job.resumable ? "继续未完成部分" : "重试失败批次"}（{job.failed_batches.length}）
          </button>}
      </div>
    </header>

    {restoring && <p className="wbg-help" role="status">正在恢复这本书的构建入口…</p>}

    {error && <div role="alert" className="wbg-notice wbg-error">
      <span>{error}</span>
      {needsSettings && <button onClick={() => store.setCurrentView("settings")}>前往设置配置模型 →</button>}
      <button aria-label="关闭" onClick={() => setError("")}>×</button>
    </div>}

    {job?.error && <div role="alert" className="wbg-notice wbg-error">
      <span>构建失败（{job.error.code}）：{job.error.message}</span>
    </div>}

    {job?.outcome === "failed" && <div role="alert" className="wbg-notice wbg-error">
      <span>这次构建没有产出任何可用结果（{OUTCOME_LABELS.failed}）。已失败的批次可以直接重试，不需要从头再来。</span>
    </div>}
    {job?.outcome === "partial" && <div role="status" className="wbg-notice wbg-warn">
      <span>构建未完全成功：{OUTCOME_LABELS.partial}。下方结果仍然可用，但请重点核对问题清单。</span>
    </div>}
    {job?.resumable && <div role="status" className="wbg-notice wbg-warn">
      <span>
        这次构建在预算内没有跑完（还差 {job.pending_card_uids || 0} 个条目分析、
        {job.pending_pairs || 0} 对候选判定）。点「继续未完成部分」会接着上次的进度跑，不会重复计费。
      </span>
    </div>}

    {job?.stale && <div role="alert" className="wbg-notice wbg-warn">
      <span>
        这本书的正文在构建开始后已被修改，这份结果已过期，不能应用（服务端也会拒绝）。
        请点「重新构建」用最新正文再跑一次。
      </span>
    </div>}

    {job && running && <div className="wbg-build-progress" role="progressbar"
      aria-valuenow={job.progress} aria-valuemax={job.total || 1}>
      <i style={{ width: `${job.total ? Math.round(100 * job.progress / job.total) : 8}%` }} />
    </div>}

    {job && !running && !result && !job.error && <p className="wbg-help" role="status">
      {job.message || "任务已结束，但没有产出可用结果。"}
    </p>}

    {result && <>
      <div className="wbg-metric-row">
        <span>必要依赖 <b>{result.stats.requires}</b></span>
        <span>关联补充 <b>{result.stats.related}</b></span>
        <span>待复核 <b>{result.stats.unsure}</b></span>
        <span>无关系 <b>{result.stats.none}</b></span>
        {!!suggestedRoots.length && <span>角色起点 <b>{suggestedRoots.length}</b></span>}
        <span>模型 <b>{result.model || "—"}</b></span>
      </div>
      <p className="wbg-help">
        置信度只用于排序参考，不代表准确率。应用前请重点看「待复核」与下方问题清单。
      </p>

      {!!job?.workload?.estimated_calls && <p className="wbg-help">
        开工前估算：{job.workload.entries ?? 0} 个条目 · {job.workload.pairs ?? 0} 对候选 ·
        预计 {job.workload.estimated_calls} 次调用（本次预算 {job.workload.budget}）。
      </p>}

      {!!result.issues.length && <details className="wbg-details" open={result.issues.length <= 6}>
        <summary>校验问题 <span>{result.issues.length}</span></summary>
        <ul className="wbg-build-issues">
          {result.issues.slice(0, 60).map((issue, index) => <li key={index} data-wbg-severity={issue.severity}>
            <b>{issue.severity === "error" ? "错误" : issue.severity === "warning" ? "注意" : "提示"}</b>
            {issue.message}
          </li>)}
        </ul>
      </details>}

      {!!suggestedRoots.length && <details className="wbg-details">
        <summary>AI 建议的角色起点 <span>{suggestedRoots.length}</span></summary>
        <ul className="wbg-build-issues">
          {suggestedRoots.slice(0, 60).map((root) => <li key={root.entry_uid}>
            <b>角色起点</b>
            {nameOf(root.entry_uid)}：角色 {(root.character_ids || []).join("、") || "（未指定）"} 入队时选用
          </li>)}
        </ul>
        <p className="wbg-help">
          只会采用真实存在于角色目录里的角色标识；目录里没有的会列在「校验问题」里，不会写进配置。
        </p>
      </details>}

      {!!uncertain.length && <details className="wbg-details">
        <summary>待复核关系 <span>{uncertain.length}</span>（不强制逐条确认）</summary>
        <ul className="wbg-build-issues">
          {uncertain.slice(0, 60).map((record) => <li key={record.from_uid + record.to_uid}>
            <b>待复核</b>
            {nameOf(record.from_uid)} → {nameOf(record.to_uid)}：{record.reason || "证据无法在原文中定位"}
          </li>)}
        </ul>
      </details>}

      {!!result.expansion_probe && Object.keys(result.expansion_probe).length > 0 &&
        <details className="wbg-details">
          <summary>阵容扩张自检</summary>
          <p className="wbg-help">
            必要依赖边 {result.expansion_probe.requires_edges ?? 0} 条 ·
            单角色最大候选 {result.expansion_probe.single_character_max ?? 0} 条 ·
            全部角色 {result.expansion_probe.all_characters ?? 0} 条 ·
            无角色条目 {result.expansion_probe.empty_roster ?? 0} 条
          </p>
          <p className="wbg-help">用于发现「所有角色都变成全局源」这类过度扩张，不会自动改配置。</p>
        </details>}

      {!!records.length && <details className="wbg-details">
        <summary>建议明细 <span>{records.length}</span></summary>
        <div className="wbg-build-records">
          {visible.map((record) => <div key={record.from_uid + record.to_uid} className="wbg-build-record">
            <span className="wbg-build-rel" data-wbg-rel={record.relation}>
              {RELATION_LABELS[record.relation] || record.relation}
            </span>
            <span>{nameOf(record.from_uid)} → {nameOf(record.to_uid)}</span>
            <small>置信度 {record.confidence.toFixed(2)}{record.evidence ? ` · 证据：${record.evidence.slice(0, 60)}` : ""}</small>
          </div>)}
        </div>
        {records.length > 40 && <button className="wbg-text-button" onClick={() => setShowAllRecords(!showAllRecords)}>
          {showAllRecords ? "收起" : `显示全部 ${records.length} 条`}
        </button>}
      </details>}

      <div className="wbg-build-apply">
        <button className="wbg-button wbg-button-primary" disabled={!canApply}
          onClick={() => onApply({ job_id: job!.job_id, accepted: result.accepted, roots: suggestedRoots })}>
          应用构建结果（{acceptedCount} 条关系{suggestedRoots.length ? ` + ${suggestedRoots.length} 个角色起点` : ""}）
        </button>
        <p className="wbg-help">
          应用会把结果并入统一草稿：你可以先审阅、撤销，再点「保存」一次性写入。
          正文不会被改写。保存时服务端会按任务标识复核来源，过期结果会被拒绝。
        </p>
      </div>
    </>}
  </section>;
}
