import { useMemo, useState } from "react";
import type { WorldBookEntryDTO } from "../../types";
import WorldBookGraphIcon from "../WorldBookGraphIcon";
import {
  avatarUrl, characterName, makeLabeler, useCharacterDirectory, type WorldBookPanelProps,
} from "./panel";

/**
 * 条目与角色：把「这条内容怎么用」变成四个常见动作，不需要理解图论。
 *
 *  - 加入基础设定      → 起点 always（所有会话候选）
 *  - 角色入队时选用    → 起点 roster_any（只有该角色入队才载入）
 *  - 选用此条时同时选用 → requires 边（会参与遍历）
 *  - 仅标记相关        → related 边（只浏览，不展开）
 *
 * 界面上显示角色名与头像，实际写入配置的仍然是角色目录 ID。
 */
export default function WorldBookEntryWorkbench(props: WorldBookPanelProps & { onNotice?: (text: string) => void }) {
  const { detail, draft, patch, onNotice } = props;
  const characters = useCharacterDirectory();
  const label = useMemo(() => makeLabeler(detail), [detail]);
  const [query, setQuery] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [selected, setSelected] = useState<string>("");
  const [target, setTarget] = useState("");
  const [pickCharacter, setPickCharacter] = useState("");

  const categories = detail.categories || [];
  const byUid = useMemo(() => new Map(detail.entries.map((e) => [e.uid, e])), [detail.entries]);
  const focused = byUid.get(selected);
  const characterOf = (entry: WorldBookEntryDTO) =>
    draft.entry_updates[entry.uid]?.character_id ?? entry.character_id ?? "";
  const categoryOf = (entry: WorldBookEntryDTO) =>
    draft.entry_moves[entry.uid] ?? draft.entry_updates[entry.uid]?.category_id ?? entry.category_id ?? "unclassified";

  const rootOf = (uid: string) => draft.roots.find((r) => r.entry_uid === uid);
  const requiresFrom = (uid: string) => draft.requires_edges.filter((e) => e.from_uid === uid);
  const requiresTo = (uid: string) => draft.requires_edges.filter((e) => e.to_uid === uid);
  const relatedFrom = (uid: string) => draft.related_edges.filter((e) => e.from_uid === uid);
  const relatedTo = (uid: string) => draft.related_edges.filter((e) => e.to_uid === uid);

  const filtered = useMemo(() => detail.entries.filter((entry) => {
    if (categoryId && categoryOf(entry) !== categoryId) return false;
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return true;
    return [entry.name, entry.uid, characterOf(entry), ...(entry.trigger_keys || [])]
      .join(" ").toLocaleLowerCase().includes(needle);
  }).slice(0, 400), [detail.entries, categoryId, query, draft.entry_updates, draft.entry_moves]);

  const setRoot = (uid: string, root: { activation: "always" | "roster_any" | "manual"; expansion: "none" | "requires_closure"; character_ids?: string[] } | null) => {
    const rest = draft.roots.filter((r) => r.entry_uid !== uid);
    patch({ roots: root ? [...rest, { entry_uid: uid, ...root }] : rest });
  };
  const addEdge = (kind: "requires_edges" | "related_edges", from: string, to: string) => {
    if (!to || from === to) return;
    const list = draft[kind];
    if (list.some((e) => e.from_uid === from && e.to_uid === to)) {
      onNotice?.(kind === "requires_edges" ? "这条必要依赖已经存在。" : "这条关联补充已经存在。");
      return;
    }
    if (draft[kind === "requires_edges" ? "related_edges" : "requires_edges"].some((e) => e.from_uid === from && e.to_uid === to)) {
      onNotice?.(kind === "requires_edges"
        ? "同一条边已经标记为关联补充；保存时不能既必要又仅关联，请先移除。"
        : "同一条边已经标记为必要依赖；保存时不能既必要又仅关联，请先移除。");
      return;
    }
    patch({ [kind]: [...list, { from_uid: from, to_uid: to }] } as any);
    onNotice?.(kind === "requires_edges"
      ? `已添加必要依赖：${label(from)} → ${label(to)}。选用前者时会自动补上后者。`
      : `已标记关联：${label(from)} → ${label(to)}。仅作浏览，不会展开。`);
    setTarget("");
  };
  const removeEdge = (kind: "requires_edges" | "related_edges", from: string, to: string) =>
    patch({ [kind]: draft[kind].filter((e) => !(e.from_uid === from && e.to_uid === to)) } as any);

  /** 未关联角色的角色目录项：入队后不会带出任何专属设定，必须明确提示。 */
  const unlinked = useMemo(() => {
    const linked = new Set(detail.entries.map((e) => e.character_id).filter(Boolean) as string[]);
    return (characters || []).filter((character) => !linked.has(character.id));
  }, [characters, detail.entries]);

  const roleTag = (entry: WorldBookEntryDTO) => {
    const root = rootOf(entry.uid);
    if (root?.activation === "always") return { text: "基础设定", kind: "always" };
    if (root?.activation === "roster_any") return { text: "角色入队时选用", kind: "roster" };
    if (root?.activation === "manual") return { text: "仅手动追加", kind: "manual" };
    if (requiresTo(entry.uid).length) return { text: "被依赖带入", kind: "requires" };
    if (relatedFrom(entry.uid).length || relatedTo(entry.uid).length) return { text: "仅标记相关", kind: "related" };
    return { text: "未配置", kind: "none" };
  };

  return <section className="wbg-entries" aria-label="条目与角色">
    <header className="wbg-config-head">
      <div>
        <p className="wbg-eyebrow">ENTRIES &amp; CHARACTERS</p>
        <h3>条目与角色</h3>
        <p className="wbg-help">
          逐条决定这条内容什么时候出现。四个动作覆盖绝大多数情况，改动进同一份草稿，
          右上角一次保存；未配置的条目不是错误，只是不会自动成为候选。
        </p>
      </div>
      <div className="wbg-config-metrics">
        <span>条目 <b>{detail.entries.length}</b></span>
        <span>已配置 <b>{draft.roots.length}</b></span>
        <span>必要依赖 <b>{draft.requires_edges.length}</b></span>
        <span>关联补充 <b>{draft.related_edges.length}</b></span>
      </div>
    </header>

    {!!unlinked.length && <div className="wbg-notice wbg-warn" role="status">
      <span>
        有 {unlinked.length} 个角色还没有关联任何条目：
        {unlinked.slice(0, 8).map((c) => characterName(characters, c.id)).join("、")}
        {unlinked.length > 8 && " 等"}。它们入队后不会带出专属设定，可在下方为对应条目选择「角色入队时选用」。
      </span>
    </div>}

    <div className="wbg-entries-body">
      <aside className="wbg-entries-list" aria-label="条目列表">
        <div className="wbg-entries-filters">
          <label className="wbg-search"><WorldBookGraphIcon name="search" size={13} />
            <input placeholder="搜索名称、UID、角色、关键词" aria-label="搜索条目" value={query}
              onChange={(event) => setQuery(event.target.value)} />
            {query && <button aria-label="清空搜索" onClick={() => setQuery("")}>×</button>}
          </label>
          <select className="wbg-field" aria-label="按分类筛选" value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
            <option value="">全部分类</option>
            {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
          </select>
        </div>
        <div className="wbg-entries-scroll">
          {filtered.map((entry) => {
            const tag = roleTag(entry);
            const characterId = characterOf(entry);
            return <button key={entry.uid} className={"wbg-entry-card" + (selected === entry.uid ? " is-active" : "")}
              onClick={() => { setSelected(entry.uid); setTarget(""); setPickCharacter(characterId); }}>
              {characterId
                ? <img className="wbg-avatar" src={avatarUrl(characterId)} alt=""
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = "hidden"; }} />
                : <span className="wbg-avatar is-empty" aria-hidden="true">#</span>}
              <span className="wbg-entry-card-main">
                <strong>{entry.name || entry.uid}</strong>
                <small>{characterId ? characterName(characters, characterId) : entry.uid}
                  {!entry.enabled && " · 已停用"}</small>
              </span>
              <em className="wbg-role-tag" data-wbg-rel={tag.kind}>{tag.text}</em>
            </button>;
          })}
          {!filtered.length && <p className="wbg-help">没有匹配的条目。</p>}
        </div>
      </aside>

      <main className="wbg-entries-detail">
        {!focused && <p className="wbg-help">从左侧选择一条条目，决定它在会话里怎么用。</p>}
        {focused && <>
          <div className="wbg-card">
            <div className="wbg-card-head">
              <div><h4>{focused.name || focused.uid}</h4>
                <p className="wbg-uid">{focused.uid}
                  {characterOf(focused) && ` · 角色 ${characterName(characters, characterOf(focused))}（${characterOf(focused)}）`}</p></div>
              <span className="wbg-chip" data-wbg-rel={roleTag(focused).kind}>{roleTag(focused).text}</span>
            </div>
            {!focused.enabled && <p className="wbg-warning">此条目已停用：即使成为候选也不会注入。</p>}
            <p className="wbg-entry-excerpt">{focused.content?.slice(0, 220) || "暂无正文"}</p>
          </div>

          <div className="wbg-card">
            <div className="wbg-card-head"><div><h4>怎么用这条内容</h4>
              <p className="wbg-help">四个动作可叠加。同一对条目不能既是必要依赖又是关联补充。</p></div></div>

            <div className="wbg-action-row">
              <div>
                <strong>加入基础设定</strong>
                <small>不分角色，用这本书就是候选</small>
              </div>
              <button className="wbg-button" aria-pressed={rootOf(focused.uid)?.activation === "always"}
                onClick={() => setRoot(focused.uid, rootOf(focused.uid)?.activation === "always"
                  ? null : { activation: "always", expansion: "none" })}>
                {rootOf(focused.uid)?.activation === "always" ? "已加入 · 点击移除" : "加入基础设定"}
              </button>
            </div>

            <div className="wbg-action-row">
              <div>
                <strong>角色入队时选用</strong>
                <small>只有该角色入队才载入，并补齐它的必要依赖</small>
              </div>
              <div className="wbg-action-controls">
                <select className="wbg-field" aria-label="选择关联角色" value={pickCharacter}
                  onChange={(event) => setPickCharacter(event.target.value)}>
                  <option value="">选择角色</option>
                  {(characters || []).map((character) => <option key={character.id} value={character.id}>
                    {character.name}（{character.id}）</option>)}
                  {pickCharacter && !(characters || []).some((c) => c.id === pickCharacter) &&
                    <option value={pickCharacter}>{pickCharacter}（目录中不存在）</option>}
                </select>
                <button className="wbg-button wbg-button-primary" disabled={!pickCharacter}
                  onClick={() => {
                    setRoot(focused.uid, { activation: "roster_any", expansion: "requires_closure", character_ids: [pickCharacter] });
                    patch({ entry_updates: { ...draft.entry_updates, [focused.uid]: { character_id: pickCharacter } } });
                    onNotice?.(`已设为「${characterName(characters, pickCharacter)}」入队时选用，并把条目关联到该角色。`);
                  }}>
                  应用
                </button>
              </div>
            </div>

            <div className="wbg-action-row">
              <div>
                <strong>选用此条时同时选用…</strong>
                <small>必要依赖：会参与遍历，对方被一起补上</small>
              </div>
              <div className="wbg-action-controls">
                <input className="wbg-field" list="wbg-entry-targets" placeholder="搜索条目名称" aria-label="必要依赖目标"
                  value={target} onChange={(event) => setTarget(event.target.value)} />
                <button className="wbg-button" disabled={!target || !byUid.has(target)} onClick={() => addEdge("requires_edges", focused.uid, target)}>
                  添加必要依赖
                </button>
              </div>
            </div>

            <div className="wbg-action-row">
              <div>
                <strong>仅标记相关</strong>
                <small>提及 / 相识 / 同组织：只浏览，不展开</small>
              </div>
              <div className="wbg-action-controls">
                <input className="wbg-field" list="wbg-entry-targets" placeholder="搜索条目名称" aria-label="关联补充目标"
                  value={target} onChange={(event) => setTarget(event.target.value)} />
                <button className="wbg-button" disabled={!target || !byUid.has(target)} onClick={() => addEdge("related_edges", focused.uid, target)}>
                  仅标记相关
                </button>
              </div>
            </div>
            <datalist id="wbg-entry-targets">
              {detail.entries.filter((entry) => entry.uid !== focused.uid).slice(0, 300)
                .map((entry) => <option key={entry.uid} value={entry.uid}>{entry.name || entry.uid}</option>)}
            </datalist>
            {!!target && !byUid.has(target) && <p className="wbg-warning">
              没有匹配的条目。请从下拉建议里选择，或直接填写条目 UID。
            </p>}
          </div>

          <div className="wbg-card">
            <div className="wbg-card-head"><div><h4>当前关系</h4>
              <p className="wbg-help">这一条作为起点、以及它与其它条目的边。</p></div></div>
            <ul className="wbg-row-list">
              {rootOf(focused.uid) && <li className="wbg-row">
                <b className="wbg-sev">起点</b>
                <span className="wbg-row-name">{rootOf(focused.uid)!.activation === "always" ? "基础设定（所有会话候选）"
                  : rootOf(focused.uid)!.activation === "roster_any" ? `角色入队时选用：${characterName(characters, rootOf(focused.uid)!.character_ids?.[0] || "")}`
                    : "仅手动追加"}</span>
                <span className="wbg-chip">{rootOf(focused.uid)!.expansion === "requires_closure" ? "补齐必要依赖"
                  : rootOf(focused.uid)!.expansion === "none" ? "只含自身" : `按深度 ${rootOf(focused.uid)!.max_depth ?? 1} 展开`}</span>
              </li>}
              {requiresFrom(focused.uid).map((edge) => <li key={`r:${edge.to_uid}`} className="wbg-row">
                <b className="wbg-sev">必要</b><span className="wbg-row-arrow" aria-hidden="true">→</span>
                <span className="wbg-row-name">{label(edge.to_uid)}</span>
                <button className="wbg-icon-button" aria-label="移除必要依赖" onClick={() => removeEdge("requires_edges", edge.from_uid, edge.to_uid)}>×</button>
              </li>)}
              {requiresTo(focused.uid).map((edge) => <li key={`ri:${edge.from_uid}`} className="wbg-row">
                <b className="wbg-sev">被依赖</b><span className="wbg-row-name">{label(edge.from_uid)}</span>
                <span className="wbg-row-arrow" aria-hidden="true">→ 本条</span>
                <button className="wbg-icon-button" aria-label="移除必要依赖" onClick={() => removeEdge("requires_edges", edge.from_uid, edge.to_uid)}>×</button>
              </li>)}
              {relatedFrom(focused.uid).map((edge) => <li key={`d:${edge.to_uid}`} className="wbg-row">
                <b className="wbg-sev">相关</b><span className="wbg-row-arrow" aria-hidden="true">→</span>
                <span className="wbg-row-name">{label(edge.to_uid)}</span>
                <button className="wbg-icon-button" aria-label="移除关联补充" onClick={() => removeEdge("related_edges", edge.from_uid, edge.to_uid)}>×</button>
              </li>)}
              {relatedTo(focused.uid).map((edge) => <li key={`di:${edge.from_uid}`} className="wbg-row">
                <b className="wbg-sev">相关</b><span className="wbg-row-name">{label(edge.from_uid)}</span>
                <span className="wbg-row-arrow" aria-hidden="true">→ 本条</span>
                <button className="wbg-icon-button" aria-label="移除关联补充" onClick={() => removeEdge("related_edges", edge.from_uid, edge.to_uid)}>×</button>
              </li>)}
              {!rootOf(focused.uid) && !requiresFrom(focused.uid).length && !requiresTo(focused.uid).length
                && !relatedFrom(focused.uid).length && !relatedTo(focused.uid).length &&
                <li className="wbg-row"><span className="wbg-help">还没有配置。上面选一个动作即可。</span></li>}
            </ul>
          </div>

          <div className="wbg-card">
            <div className="wbg-card-head"><div><h4>归属</h4>
              <p className="wbg-help">分类只负责组织内容；角色关联决定它跟谁走。实际写入的是角色目录 ID。</p></div></div>
            <div className="wbg-form-pair">
              <label className="wbg-form-label">分类
                <select className="wbg-field" value={categoryOf(focused)} aria-label="条目分类"
                  onChange={(event) => patch({ entry_moves: { ...draft.entry_moves, [focused.uid]: event.target.value } })}>
                  {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
                </select>
              </label>
              <label className="wbg-form-label">关联角色
                <select className="wbg-field" value={characterOf(focused)} aria-label="条目关联角色"
                  onChange={(event) => patch({ entry_updates: { ...draft.entry_updates,
                    [focused.uid]: { ...draft.entry_updates[focused.uid], character_id: event.target.value } } })}>
                  <option value="">不关联</option>
                  {(characters || []).map((character) => <option key={character.id} value={character.id}>
                    {character.name}（{character.id}）</option>)}
                  {!!characterOf(focused) && !(characters || []).some((c) => c.id === characterOf(focused)) &&
                    <option value={characterOf(focused)}>{characterOf(focused)}（目录中不存在）</option>}
                </select>
              </label>
            </div>
            <p className="wbg-help">
              角色分类下的条目必须关联角色，非角色分类的条目不能关联角色；保存时服务端会再校验一次。
            </p>
          </div>
        </>}
      </main>
    </div>
  </section>;
}
