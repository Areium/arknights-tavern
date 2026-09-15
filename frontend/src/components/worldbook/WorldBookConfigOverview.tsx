import { useMemo, useState } from "react";
import type { WorldBookDependencyEdgeDTO, WorldBookRootDTO } from "../../types";
import WorldBookScopePreview from "../WorldBookScopePreview";
import WorldBookGraphIcon from "../WorldBookGraphIcon";
import DependencyBuildPanel from "./DependencyBuildPanel";
import {
  ACTIVATION_LABELS, EXPANSION_LABELS, avatarUrl, characterName, makeLabeler,
  useCharacterDirectory, type WorldBookPanelProps,
} from "./panel";

/**
 * 配置概览：把「这本书怎么载入」压缩成四组看得懂的东西 ——
 * 基础设定（所有会话候选）/ 角色设定（入队时选用）/ 关联补充 / 待处理，
 * 外加「试选阵容」与「本次范围预览」，以及一次点击的 AI 自动构建。
 *
 * 所有改动只落在页面级的统一草稿上，由页面右上角一次保存。
 */
export default function WorldBookConfigOverview(props: WorldBookPanelProps) {
  const { detail, draft, patch, adoptV3, preview, previewing, previewError, roster, setRoster } = props;
  const characters = useCharacterDirectory();
  const label = useMemo(() => makeLabeler(detail), [detail]);
  const [showAllBase, setShowAllBase] = useState(false);
  const [rosterOpen, setRosterOpen] = useState(true);

  const byUid = useMemo(() => new Map(detail.entries.map((e) => [e.uid, e])), [detail.entries]);
  const alwaysRoots = draft.roots.filter((r) => r.activation === "always");
  const rosterRoots = draft.roots.filter((r) => r.activation === "roster_any");
  const manualRoots = draft.roots.filter((r) => r.activation === "manual");
  const requiresSet = useMemo(() => new Set(draft.requires_edges.map((e) => `${e.from_uid}\u0000${e.to_uid}`)),
    [draft.requires_edges]);
  const rejectedSet = useMemo(() => new Set(draft.rejected.map((e) => `${e.from_uid}\u0000${e.to_uid}`)),
    [draft.rejected]);

  const rootPatch = (next: WorldBookRootDTO[]) => patch({ roots: next });
  const removeRoot = (uid: string) => rootPatch(draft.roots.filter((r) => r.entry_uid !== uid));
  const toggleExpansion = (root: WorldBookRootDTO) => rootPatch(draft.roots.map((r) => r.entry_uid !== root.entry_uid
    ? r : { ...r, expansion: r.expansion === "requires_closure" ? "none" : "requires_closure" }));
  /**
   * 移除一条边。若它来自 AI 建议，必须**同时**记进 `rejected` 并把它从待应用的
   * `proposal.accepted` 里摘掉：否则保存时 AI 结果会重新并回来，删掉的边复活
   * （审核反证 P2-11）。统一草稿才是编辑真相，不再每次叠加旧建议。
   */
  const removeEdge = (list: WorldBookDependencyEdgeDTO[], edge: WorldBookDependencyEdgeDTO,
    key: "requires_edges" | "related_edges") => {
    const pair = `${edge.from_uid}\u0000${edge.to_uid}`;
    const nextProposal = draft.proposal ? {
      ...draft.proposal,
      accepted: (draft.proposal.accepted || []).filter(
        (item) => `${item.from_uid}\u0000${item.to_uid}` !== pair),
      accepted_pairs: (draft.proposal.accepted_pairs || []).filter(
        (item) => `${item[0]}\u0000${item[1]}` !== pair),
    } : null;
    patch({
      [key]: list.filter((e) => !(e.from_uid === edge.from_uid && e.to_uid === edge.to_uid)),
      rejected: rejectedSet.has(pair) ? draft.rejected
        : [...draft.rejected, { from_uid: edge.from_uid, to_uid: edge.to_uid }],
      proposal: nextProposal,
    } as Partial<typeof draft>);
  };

  /** 角色设定按角色分组：一个角色一组，组内是「入队时选用」的条目。 */
  const characterGroups = useMemo(() => {
    const groups = new Map<string, WorldBookRootDTO[]>();
    for (const root of rosterRoots) {
      for (const key of root.character_ids?.length ? root.character_ids : [""]) {
        const list = groups.get(key);
        if (list) list.push(root); else groups.set(key, [root]);
      }
    }
    return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [rosterRoots]);

  /** 待处理：只列真正要动手的，未被当前试选阵容选中不算错误。 */
  const todos = useMemo(() => {
    const out: Array<{ key: string; severity: "error" | "warning"; text: string; uid?: string }> = [];
    for (const issue of preview?.issues || []) {
      out.push({ key: `${issue.code}:${issue.uid || ""}`, severity: issue.severity === "error" ? "error" : "warning",
        text: issue.message, uid: issue.uid });
    }
    for (const uid of draft.requires_edges.flatMap((e) => [e.from_uid, e.to_uid])
      .concat(draft.related_edges.flatMap((e) => [e.from_uid, e.to_uid]))) {
      if (!byUid.has(uid)) out.push({ key: `ghost:${uid}`, severity: "error", text: `依赖引用了不存在的条目 ${uid}` });
    }
    const scopeOf = (id: string) => detail.categories?.find((c) => c.id === id)?.scope_type;
    for (const entry of detail.entries) {
      if (scopeOf(entry.category_id || "") === "character" && !entry.character_id) {
        out.push({ key: `nochar:${entry.uid}`, severity: "error", uid: entry.uid,
          text: `${entry.name || entry.uid} 在角色分类下但没有关联角色，保存会被拒绝` });
      }
      if (scopeOf(entry.category_id || "") !== "character" && entry.character_id) {
        out.push({ key: `stray:${entry.uid}`, severity: "error", uid: entry.uid,
          text: `${entry.name || entry.uid} 关联了角色却不在角色分类下，保存会被拒绝` });
      }
    }
    // 未关联角色：角色目录里有，但没有任何条目指向它 —— 这些角色入队后不会带来任何条目
    const linked = new Set([...detail.entries.map((e) => e.character_id).filter(Boolean) as string[],
      ...rosterRoots.flatMap((r) => r.character_ids || [])]);
    for (const character of characters || []) {
      if (!linked.has(character.id)) out.push({ key: `unlinked:${character.id}`, severity: "warning",
        text: `${character.name}（${character.id}）还没有关联任何条目：入队后不会带出专属设定` });
    }
    for (const edge of preview?.cross_references || []) {
      out.push({ key: `xref:${edge.from_uid}:${edge.to_uid}`, severity: "warning",
        text: `交叉引用：${label(edge.from_uid)} → ${label(edge.to_uid)}（依赖成环，遍历会安全终止）` });
    }
    for (const group of characterGroups) {
      if (!group[0] && group[1].length) out.push({ key: "roster:none", severity: "error",
        text: `${group[1].length} 个「角色入队时选用」起点没有指定角色，保存会被拒绝` });
      if (group[0] && characters && !characters.some((c) => c.id === group[0])) {
        out.push({ key: `roster:missing:${group[0]}`, severity: "warning",
          text: `起点指定的角色「${group[0]}」不在角色目录里：入队时永远不会被激活` });
      }
    }
    return out;
  }, [preview, draft.requires_edges, draft.related_edges, detail.entries, detail.categories, byUid, label, characterGroups, characters]);

  const baseVisible = showAllBase ? alwaysRoots : alwaysRoots.slice(0, 24);

  return <section className="wbg-config" aria-label="世界书配置概览">
    <header className="wbg-config-head">
      <div>
        <p className="wbg-eyebrow">CONFIG OVERVIEW</p>
        <h3>配置概览</h3>
        <p className="wbg-help">
          这里回答一件事：这本书在会话里到底会载入什么。改动都进同一份草稿，
          右上角一次保存；正文不会被改写。
        </p>
      </div>
      <div className="wbg-config-metrics">
        <span>基础设定 <b>{alwaysRoots.length}</b></span>
        <span>角色设定 <b>{characterGroups.length}</b></span>
        <span>关联补充 <b>{draft.related_edges.length}</b></span>
        <span className={todos.some((t) => t.severity === "error") ? "is-warn" : ""}>待处理 <b>{todos.length}</b></span>
      </div>
    </header>

    {!detail.dependency_rules && <div className="wbg-notice wbg-warn" role="status">
      <span>
        这本书目前仍使用旧版载入规则。下面按「固定导入 → 基础设定、导入源 → 按旧深度展开」
        等价呈现；<b>改分类、改角色关联不会改变载入范围</b>，要改用按需载入请显式选择（右侧预览会先展示迁移结果）。
      </span>
      {!draft.adopt_v3 && <button className="wbg-button wbg-button-quiet" onClick={adoptV3}>
        启用按需载入（保留现有全部来源）
      </button>}
      {draft.adopt_v3 && <span className="wbg-chip">已选择：保存后改用按需载入</span>}
    </div>}

    <div className="wbg-config-grid">
      <div className="wbg-config-main">
        <section className="wbg-card" aria-label="基础设定">
          <div className="wbg-card-head">
            <div><h4>{ACTIVATION_LABELS.always}</h4>
              <p className="wbg-help">不分角色，只要用这本书就是候选。适合世界观、地理、常识这类全局设定。</p></div>
            <span className="wbg-card-count">{alwaysRoots.length}</span>
          </div>
          {!alwaysRoots.length && <p className="wbg-help">还没有基础设定。可在「条目与角色」里把条目设为「加入基础设定」。</p>}
          <ul className="wbg-row-list">
            {baseVisible.map((root) => <li key={root.entry_uid} className="wbg-row">
              <WorldBookGraphIcon name="pin" size={13} />
              <span className="wbg-row-name">{label(root.entry_uid)}</span>
              <span className="wbg-chip" title="展开方式">{EXPANSION_LABELS[root.expansion] || root.expansion}</span>
              {byUid.get(root.entry_uid)?.enabled === false && <span className="wbg-chip is-warn">已停用</span>}
              <button className="wbg-text-button" disabled={root.expansion === "legacy_depth"}
                title={root.expansion === "legacy_depth" ? "旧格式导入源固定按深度展开" : "在「只含自身」与「补齐必要依赖」之间切换"}
                onClick={() => toggleExpansion(root)}>
                {root.expansion === "requires_closure" ? "改为只含自身" : "补齐必要依赖"}
              </button>
              <button className="wbg-icon-button" aria-label={`移除基础设定 ${label(root.entry_uid)}`}
                onClick={() => removeRoot(root.entry_uid)}>×</button>
            </li>)}
          </ul>
          {alwaysRoots.length > 24 && <button className="wbg-text-button" onClick={() => setShowAllBase(!showAllBase)}>
            {showAllBase ? "收起" : `显示全部 ${alwaysRoots.length} 条`}
          </button>}
          {!!manualRoots.length && <details className="wbg-details">
            <summary>{ACTIVATION_LABELS.manual} <span>{manualRoots.length}</span></summary>
            <p className="wbg-help">这些条目不会自动成为候选，只在新建会话时手动追加时才会载入。</p>
            <ul className="wbg-row-list">{manualRoots.map((root) => <li key={root.entry_uid} className="wbg-row">
              <span className="wbg-row-name">{label(root.entry_uid)}</span>
              <span className="wbg-chip">仅手动追加</span>
              <button className="wbg-icon-button" aria-label={`移除 ${label(root.entry_uid)}`} onClick={() => removeRoot(root.entry_uid)}>×</button>
            </li>)}</ul>
          </details>}
        </section>

        <section className="wbg-card" aria-label="角色设定">
          <div className="wbg-card-head">
            <div><h4>{ACTIVATION_LABELS.roster_any}</h4>
              <p className="wbg-help">只有该角色入队时才会载入，不会因为别的角色入队被带出来。</p></div>
            <span className="wbg-card-count">{rosterRoots.length}</span>
          </div>
          {!characterGroups.length && <p className="wbg-help">还没有角色设定。可在「条目与角色」里为条目选择「角色入队时选用」。</p>}
          {characterGroups.map(([characterId, roots]) => <div key={characterId || "(未指定)"} className="wbg-char-group">
            <div className="wbg-char-group-head">
              {characterId
                ? <img className="wbg-avatar" src={avatarUrl(characterId)} alt=""
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }} />
                : <span className="wbg-avatar is-empty" aria-hidden="true">?</span>}
              <div>
                <strong>{characterId ? characterName(characters, characterId) : "未指定角色"}</strong>
                <small>{characterId || "入队时永远不会被激活，需要补一个角色"}</small>
              </div>
              <span className="wbg-card-count">{roots.length}</span>
            </div>
            <ul className="wbg-row-list">{roots.map((root) => <li key={root.entry_uid} className="wbg-row">
              <span className="wbg-row-name">{label(root.entry_uid)}</span>
              <span className="wbg-chip">{EXPANSION_LABELS[root.expansion] || root.expansion}</span>
              <button className="wbg-text-button" title="把这条改成所有会话都能用的基础设定"
                onClick={() => rootPatch(draft.roots.map((r) => r.entry_uid === root.entry_uid
                  ? { entry_uid: r.entry_uid, activation: "always", expansion: "requires_closure" } : r))}>
                改为基础设定
              </button>
              <button className="wbg-icon-button" aria-label={`移除角色设定 ${label(root.entry_uid)}`}
                onClick={() => removeRoot(root.entry_uid)}>×</button>
            </li>)}</ul>
          </div>)}
        </section>

        <section className="wbg-card" aria-label="关联补充">
          <div className="wbg-card-head">
            <div><h4>关联补充</h4>
              <p className="wbg-help">只作为浏览信息，<b>不参与依赖展开</b>：提及、相识、同组织这类关系放这里。</p></div>
            <span className="wbg-card-count">{draft.related_edges.length}</span>
          </div>
          {!draft.related_edges.length && <p className="wbg-help">还没有关联补充。可在「条目与角色」里选「仅标记相关」。</p>}
          <ul className="wbg-row-list">{draft.related_edges.map((edge) => <li key={`${edge.from_uid}->${edge.to_uid}`} className="wbg-row">
            <span className="wbg-row-name">{label(edge.from_uid)}</span>
            <span className="wbg-row-arrow" aria-hidden="true">→</span>
            <span className="wbg-row-name">{label(edge.to_uid)}</span>
            {requiresSet.has(`${edge.from_uid}\u0000${edge.to_uid}`) && <span className="wbg-chip is-warn">同时是必要依赖</span>}
            <button className="wbg-icon-button" aria-label="移除关联补充" onClick={() => removeEdge(draft.related_edges, edge, "related_edges")}>×</button>
          </li>)}</ul>
        </section>

        <section className="wbg-card" aria-label="待处理">
          <div className="wbg-card-head">
            <div><h4>待处理</h4>
              <p className="wbg-help">只列真正需要动手的项。条目没被当前试选阵容选中不是错误。</p></div>
            <span className="wbg-card-count">{todos.length}</span>
          </div>
          {!todos.length && <p className="wbg-help">没有待处理项。</p>}
          <ul className="wbg-row-list">{todos.slice(0, 80).map((todo) => <li key={todo.key} className="wbg-row" data-wbg-severity={todo.severity}>
            <b className="wbg-sev">{todo.severity === "error" ? "错误" : "注意"}</b>
            <span className="wbg-row-name">{todo.text}</span>
          </li>)}</ul>
          {todos.length > 80 && <p className="wbg-help">还有 {todos.length - 80} 项未显示，建议先处理上面的错误。</p>}
        </section>
      </div>

      <aside className="wbg-config-side">
        <DependencyBuildPanel detail={detail} busy={props.saving}
          onApply={(proposal) => {
            // 建议并入统一草稿：边去重后追加，保存时与人工配置一起原子写入。
            // 必须带上 job_id：服务端据此复核任务身份 / 正文哈希 / 证据，不信任客户端的 accepted。
            const key = (e: { from_uid: string; to_uid: string }) => `${e.from_uid}\u0000${e.to_uid}`;
            const merge = (base: WorldBookDependencyEdgeDTO[], add: Array<{ from_uid: string; to_uid: string }>) => {
              const seen = new Set(base.map(key));
              return [...base, ...add.filter((e) => !seen.has(key(e)) && !rejectedSet.has(key(e)))
                .map((e) => ({ from_uid: e.from_uid, to_uid: e.to_uid }))];
            };
            // 已人工拒绝的建议不再并入，也不留在待应用列表里。
            const accepted = proposal.accepted.filter((r) => !rejectedSet.has(key(r)));
            const requires = accepted.filter((r) => r.relation === "requires");
            const related = accepted.filter((r) => r.relation === "related");
            patch({
              adopt_v3: true,
              scope_mode: "selective",
              roots: [...draft.roots, ...proposal.roots.filter(
                (root) => !draft.roots.some((old) => old.entry_uid === root.entry_uid))],
              proposal: {
                materialized: true,
                job_id: proposal.job_id,
                accepted,
                accepted_pairs: accepted.map((r) => [r.from_uid, r.to_uid] as [string, string]),
              },
              requires_edges: merge(draft.requires_edges, requires),
              related_edges: merge(draft.related_edges, related),
            });
          }} />

        <section className="wbg-card" aria-label="试选阵容">
          <div className="wbg-card-head">
            <div><h4>试选阵容</h4>
              <p className="wbg-help">只用于试算「本次范围」，不会写进任何配置。</p></div>
            <button className="wbg-text-button" aria-expanded={rosterOpen} onClick={() => setRosterOpen(!rosterOpen)}>
              {rosterOpen ? "收起" : "展开"}
            </button>
          </div>
          {rosterOpen && <>
            <div className="wbg-roster-chips">
              {roster.map((id) => <span key={id} className="wbg-fixed-chip">
                <img src={avatarUrl(id)} alt="" onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }} />
                <span>{characterName(characters, id)}</span>
                <button aria-label={`移出试选阵容 ${characterName(characters, id)}`}
                  onClick={() => setRoster((current) => current.filter((item) => item !== id))}>×</button>
              </span>)}
              {!roster.length && <span className="wbg-help">未选角色：只会看到基础设定与固定内容。</span>}
            </div>
            <div className="wbg-roster-picker">
              {(characters || []).map((character) => <button key={character.id}
                className={"wbg-roster-chip" + (roster.includes(character.id) ? " is-on" : "")}
                aria-pressed={roster.includes(character.id)}
                onClick={() => setRoster((current) => current.includes(character.id)
                  ? current.filter((id) => id !== character.id) : [...current, character.id])}>
                <img src={avatarUrl(character.id)} alt="" onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }} />
                {character.name}
              </button>)}
              {characters === null && <p className="wbg-help">正在读取角色目录…</p>}
              {characters?.length === 0 && <p className="wbg-help">角色目录为空，可前往「资产」导入角色卡。</p>}
            </div>
          </>}
        </section>

        <section className="wbg-card" aria-label="本次范围预览">
          <div className="wbg-card-head">
            <div><h4>本次范围预览</h4>
              <p className="wbg-help">按当前草稿 + 试选阵容试算，<b>保存后就是这个结果</b>。</p></div>
            {previewing && <span className="wbg-chip">计算中…</span>}
          </div>
          {previewError && <div role="alert" className="wbg-notice wbg-error"><span>预览未通过：{previewError}</span></div>}
          {preview ? <WorldBookScopePreview value={preview} /> : !previewError && <p className="wbg-help">正在计算候选范围…</p>}
          {preview?.display_tree?.length ? <details className="wbg-details">
            <summary>载入树（按起点分层） <span>{preview.display_tree.length}</span></summary>
            <ul className="wbg-tree-list">{preview.display_tree.slice(0, 120).map((node) => <li key={node.uid}
              style={{ paddingLeft: 8 + Math.min(node.depth, 8) * 14 }}>
              <span className={node.is_root ? "wbg-tree-root" : ""}>{node.name || node.uid}</span>
              {node.remaining !== null && <small>剩余 {node.remaining}</small>}
            </li>)}</ul>
            {preview.display_tree.length > 120 && <p className="wbg-help">仅显示前 120 个节点。</p>}
          </details> : null}
        </section>
      </aside>
    </div>
  </section>;
}
