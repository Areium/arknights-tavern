import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "../../hooks/useApi";
import { useAppStore } from "../../stores/appStore";
import type { DependencyProposalJobDTO, WorldBookDetail } from "../../types";
import WorldBookGraphIcon from "../WorldBookGraphIcon";

const STAGE_LABELS: Record<string, string> = {
  queued: "排队中", metadata: "提取条目元数据", cards: "生成条目分析卡",
  candidates: "检索明确引用", adjudication: "判定候选关系", validation: "校验建议",
  done: "已完成", failed: "失败", cancelled: "已取消",
};
const RELATION_LABELS: Record<string, string> = {
  requires: "必要依赖", related: "关联补充", none: "无关系", unsure: "待复核",
};

/**
 * 「AI 自动构建依赖」：选书后一次点击，后台用当前已配置的 LLM 自行读取条目、
 * 分析并构建完整依赖配置。用户不写提示词、不复制 JSON、不手工连线。
 *
 * 生成后展示图谱与预览，一次「应用构建结果」把建议并入统一草稿并保存；
 * 疑问关系单独列出，允许审阅但不强制逐条确认。
 */
export default function DependencyBuildPanel({ detail, onApply, busy }: {
  detail: WorldBookDetail;
  /** 把建议并入统一草稿（由页面统一保存，不是这里直接写盘） */
  onApply: (proposal: { accepted: Array<{ from_uid: string; to_uid: string; relation: string }> }) => void;
  busy?: boolean;
}) {
  const api = useApi();
  const store = useAppStore();
  const [job, setJob] = useState<DependencyProposalJobDTO | null>(null);
  const [error, setError] = useState("");
  const [needsSettings, setNeedsSettings] = useState(false);
  const [starting, setStarting] = useState(false);
  const [showAllRecords, setShowAllRecords] = useState(false);
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
        if (["done", "failed", "cancelled"].includes(value.stage)) { stopPolling(); return; }
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
  const uncertain = records.filter((r) => r.relation === "unsure");
  const running = !!job && !["done", "failed", "cancelled"].includes(job.stage);
  const nameOf = (uid: string) => detail.entries.find((e) => e.uid === uid)?.name || uid;

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
        {!running && <button className="wbg-button wbg-button-primary" disabled={starting || busy}
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
            重试失败批次（{job.failed_batches.length}）
          </button>}
      </div>
    </header>

    {error && <div role="alert" className="wbg-notice wbg-error">
      <span>{error}</span>
      {needsSettings && <button onClick={() => store.setCurrentView("settings")}>前往设置配置模型 →</button>}
      <button aria-label="关闭" onClick={() => setError("")}>×</button>
    </div>}

    {job?.error && <div role="alert" className="wbg-notice wbg-error">
      <span>构建失败（{job.error.code}）：{job.error.message}</span>
    </div>}

    {job?.stale && <div role="status" className="wbg-notice wbg-warn">
      <span>这本书在构建开始后已被修改，结果可能已过期。请重新构建，或先核对下方内容再应用。</span>
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
        <span>模型 <b>{result.model || "—"}</b></span>
      </div>
      <p className="wbg-help">
        置信度只用于排序参考，不代表准确率。应用前请重点看「待复核」与下方问题清单。
      </p>

      {!!result.issues.length && <details className="wbg-details" open={result.issues.length <= 6}>
        <summary>校验问题 <span>{result.issues.length}</span></summary>
        <ul className="wbg-build-issues">
          {result.issues.slice(0, 60).map((issue, index) => <li key={index} data-wbg-severity={issue.severity}>
            <b>{issue.severity === "error" ? "错误" : issue.severity === "warning" ? "注意" : "提示"}</b>
            {issue.message}
          </li>)}
        </ul>
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
        <button className="wbg-button wbg-button-primary" disabled={busy || acceptedCount === 0}
          onClick={() => onApply({ accepted: result.accepted })}>
          应用构建结果（{acceptedCount} 条关系）
        </button>
        <p className="wbg-help">
          应用会把结果并入统一草稿：你可以先审阅、撤销，再点「保存」一次性写入。
          正文不会被改写。
        </p>
      </div>
    </>}
  </section>;
}
