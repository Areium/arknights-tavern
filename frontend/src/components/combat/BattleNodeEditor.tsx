/**
 * 战斗节点编辑器（batch 2）
 *
 * 左：节点列表（剧情节拍绑定 + 会话进度 + 待创建节点）
 * 右：节点详情表单 —— 基本信息 / 地图绘制 / 敌人编成 / 难度奖励 / 校验
 *
 * 数据面：`data/combat/nodes/<node_id>.json`（唯一真相源），保存走 `_hash`
 * 冲突检测（409 → 提示重新加载），校验由服务端 `POST /api/combat/nodes/validate`
 * 判定（与开战时同一套规则）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useApi } from "../../hooks/useApi";
import { useAppStore } from "../../stores/appStore";
import type {
  BattleNodeDTO, BattleNodeOverviewDTO, EnemyCatalogEntryDTO,
  TileTypeDTO, ValidationReportDTO,
} from "../../types";
import BattleMapCanvas, { type MapEditMode } from "./BattleMapCanvas";

const BANDS = ["T0", "T1", "T2", "T3", "T4"];
const CATEGORIES = ["story", "test", "event"];

const PROGRESS_BADGE: Record<string, { label: string; cls: string }> = {
  done: { label: "已完成", cls: "text-emerald-300 border-emerald-700/60" },
  current: { label: "进行中", cls: "text-amber-300 border-amber-600/60" },
  locked: { label: "未到达", cls: "text-gray-400 border-gray-600/60" },
};

interface Props {
  sessionId?: string | null;
  initialNodeId?: string;
  onClose?: () => void;
}

/** 把 tiles 简写（字符串）展开为二维数组 */
function normalizeTiles(map: BattleNodeDTO["map"] | undefined,
                        rows: number, cols: number): string[][] {
  const raw = map?.tiles;
  if (typeof raw === "string") {
    return Array.from({ length: rows }, () => Array.from({ length: cols }, () => raw));
  }
  if (Array.isArray(raw)) {
    return Array.from({ length: rows }, (_, r) =>
      Array.from({ length: cols }, (_, c) => raw[r]?.[c] ?? "ground"));
  }
  return Array.from({ length: rows }, () => Array.from({ length: cols }, () => "ground"));
}

function deployCells(zone: { rect?: number[]; cells?: [number, number][] } | undefined):
  [number, number][] {
  if (!zone) return [];
  if (zone.cells?.length) return zone.cells.map(([r, c]) => [r, c] as [number, number]);
  if (zone.rect?.length === 4) {
    const [r0, c0, r1, c1] = zone.rect;
    const out: [number, number][] = [];
    for (let r = Math.min(r0, r1); r <= Math.max(r0, r1); r++) {
      for (let c = Math.min(c0, c1); c <= Math.max(c0, c1); c++) out.push([r, c]);
    }
    return out;
  }
  return [];
}

function cellsToZone(cells: [number, number][]) {
  if (!cells.length) return undefined;
  const rows = cells.map(([r]) => r);
  const cols = cells.map(([, c]) => c);
  const loR = Math.min(...rows), hiR = Math.max(...rows);
  const loC = Math.min(...cols), hiC = Math.max(...cols);
  const area = (hiR - loR + 1) * (hiC - loC + 1);
  return area === cells.length
    ? { rect: [loR, loC, hiR, hiC] as [number, number, number, number] }
    : { cells };
}

export default function BattleNodeEditor({ sessionId, initialNodeId, onClose }: Props) {
  const api = useApi();
  const { setCombatContext, setCurrentView } = useAppStore();

  const [list, setList] = useState<BattleNodeOverviewDTO[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [node, setNode] = useState<BattleNodeDTO | null>(null);
  const [original, setOriginal] = useState<string>("");
  const [validation, setValidation] = useState<ValidationReportDTO>({ errors: [], warnings: [] });
  const [tiles, setTiles] = useState<TileTypeDTO[]>([]);
  const [enemies, setEnemies] = useState<EnemyCatalogEntryDTO[]>([]);
  const [mode, setMode] = useState<MapEditMode>("tile");
  const [brush, setBrush] = useState("wall");
  const [placing, setPlacing] = useState<{ wave: number; entry: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [search, setSearch] = useState("");
  const validateTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const dirty = useMemo(
    () => !!node && JSON.stringify(node) !== original,
    [node, original],
  );

  // ── 载入目录 ──
  useEffect(() => {
    api.listCombatTiles().then((r) => setTiles(r.tiles as TileTypeDTO[]), () => {});
    api.listCombatEnemies().then((r) => setEnemies(r.enemies as EnemyCatalogEntryDTO[]), () => {});
  }, [api]);

  const reloadList = useCallback(async (selectId?: string) => {
    try {
      const res = await api.listCombatNodes(sessionId || undefined);
      setList(res.nodes || []);
      const wanted = selectId || selectedId || initialNodeId || res.nodes?.[0]?.node_id;
      if (wanted) setSelectedId(wanted);
    } catch (e: any) {
      setError(e.message || "节点列表加载失败");
    }
  }, [api, sessionId, selectedId, initialNodeId]);

  useEffect(() => { reloadList(initialNodeId); /* eslint-disable-next-line */ }, [sessionId]);

  const loadNode = useCallback(async (nodeId: string) => {
    if (!nodeId) return;
    setBusy(true);
    try {
      const res = await api.getCombatNode(nodeId);
      const fresh = {
        ...res.node,
        map: {
          ...res.node.map,
          tiles: normalizeTiles(res.node.map, res.node.map?.rows ?? 7, res.node.map?.cols ?? 7),
        },
      } as BattleNodeDTO;
      setNode(fresh);
      setOriginal(JSON.stringify(fresh));
      setValidation(res.validation || { errors: [], warnings: [] });
      setConflict(false);
      setError(null);
    } catch (e: any) {
      setError(e.message || "节点加载失败");
      setNode(null);
    } finally {
      setBusy(false);
    }
  }, [api]);

  useEffect(() => { if (selectedId) loadNode(selectedId); }, [selectedId, loadNode]);

  // 改动后防抖校验（服务端判定，与开战一致）
  useEffect(() => {
    if (!node || !dirty) return;
    if (validateTimer.current) clearTimeout(validateTimer.current);
    validateTimer.current = setTimeout(() => {
      api.validateCombatNode(node)
        .then((rep) => setValidation(rep))
        .catch(() => {});
    }, 350);
    return () => { if (validateTimer.current) clearTimeout(validateTimer.current); };
  }, [node, dirty, api]);

  // ── 编辑助手 ──
  const patch = useCallback((fn: (draft: BattleNodeDTO) => void) => {
    setNode((prev) => {
      if (!prev) return prev;
      const draft: BattleNodeDTO = JSON.parse(JSON.stringify(prev));
      fn(draft);
      return draft;
    });
    setNotice(null);
  }, []);

  const tileDefMap = useMemo(() => {
    const map: Record<string, Partial<TileTypeDTO>> = {};
    tiles.forEach((t) => { map[t.tile_id] = t; });
    Object.entries(node?.map?.tile_defs || {}).forEach(([id, def]) => {
      map[id] = { ...(map[id] || {}), ...def } as Partial<TileTypeDTO>;
    });
    return map;
  }, [tiles, node?.map?.tile_defs]);

  const rows = node?.map?.rows ?? 7;
  const cols = node?.map?.cols ?? 7;
  const tileGrid = useMemo(() => normalizeTiles(node?.map, rows, cols), [node?.map, rows, cols]);
  const deploy = useMemo(() => ({
    player: deployCells(node?.map?.deploy?.player),
    enemy: deployCells(node?.map?.deploy?.enemy),
  }), [node?.map?.deploy]);

  const paintCell = useCallback((r: number, c: number) => {
    if (!node) return;
    if (placing) {
      patch((draft) => {
        const entry = draft.waves[placing.wave]?.enemies[placing.entry];
        if (!entry) return;
        const next = (entry.positions || []).slice(0, Math.max(0, entry.count - 1));
        while (next.length < Math.min(entry.count, 1)) next.push([r, c]);
        next[0] = [r, c];
        entry.positions = next;
      });
      return;
    }
    if (mode === "tile") {
      patch((draft) => {
        draft.map.tiles = tileGrid.map((row, ri) =>
          row.map((tid, ci) => (ri === r && ci === c ? brush : tid)));
      });
      return;
    }
    // 部署区涂改：切换该格归属（再点一次取消）
    const team = mode === "deploy-player" ? "player" : "enemy";
    patch((draft) => {
      draft.map.deploy = draft.map.deploy || {};
      const other = team === "player" ? "enemy" : "player";
      const mine = deployCells((draft.map.deploy as any)[team])
        .filter(([rr, cc]) => !(rr === r && cc === c));
      const inMine = deploy[team].some(([rr, cc]) => rr === r && cc === c);
      if (!inMine) mine.push([r, c]);
      const theirs = deployCells((draft.map.deploy as any)[other])
        .filter(([rr, cc]) => !(rr === r && cc === c));
      (draft.map.deploy as any)[team] = cellsToZone(mine);
      (draft.map.deploy as any)[other] = cellsToZone(theirs);
    });
  }, [node, placing, mode, brush, patch, tileGrid, deploy]);

  const resizeMap = useCallback((nextRows: number, nextCols: number) => {
    patch((draft) => {
      const grid = normalizeTiles(draft.map, nextRows, nextCols);
      const old = normalizeTiles(draft.map, draft.map.rows, draft.map.cols);
      for (let r = 0; r < nextRows; r++) {
        for (let c = 0; c < nextCols; c++) {
          if (old[r]?.[c] !== undefined) grid[r][c] = old[r][c];
        }
      }
      draft.map.rows = nextRows;
      draft.map.cols = nextCols;
      draft.map.tiles = grid;
    });
  }, [patch]);

  // ── 保存 / 新建 / 删除 ──
  const save = useCallback(async () => {
    if (!node) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.saveCombatNode(node.node_id, node);
      const fresh = { ...res.node,
        map: { ...res.node.map,
          tiles: normalizeTiles(res.node.map, res.node.map?.rows ?? 7, res.node.map?.cols ?? 7) } } as BattleNodeDTO;
      setNode(fresh);
      setOriginal(JSON.stringify(fresh));
      setNotice("已保存");
      setConflict(false);
      reloadList(fresh.node_id);
    } catch (e: any) {
      if (e?.status === 409) {
        setConflict(true);
        setError("保存冲突：节点已被其他窗口/进程修改");
      } else {
        setError(e.message || "保存失败");
      }
    } finally {
      setBusy(false);
    }
  }, [api, node, reloadList]);

  const createNode = useCallback(async () => {
    if (!newId.trim()) return;
    setBusy(true);
    try {
      await api.createCombatNode(newId.trim(), newName.trim() || newId.trim());
      setNewId(""); setNewName("");
      await reloadList(newId.trim());
      setSelectedId(newId.trim());
    } catch (e: any) {
      setError(e.message || "新建失败");
    } finally {
      setBusy(false);
    }
  }, [api, newId, newName, reloadList]);

  const removeNode = useCallback(async (nodeId: string) => {
    setBusy(true);
    try {
      await api.deleteCombatNode(nodeId);
      setNotice(`已删除 ${nodeId}`);
      setNode(null);
      await reloadList();
    } catch (e: any) {
      if (e?.status === 409 && window.confirm(`${e.message}\n\n仍要强制删除吗？`)) {
        await api.deleteCombatNode(nodeId, true);
        setNode(null);
        await reloadList();
      } else {
        setError(e.message || "删除失败");
      }
    } finally {
      setBusy(false);
    }
  }, [api, reloadList]);

  const tryBattle = useCallback(async () => {
    if (!node) return;
    setBusy(true);
    try {
      const res = await api.combatTestStart(node.node_id);
      setCombatContext({ state: res.state, testId: res.test_id });
      setCurrentView("combat");
    } catch (e: any) {
      setError(e.message || "试打启动失败");
    } finally {
      setBusy(false);
    }
  }, [api, node, setCombatContext, setCurrentView]);

  const filtered = list.filter((n) =>
    !search.trim() || n.name.includes(search) || n.node_id.includes(search));

  return (
    <div className="flex h-full min-h-0 bg-gray-950 text-gray-200">
      {/* ── 左：节点列表 ── */}
      <div className="w-72 flex-shrink-0 border-r border-gray-800 flex flex-col min-h-0">
        <div className="p-3 border-b border-gray-800 space-y-2">
          <div className="flex items-center gap-2">
            <input
              className="flex-1 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs outline-none focus:border-amber-500/50"
              placeholder="搜索节点…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <button
              className="text-xs px-2 py-1 rounded border border-gray-700 hover:border-amber-500/60"
              onClick={() => reloadList()}
              title="刷新"
            >⟳</button>
          </div>
          <div className="flex items-center gap-1">
            <input
              className="w-24 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-[11px] outline-none"
              placeholder="node_id"
              value={newId}
              onChange={(e) => setNewId(e.target.value)}
            />
            <input
              className="flex-1 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-[11px] outline-none"
              placeholder="名称"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <button
              className="text-[11px] px-2 py-1 rounded bg-amber-700/30 border border-amber-600/50 hover:bg-amber-700/50 disabled:opacity-40"
              onClick={createNode}
              disabled={!newId.trim() || busy}
            >新建</button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {filtered.map((n) => {
            const badge = n.progress ? PROGRESS_BADGE[n.progress.state] : null;
            return (
              <button
                key={n.node_id}
                onClick={() => setSelectedId(n.node_id)}
                className={
                  "w-full text-left px-3 py-2 border-b border-gray-900 hover:bg-gray-900/70 "
                  + (selectedId === n.node_id ? "bg-gray-900 " : "")
                }
              >
                <div className="flex items-center gap-1.5">
                  <span className={"text-xs truncate " + (n.missing ? "text-amber-300" : "")}>
                    {n.name}
                  </span>
                  {n.missing && <span className="text-[9px] text-amber-400">待创建</span>}
                  {badge && (
                    <span className={"ml-auto text-[9px] border rounded px-1 " + badge.cls}>
                      {badge.label}
                    </span>
                  )}
                </div>
                <div className="text-[10px] text-gray-500 truncate">
                  {n.node_id}
                  {n.rows ? ` · ${n.rows}×${n.cols}` : ""}
                  {n.unit_total ? ` · ${n.unit_total} 敌` : ""}
                </div>
                {n.markers.length > 0 && (
                  <div className="text-[9px] text-cyan-500/80 truncate">
                    {n.markers[0].plot_id}/{n.markers[0].beat_id}
                  </div>
                )}
              </button>
            );
          })}
          {filtered.length === 0 && (
            <p className="p-3 text-xs text-gray-500">没有匹配的节点</p>
          )}
        </div>
      </div>

      {/* ── 右：编辑区 ── */}
      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-800">
          <span className="text-sm font-medium truncate">
            {node ? node.name : "未选择节点"}
          </span>
          {node && <span className="text-[10px] text-gray-500 font-mono">{node.node_id}</span>}
          {dirty && <span className="text-[10px] text-amber-400">● 未保存</span>}
          <div className="flex-1" />
          {notice && <span className="text-[11px] text-emerald-300">{notice}</span>}
          {onClose && (
            <button className="text-xs text-gray-500 hover:text-gray-300" onClick={onClose}>
              ✕ 关闭
            </button>
          )}
          <button
            className="text-xs px-2.5 py-1 rounded border border-gray-700 hover:border-emerald-500/60 disabled:opacity-40"
            onClick={tryBattle}
            disabled={!node || busy || validation.errors.length > 0}
            title={validation.errors.length ? "校验未通过，无法试打" : "以该节点启动一场测试战斗"}
          >⚔ 试打</button>
          <button
            className="text-xs px-2.5 py-1 rounded bg-cyan-800/40 border border-cyan-600/50 hover:bg-cyan-800/70 disabled:opacity-40"
            onClick={save}
            disabled={!node || !dirty || busy}
          >保存</button>
          {node && (
            <button
              className="text-xs px-2 py-1 rounded border border-red-800/60 text-red-300 hover:bg-red-900/30"
              onClick={() => removeNode(node.node_id)}
            >删除</button>
          )}
        </div>

        {error && (
          <div className="mx-4 mt-3 px-3 py-2 rounded border border-red-800/60 bg-red-950/40 text-xs text-red-200 flex items-center gap-3">
            <span className="flex-1">{error}</span>
            {conflict && (
              <button
                className="px-2 py-0.5 rounded border border-red-700 hover:bg-red-900/40"
                onClick={() => { setError(null); loadNode(node?.node_id || selectedId); }}
              >重新加载</button>
            )}
            <button className="text-red-300/70" onClick={() => setError(null)}>✕</button>
          </div>
        )}

        {!node ? (
          <div className="flex-1 flex items-center justify-center text-sm text-gray-500">
            选择左侧节点开始编辑，或新建一个节点
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto p-4 space-y-5">
            {/* 基本信息 */}
            <section className="space-y-2">
              <h3 className="text-xs text-gray-400 tracking-wider">基本信息</h3>
              <div className="grid grid-cols-2 gap-2">
                <label className="text-[11px] text-gray-500">
                  名称
                  <input
                    className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs"
                    value={node.name}
                    onChange={(e) => patch((d) => { d.name = e.target.value; })}
                  />
                </label>
                <label className="text-[11px] text-gray-500">
                  分类
                  <select
                    className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs"
                    value={node.difficulty?.category || ""}
                    onChange={(e) => patch((d) => {
                      d.difficulty = { ...(d.difficulty || {}), category: e.target.value };
                    })}
                  >
                    <option value="">（未设置）</option>
                    {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </label>
              </div>
              <label className="block text-[11px] text-gray-500">
                概要
                <input
                  className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs"
                  value={node.summary || ""}
                  onChange={(e) => patch((d) => { d.summary = e.target.value; })}
                />
              </label>
              <div className="grid grid-cols-3 gap-2">
                {(["plot_id", "chapter_id", "beat_id"] as const).map((key) => (
                  <label key={key} className="text-[11px] text-gray-500">
                    {key}
                    <input
                      className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-[11px] font-mono"
                      value={(node.bind as any)?.[key] || ""}
                      onChange={(e) => patch((d) => {
                        d.bind = { ...(d.bind || {}), [key]: e.target.value };
                      })}
                    />
                  </label>
                ))}
              </div>
            </section>

            {/* 地图 */}
            <section className="space-y-2">
              <div className="flex items-center gap-2">
                <h3 className="text-xs text-gray-400 tracking-wider">地图</h3>
                <span className="text-[10px] text-gray-500">
                  {rows}×{cols}（上限 40×40）
                </span>
                <div className="flex-1" />
                <label className="text-[10px] text-gray-500">
                  行
                  <input
                    type="number" min={1} max={40}
                    className="ml-1 w-14 bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-[11px]"
                    value={rows}
                    onChange={(e) => resizeMap(Math.max(1, Math.min(40, +e.target.value || 1)), cols)}
                  />
                </label>
                <label className="text-[10px] text-gray-500">
                  列
                  <input
                    type="number" min={1} max={40}
                    className="ml-1 w-14 bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-[11px]"
                    value={cols}
                    onChange={(e) => resizeMap(rows, Math.max(1, Math.min(40, +e.target.value || 1)))}
                  />
                </label>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {(["tile", "deploy-player", "deploy-enemy"] as MapEditMode[]).map((m) => (
                  <button
                    key={m}
                    onClick={() => { setMode(m); setPlacing(null); }}
                    className={
                      "text-[11px] px-2 py-1 rounded border "
                      + (mode === m
                        ? "border-amber-500/60 bg-amber-600/20 text-amber-200"
                        : "border-gray-700 text-gray-400 hover:text-gray-200")
                    }
                  >
                    {m === "tile" ? "画格子" : m === "deploy-player" ? "玩家部署区" : "敌方部署区"}
                  </button>
                ))}
                {mode === "tile" && (
                  <>
                    <div className="flex items-center gap-1">
                      {tiles.map((t) => (
                        <button
                          key={t.tile_id}
                          onClick={() => setBrush(t.tile_id)}
                          title={`${t.name}（移动代价 ${t.move_cost}${t.blocks_movement ? "，不可通行" : ""}）`}
                          className={
                            "w-6 h-6 rounded border text-[10px] flex items-center justify-center "
                            + (brush === t.tile_id ? "ring-2 ring-amber-400/70 " : "")
                          }
                          style={{ backgroundColor: `${t.color}cc`, borderColor: `${t.color}` }}
                        >{t.glyph}</button>
                      ))}
                    </div>
                    <button
                      className="text-[11px] px-2 py-1 rounded border border-gray-700 hover:text-gray-200"
                      onClick={() => patch((d) => {
                        d.map.tiles = Array.from({ length: rows }, () =>
                          Array.from({ length: cols }, () => brush));
                      })}
                    >整图填充</button>
                  </>
                )}
                {placing && (
                  <span className="text-[11px] text-amber-300">
                    站位模式：点击地图为 wave{placing.wave + 1} / {node.waves[placing.wave]?.enemies[placing.entry]?.enemy} 指定落点
                    <button className="ml-2 underline" onClick={() => setPlacing(null)}>退出</button>
                  </span>
                )}
              </div>

              <div className="overflow-auto border border-gray-800 rounded p-2 bg-gray-950">
                <BattleMapCanvas
                  rows={rows} cols={cols} tiles={tileGrid} tileDefs={tileDefMap}
                  deploy={deploy} mode={mode} brush={brush} onPaint={paintCell}
                  highlight={placing ? new Set(deploy.enemy.map(([r, c]) => `${r},${c}`)) : undefined}
                />
              </div>
              <p className="text-[10px] text-gray-500">
                勾选模式后按住左键可连续涂抹；部署区格子在战斗内决定入场位置（未声明时按左右三分之一推导）。
              </p>
            </section>

            {/* 敌人编成 */}
            <section className="space-y-2">
              <div className="flex items-center gap-2">
                <h3 className="text-xs text-gray-400 tracking-wider">敌人编成</h3>
                <button
                  className="text-[11px] px-2 py-0.5 rounded border border-gray-700 hover:text-gray-200"
                  onClick={() => patch((d) => { d.waves = [...d.waves, { enemies: [] }]; })}
                >＋ 波次</button>
              </div>

              {node.waves.map((wave, wi) => (
                <div key={wi} className="border border-gray-800 rounded p-2 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-gray-400">第 {wi + 1} 波</span>
                    <span className="text-[10px] text-gray-600">
                      {wave.enemies.reduce((sum, e) => sum + (e.count || 0), 0)} 个单位
                    </span>
                    <div className="flex-1" />
                    <button
                      className="text-[11px] px-1.5 rounded border border-gray-700 hover:text-red-300"
                      onClick={() => patch((d) => {
                        d.waves.splice(wi, 1);
                        if (!d.waves.length) d.waves = [{ enemies: [] }];
                      })}
                    >删除波次</button>
                  </div>

                  {wave.enemies.map((entry, ei) => {
                    const catalog = enemies.find((e) => e.name === entry.enemy);
                    return (
                      <div key={ei} className="flex flex-wrap items-center gap-2 bg-gray-900/60 rounded px-2 py-1.5">
                        <select
                          className="bg-gray-900 border border-gray-700 rounded px-1.5 py-0.5 text-[11px] max-w-[12rem]"
                          value={entry.enemy}
                          onChange={(e) => patch((d) => {
                            d.waves[wi].enemies[ei].enemy = e.target.value;
                          })}
                        >
                          {!enemies.some((e) => e.name === entry.enemy) && (
                            <option value={entry.enemy}>{entry.enemy}（未知）</option>
                          )}
                          {enemies.map((e) => (
                            <option key={e.name} value={e.name}>
                              {e.name} · {e.combat_stats?.hp ?? "?"}HP
                            </option>
                          ))}
                        </select>
                        <label className="text-[10px] text-gray-500">
                          数量
                          <input
                            type="number" min={1} max={12}
                            className="ml-1 w-12 bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-[11px]"
                            value={entry.count}
                            onChange={(e) => patch((d) => {
                              d.waves[wi].enemies[ei].count = Math.max(1, Math.min(12, +e.target.value || 1));
                            })}
                          />
                        </label>
                        <label className="text-[10px] text-gray-500">
                          血量覆盖
                          <input
                            type="number" min={1}
                            placeholder={String(catalog?.combat_stats?.hp ?? "")}
                            className="ml-1 w-16 bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-[11px]"
                            value={entry.stats?.hp ?? ""}
                            onChange={(e) => patch((d) => {
                              const target = d.waves[wi].enemies[ei];
                              const hp = +e.target.value;
                              if (!e.target.value) {
                                if (target.stats) delete target.stats.hp;
                                if (target.stats && !Object.keys(target.stats).length) delete target.stats;
                              } else {
                                target.stats = { ...(target.stats || {}), hp };
                              }
                            })}
                          />
                        </label>
                        <span className="text-[10px] text-gray-500">
                          站位 {entry.positions?.length ? entry.positions.map(([r, c]) => `${r},${c}`).join(" ") : "自动"}
                        </span>
                        <button
                          className={
                            "text-[11px] px-1.5 rounded border "
                            + (placing && placing.wave === wi && placing.entry === ei
                              ? "border-amber-500/60 text-amber-200"
                              : "border-gray-700 hover:text-gray-200")
                          }
                          onClick={() => setPlacing(
                            placing && placing.wave === wi && placing.entry === ei ? null : { wave: wi, entry: ei })}
                        >📍 指定站位</button>
                        <button
                          className="text-[11px] px-1.5 rounded border border-gray-700 hover:text-red-300"
                          onClick={() => patch((d) => { d.waves[wi].enemies.splice(ei, 1); })}
                        >移除</button>
                      </div>
                    );
                  })}

                  <div className="flex items-center gap-2">
                    <select
                      className="bg-gray-900 border border-gray-700 rounded px-1.5 py-0.5 text-[11px]"
                      defaultValue=""
                      onChange={(e) => {
                        const name = e.target.value;
                        if (!name) return;
                        patch((d) => { d.waves[wi].enemies.push({ enemy: name, count: 1, positions: [] }); });
                        e.target.value = "";
                      }}
                    >
                      <option value="">＋ 添加敌人…</option>
                      {enemies.map((en) => (
                        <option key={en.name} value={en.name}>{en.name}</option>
                      ))}
                    </select>
                    {wave.enemies.length === 0 && (
                      <span className="text-[10px] text-amber-300/80">
                        这一波还没有敌人（空节点无法开战）
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </section>

            {/* 难度与奖励 */}
            <section className="space-y-2">
              <h3 className="text-xs text-gray-400 tracking-wider">难度与奖励</h3>
              <div className="grid grid-cols-4 gap-2">
                <label className="text-[11px] text-gray-500">
                  阶段带
                  <select
                    className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs"
                    value={node.difficulty?.band || ""}
                    onChange={(e) => patch((d) => {
                      d.difficulty = { ...(d.difficulty || {}), band: e.target.value };
                    })}
                  >
                    <option value="">（未设置）</option>
                    {BANDS.map((b) => <option key={b} value={b}>{b}</option>)}
                  </select>
                </label>
                <label className="text-[11px] text-gray-500">
                  威胁预算
                  <input type="number" step="0.1"
                    className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs"
                    value={node.difficulty?.threat_budget ?? ""}
                    onChange={(e) => patch((d) => {
                      d.difficulty = { ...(d.difficulty || {}), threat_budget: +e.target.value };
                    })}
                  />
                </label>
                <label className="text-[11px] text-gray-500">
                  目标回合
                  <input type="number"
                    className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs"
                    value={node.difficulty?.target_rounds ?? ""}
                    onChange={(e) => patch((d) => {
                      d.difficulty = { ...(d.difficulty || {}), target_rounds: +e.target.value };
                    })}
                  />
                </label>
                <label className="text-[11px] text-gray-500">
                  回合上限
                  <input type="number"
                    className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs"
                    value={node.conditions?.max_rounds ?? ""}
                    onChange={(e) => patch((d) => {
                      d.conditions = { ...(d.conditions || {}), max_rounds: +e.target.value };
                    })}
                  />
                </label>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <label className="text-[11px] text-gray-500">
                  奖励 XP
                  <input type="number"
                    className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs"
                    value={node.rewards?.xp ?? 0}
                    onChange={(e) => patch((d) => {
                      d.rewards = { ...(d.rewards || {}), xp: +e.target.value };
                    })}
                  />
                </label>
                <label className="text-[11px] text-gray-500">
                  背景 id
                  <input
                    className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs font-mono"
                    value={node.background || ""}
                    onChange={(e) => patch((d) => { d.background = e.target.value; })}
                  />
                </label>
                <label className="text-[11px] text-gray-500">
                  可撤退
                  <select
                    className="mt-1 w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs"
                    value={node.conditions?.escape_enabled ? "1" : "0"}
                    onChange={(e) => patch((d) => {
                      d.conditions = { ...(d.conditions || {}), escape_enabled: e.target.value === "1" };
                    })}
                  >
                    <option value="1">允许</option>
                    <option value="0">禁止</option>
                  </select>
                </label>
              </div>
            </section>

            {/* 校验 */}
            <section className="space-y-1">
              <h3 className="text-xs text-gray-400 tracking-wider">校验</h3>
              {validation.errors.length === 0 && validation.warnings.length === 0 && (
                <p className="text-[11px] text-emerald-300">✔ 通过（可保存 / 可试打）</p>
              )}
              {validation.errors.map((msg, i) => (
                <p key={`e${i}`} className="text-[11px] text-red-300">✖ {msg}</p>
              ))}
              {validation.warnings.map((msg, i) => (
                <p key={`w${i}`} className="text-[11px] text-amber-300/90">⚠ {msg}</p>
              ))}
              <p className="text-[10px] text-gray-600">
                校验由服务端判定（与开战同一套规则）；错误会阻止保存与试打，警告仅供提醒。
              </p>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
