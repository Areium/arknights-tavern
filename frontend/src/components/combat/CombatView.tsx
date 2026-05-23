import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useAppStore } from "../../stores/appStore";
import { useApi, createCombatSSE, createCombatTestSSE } from "../../hooks/useApi";
import type { CombatEventDTO, CombatStateDTO, CardDTO } from "../../types";
import CombatGrid from "./CombatGrid";
import CombatHand from "./CombatHand";
import CombatEventLog from "./CombatEventLog";
import UnitStatusPanel from "./UnitStatusPanel";
import CombatParticles from "./CombatParticles";
import CombatCard from "./CombatCard";

const CELL = 56; // px — must match CSS .combat-cell size

const DEFAULT_CHARACTERS = ["阿米娅", "博士", "银灰", "霜星"];
const DEFAULT_ENCOUNTER = "初遇整合运动";

export default function CombatView() {
  const {
    activeSessionId,
    sessions,
    combatState,
    setCombatState,
    combatUIMode,
    setCombatUIMode,
    selectedCardIndex,
    setSelectedCardIndex,
    combatTestId,
    setCombatTestId,
    selectedUnitId,
    setSelectedUnitId,
    setCurrentView,
  } = useAppStore();
  const api = useApi();

  const [events, setEvents] = useState<CombatEventDTO[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [cursor, setCursor] = useState<[number, number] | null>(null);
  const [dragCardIndex, setDragCardIndex] = useState<number | null>(null);
  const [dragCell, setDragCell] = useState<[number, number] | null>(null);
  const [startChars, setStartChars] = useState<string[]>(DEFAULT_CHARACTERS);
  const [encounterId, setEncounterId] = useState(DEFAULT_ENCOUNTER);
  const [charInput, setCharInput] = useState("");
  const sseRef = useRef<{ close: () => void } | null>(null);
  const stateRef = useRef(combatState);
  stateRef.current = combatState;

  // Damage numbers for floating text effects
  const [damageNumbers, setDamageNumbers] = useState<
    { id: number; value: number; type: string; pos: [number, number] }[]
  >([]);
  const dmgIdRef = useRef(0);

  const addDamageNumber = useCallback(
    (value: number, type: string, pos: [number, number]) => {
      const id = ++dmgIdRef.current;
      setDamageNumbers((prev) => [...prev.slice(-20), { id, value, type, pos }]);
      setTimeout(() => {
        setDamageNumbers((prev) => prev.filter((d) => d.id !== id));
      }, 1200);
    },
    []
  );

  // Particle emitters
  const [particleEmitters, setParticleEmitters] = useState<
    { id: string; config: { type: "spark" | "heal" | "death" | "victory"; x: number; y: number; count?: number } }[]
  >([]);
  const emitterIdRef = useRef(0);

  const spawnParticles = useCallback(
    (type: "spark" | "heal" | "death" | "victory", pos: [number, number], count?: number) => {
      const id = `emitter_${++emitterIdRef.current}`;
      const gap = 2;
      const x = CELL + 5 + pos[1] * (CELL + gap) + CELL / 2;
      const y = CELL - 12 + pos[0] * (CELL + gap) + CELL / 2;
      setParticleEmitters((prev) => [...prev.slice(-30), { id, config: { type, x, y, count } }]);
    },
    []
  );

  const removeEmitter = useCallback((id: string) => {
    setParticleEmitters((prev) => prev.filter((e) => e.id !== id));
  }, []);

  const sessionId = activeSessionId || (sessions.length > 0 ? sessions[0].id : null);
  const effectiveId = combatTestId || sessionId;

  const fetchState = useCallback(async () => {
    if (!effectiveId) return;
    try {
      const state = combatTestId
        ? await api.combatTestState(combatTestId)
        : await api.combatState(sessionId!);
      setCombatState(state as CombatStateDTO);
      if (state.battle_over && state.winner) {
        setResult(state.winner === "player" ? "胜利" : "失败");
      }
    } catch {
      // no combat active
    }
  }, [effectiveId, combatTestId, sessionId, api, setCombatState]);

  const connectSSE = useCallback(() => {
    if (!effectiveId) return;
    sseRef.current?.close();
    const handlers = {
      onEvent: (ev: any) => {
        setEvents((prev) => [...prev.slice(-200), ev as CombatEventDTO]);
        // Spawn damage numbers + particles
        if (ev.type === "damage" && ev.data?.damage > 0) {
          const pos = ev.data.target_pos || [4, 4];
          addDamageNumber(ev.data.damage, ev.data.damage_type || "physical", pos);
          spawnParticles("spark", pos, 8 + Math.floor(ev.data.damage / 5));
        }
        if (ev.type === "heal" && ev.data?.amount > 0) {
          const pos = ev.data.target_pos || [4, 4];
          addDamageNumber(ev.data.amount, "heal", pos);
          spawnParticles("heal", pos, 6);
        }
        if (ev.type === "death") {
          const pos = ev.data.pos || [4, 4];
          spawnParticles("death", pos, 15);
        }
        if (ev.type === "battle_end") {
          setResult(ev.data.winner === "player" ? "胜利" : "失败");
          if (ev.data.winner === "player") {
            spawnParticles("victory", [4, 4], 40);
          }
          fetchState();
        }
      },
      onError: (msg: string) => setError(msg),
      onDone: () => fetchState(),
    };
    sseRef.current = combatTestId
      ? createCombatTestSSE(combatTestId, handlers)
      : createCombatSSE(sessionId!, handlers);
  }, [effectiveId, combatTestId, sessionId, fetchState, addDamageNumber, spawnParticles]);

  useEffect(() => {
    fetchState();
    connectSSE();
    return () => {
      sseRef.current?.close();
    };
  }, [fetchState, connectSSE]);

  const handleStartBattle = useCallback(async () => {
    if (!sessionId || startChars.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const state = await api.combatStart(sessionId, encounterId, startChars);
      setCombatState(state as CombatStateDTO);
      setEvents([]);
      setResult(null);
      setDamageNumbers([]);
      connectSSE();
    } catch (e: any) {
      setError(e.message || "启动战斗失败");
    } finally {
      setLoading(false);
    }
  }, [sessionId, encounterId, startChars, api, setCombatState, connectSSE]);

  const handleStartTestBattle = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.combatTestStart(encounterId);
      setCombatState(result.state as CombatStateDTO);
      setCombatTestId(result.test_id);
      setEvents([]);
      setResult(null);
      setDamageNumbers([]);
    } catch (e: any) {
      setError(e.message || "启动战斗测试失败");
    } finally {
      setLoading(false);
    }
  }, [encounterId, api, setCombatState, setCombatTestId]);

  const addChar = () => {
    const name = charInput.trim();
    if (name && !startChars.includes(name)) {
      setStartChars([...startChars, name]);
    }
    setCharInput("");
  };

  const removeChar = (name: string) => {
    setStartChars(startChars.filter((c) => c !== name));
  };

  // Active unit (engine's current turn)
  const activeUnit = combatState?.units.find((u) => u.unit_id === combatState.active_unit_id) ?? null;

  // Selected unit (clicked on grid or status panel)
  const selectedUnit = selectedUnitId
    ? combatState?.units.find((u) => u.unit_id === selectedUnitId) ?? null
    : null;

  // Attack range origin: selected unit or active unit
  const rangeOrigin = selectedUnit || activeUnit;

  // Cards to display: selected unit's hand, or active unit's hand
  const displayedHand = selectedUnit && combatState?.player_hands
    ? (combatState.player_hands[selectedUnit.unit_id] || [])
    : combatState?.shared_hand ?? [];

  const isSelectedActive = selectedUnit?.unit_id === combatState?.active_unit_id;

  // Move range from selected unit's mobility (Chebyshev distance)
  const moveHighlights = useMemo(() => {
    if (!selectedUnit || !selectedUnit.is_alive || selectedUnit.team !== "player") {
      return new Set<string>();
    }
    const mobility = selectedUnit.mobility || 1;
    const [r0, c0] = selectedUnit.pos;
    const cells = new Set<string>();
    for (let dr = -mobility; dr <= mobility; dr++) {
      for (let dc = -mobility; dc <= mobility; dc++) {
        if (dr === 0 && dc === 0) continue;
        if (Math.abs(dr) > mobility || Math.abs(dc) > mobility) continue;
        const r = r0 + dr;
        const c = c0 + dc;
        if (r >= 0 && r < 9 && c >= 0 && c <= 2) {
          const key = `${r},${c}`;
          if (!combatState?.grid?.[key]) {
            cells.add(key);
          }
        }
      }
    }
    return cells;
  }, [selectedUnit, combatState]);

  // Attack range from selected card + range origin
  const rangeHighlights = useMemo(() => {
    if (combatUIMode !== "TARGETING" || selectedCardIndex === null || !rangeOrigin) {
      return new Set<string>();
    }
    const card = displayedHand[selectedCardIndex];
    if (!card) return new Set<string>();

    const [r0, c0] = rangeOrigin.pos;
    const maxRange = card.range;
    const cells = new Set<string>();

    if (maxRange < 0) {
      for (let r = 0; r < 9; r++) {
        for (let c = 3; c < 8; c++) {
          cells.add(`${r},${c}`);
        }
      }
      return cells;
    }

    for (let dr = -maxRange; dr <= maxRange; dr++) {
      for (let dc = -maxRange; dc <= maxRange; dc++) {
        if (dr === 0 && dc === 0) continue;
        const r = r0 + dr;
        const c = c0 + dc;
        if (r >= 0 && r < 9 && c >= 3 && c < 8) {
          cells.add(`${r},${c}`);
        }
      }
    }
    return cells;
  }, [combatUIMode, selectedCardIndex, displayedHand, rangeOrigin]);

  const handleCellClick = useCallback(
    async (row: number, col: number) => {
      if (!effectiveId || !combatState) return;

      const doAction = (action: { action: string; card_index?: number; target: [number, number] }) =>
        combatTestId
          ? api.combatTestAction(combatTestId, action)
          : api.combatAction(sessionId!, action);

      // TARGETING: play card
      if (combatUIMode === "TARGETING" && selectedCardIndex !== null) {
        setLoading(true);
        try {
          await doAction({
            action: "play_card",
            card_index: selectedCardIndex,
            target: [row, col],
          });
          setSelectedCardIndex(null);
          setSelectedUnitId(null);
          setCombatUIMode("VIEWING");
          await fetchState();
        } catch {
          setError("操作失败");
        } finally {
          setLoading(false);
        }
        return;
      }

      // Unit selected + clicked a move-highlighted cell → move
      if (selectedUnitId && moveHighlights.has(`${row},${col}`)) {
        setLoading(true);
        try {
          await doAction({ action: "move", target: [row, col] });
          setSelectedUnitId(null);
          setCombatUIMode("VIEWING");
          await fetchState();
        } catch {
          setError("移动失败");
        } finally {
          setLoading(false);
        }
        return;
      }

      // Click on a player unit → select it
      const unit = combatState.units.find(
        (u) => u.is_alive && u.pos[0] === row && u.pos[1] === col && u.team === "player"
      );
      if (unit) {
        setSelectedUnitId(selectedUnitId === unit.unit_id ? null : unit.unit_id);
        setCombatUIMode("VIEWING");
        setSelectedCardIndex(null);
        setCursor([row, col]);
        return;
      }

      // Clicked empty/invalid cell → deselect
      setSelectedUnitId(null);
      setCombatUIMode("VIEWING");
      setSelectedCardIndex(null);
      setCursor([row, col]);
    },
    [effectiveId, combatTestId, sessionId, combatState, combatUIMode, selectedCardIndex, selectedUnitId, moveHighlights, api, fetchState, setSelectedCardIndex, setCombatUIMode, setSelectedUnitId]
  );

  const handleCardClick = useCallback(
    (index: number) => {
      if (combatUIMode === "TARGETING" && selectedCardIndex === index) {
        setSelectedCardIndex(null);
        setCombatUIMode("VIEWING");
        return;
      }
      setSelectedCardIndex(index);
      setCombatUIMode("TARGETING");
    },
    [combatUIMode, selectedCardIndex, setSelectedCardIndex, setCombatUIMode]
  );

  const handleEndTurn = useCallback(async () => {
    if (!effectiveId) return;
    setLoading(true);
    try {
      if (combatTestId) {
        await api.combatTestEndTurn(combatTestId);
      } else {
        await api.combatEndTurn(sessionId!);
      }
      setCombatUIMode("VIEWING");
      setSelectedCardIndex(null);
      setSelectedUnitId(null);
      await fetchState();
    } catch {
      setError("结束回合失败");
    } finally {
      setLoading(false);
    }
  }, [effectiveId, combatTestId, sessionId, api, fetchState, setCombatUIMode, setSelectedCardIndex, setSelectedUnitId]);

  const handleCancel = useCallback(() => {
    setCombatUIMode("VIEWING");
    setSelectedCardIndex(null);
    setCursor(null);
    setSelectedUnitId(null);
  }, [setCombatUIMode, setSelectedCardIndex, setSelectedUnitId]);

  const handleCardDragStart = useCallback((index: number) => {
    setDragCardIndex(index);
    setSelectedCardIndex(index);
    setCombatUIMode("TARGETING");
  }, [setSelectedCardIndex, setCombatUIMode]);

  const handleCardDragEnd = useCallback(() => {
    setDragCardIndex(null);
    setDragCell(null);
  }, []);

  const handleGridDragMove = useCallback((cell: [number, number] | null) => {
    setDragCell(cell);
  }, []);

  const handleGridDrop = useCallback(
    async (row: number, col: number) => {
      if (!effectiveId || !combatState || dragCardIndex === null) return;
      setLoading(true);
      try {
        const doAction = (action: { action: string; card_index?: number; target: [number, number] }) =>
          combatTestId
            ? api.combatTestAction(combatTestId, action)
            : api.combatAction(sessionId!, action);
        await doAction({
          action: "play_card",
          card_index: dragCardIndex,
          target: [row, col],
        });
        setSelectedCardIndex(null);
        setSelectedUnitId(null);
        setCombatUIMode("VIEWING");
        await fetchState();
      } catch {
        setError("操作失败");
      } finally {
        setLoading(false);
        setDragCardIndex(null);
        setDragCell(null);
      }
    },
    [effectiveId, combatTestId, sessionId, combatState, dragCardIndex, api, fetchState, setSelectedCardIndex, setCombatUIMode, setSelectedUnitId]
  );

  const handleUnitClick = useCallback((unitId: string) => {
    if (selectedUnitId === unitId) {
      setSelectedUnitId(null);
      setCombatUIMode("VIEWING");
      setSelectedCardIndex(null);
    } else {
      setSelectedUnitId(unitId);
      setCombatUIMode("VIEWING");
      setSelectedCardIndex(null);
    }
  }, [selectedUnitId, setSelectedUnitId, setCombatUIMode, setSelectedCardIndex]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!combatState || combatState.battle_over) return;
      if (e.key === "f" || e.key === "F") {
        handleEndTurn();
        return;
      }
      if (e.key === "Escape") {
        if (selectedUnitId) {
          setSelectedUnitId(null);
          setCombatUIMode("VIEWING");
          setSelectedCardIndex(null);
        } else {
          handleCancel();
        }
        return;
      }
      const num = parseInt(e.key);
      if (num >= 1 && num <= 5) {
        const idx = num - 1;
        if (idx < combatState.shared_hand.length) {
          handleCardClick(idx);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [combatState, selectedUnitId, handleEndTurn, handleCancel, handleCardClick, setSelectedUnitId, setCombatUIMode, setSelectedCardIndex]);

  if (!combatState) {
    return (
      <div className="flex items-center justify-center h-full bg-combat-bg">
        <div className="bg-surface-card border border-combat-border rounded-xl p-6 w-96 shadow-2xl">
          <h2 className="text-lg font-bold text-gray-200 mb-4 font-display tracking-wide">
            开始战斗
          </h2>

          {!sessionId && (
            <p className="text-sm text-combat-gold/80 mb-3">
              未选择会话 — 可使用下方"战斗测试"直接开战，或先在对话页面创建会话
            </p>
          )}

          {error && (
            <div className="bg-red-950/50 border border-red-800 rounded-lg px-3 py-2 mb-3 text-sm text-red-300">
              {error}
              <button className="ml-2 text-red-400 hover:text-red-200" onClick={() => setError(null)}>x</button>
            </div>
          )}

          <label className="block text-xs text-gray-500 mb-1 font-display tracking-wider">遭遇战</label>
          <input
            className="w-full bg-surface-dark border border-combat-border rounded-lg px-3 py-2 text-sm text-gray-200 mb-4 focus:border-combat-player transition-colors"
            value={encounterId}
            onChange={(e) => setEncounterId(e.target.value)}
          />

          <label className="block text-xs text-gray-500 mb-1 font-display tracking-wider">出战角色 (会话模式)</label>
          <div className="flex flex-wrap gap-1 mb-2">
            {startChars.map((c) => (
              <span key={c} className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-cyan-950/50 border border-cyan-900/50 text-cyan-300 rounded-full">
                {c}
                <button className="text-gray-500 hover:text-red-400 ml-0.5" onClick={() => removeChar(c)}>×</button>
              </span>
            ))}
          </div>
          <div className="flex gap-1.5 mb-4">
            <input
              className="flex-1 bg-surface-dark border border-combat-border rounded-lg px-3 py-1.5 text-xs text-gray-200 focus:border-combat-player transition-colors"
              placeholder="输入角色名"
              value={charInput}
              onChange={(e) => setCharInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addChar()}
            />
            <button className="px-3 py-1.5 text-xs bg-surface-hover hover:bg-gray-700 text-gray-300 rounded-lg transition-colors" onClick={addChar}>
              添加
            </button>
          </div>

          <button
            className="w-full py-2.5 bg-cyan-900 hover:bg-cyan-800 text-cyan-200 rounded-lg text-sm font-medium transition-all disabled:opacity-40 mb-3 border border-cyan-800/50"
            onClick={handleStartBattle}
            disabled={!sessionId || startChars.length === 0 || loading}
          >
            {loading ? "启动中..." : "开始战斗"}
          </button>

          <div className="border-t border-combat-divider pt-3 mt-1">
            <p className="text-xs text-gray-600 mb-2">
              测试模式：无需会话，从 data/plots/combat-test/index.md 加载角色和随机敌人
            </p>
            <button
              className="w-full py-2.5 bg-emerald-900/60 hover:bg-emerald-800/60 text-emerald-200 rounded-lg text-sm font-medium transition-all disabled:opacity-40 border border-emerald-800/50"
              onClick={handleStartTestBattle}
              disabled={loading}
            >
              {loading ? "启动中..." : "战斗测试 (无需会话)"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  const sharedAp = combatState.shared_ap ?? 0;
  const sharedApMax = combatState.shared_ap_max ?? 6;
  const activeUnitName = activeUnit?.name ?? "?";

  return (
    <div className="flex flex-col h-full bg-combat-bg relative">
      {/* Error toast */}
      {error && (
        <div className="absolute top-3 right-3 z-50 bg-red-950/95 border border-red-800 text-red-200 px-4 py-2 rounded-lg text-sm shadow-lg">
          {error}
          <button className="ml-2 text-red-400 hover:text-red-200" onClick={() => setError(null)}>×</button>
        </div>
      )}

      {/* Main area: status panels + grid */}
      <div className="flex-1 flex items-start justify-center p-4 gap-4 relative">
        {/* Player status — left panel */}
        <div className="w-56 flex-shrink-0 max-h-[calc(100vh-320px)] overflow-y-auto bg-surface-card/90 border border-combat-border rounded-xl p-3 backdrop-blur-sm">
          <UnitStatusPanel
            units={combatState.units}
            activeUnitId={combatState.active_unit_id}
            selectedUnitId={selectedUnitId}
            team="player"
            sharedAp={sharedAp}
            sharedApMax={sharedApMax}
            onUnitClick={handleUnitClick}
          />
        </div>

        {/* Grid area */}
        <div className="flex flex-col items-center">
          {/* Turn info */}
          <div className="mb-4 text-center">
            <span className="text-sm text-gray-300 font-display tracking-wider">
              ROUND {combatState.round_num}
            </span>
            <span className={`ml-3 text-xs font-bold ${
              combatState.phase === "PLAYER_TURN" ? "text-combat-player" : "text-combat-enemy"
            }`}>
              {combatState.phase === "PLAYER_TURN" ? "我方行动" : "敌方行动"}
            </span>
            {activeUnit && combatState.phase === "PLAYER_TURN" && (
              <span className="text-xs text-cyan-400 ml-3">当前: {activeUnitName}</span>
            )}
          </div>

          {/* Grid with damage numbers overlay */}
          <div className="relative">
            <CombatGrid
              gridSize={combatState.grid_size}
              units={combatState.units}
              grid={combatState.grid ?? {}}
              validTargets={combatState.valid_targets ?? []}
              validMoves={[]}
              moveHighlights={moveHighlights}
              rangeHighlights={rangeHighlights}
              selectedUnitId={selectedUnitId}
              uiMode={combatUIMode}
              cursor={cursor}
              dragCell={dragCell}
              onCellClick={handleCellClick}
              onCellDrop={handleGridDrop}
              onGridDragMove={handleGridDragMove}
            />

            {/* Damage numbers */}
            {damageNumbers.map((d) => (
              <span
                key={d.id}
                className={`damage-number ${d.type === "heal" ? "heal" : d.type === "arts" ? "arts" : "physical"}`}
                style={{
                  position: "absolute",
                  left: `${CELL + d.pos[1] * (CELL + 2)}px`,
                  top: `${d.pos[0] * (CELL + 2)}px`,
                  zIndex: 100,
                }}
              >
                {d.type === "heal" ? `+${d.value}` : `-${d.value}`}
              </span>
            ))}

            {/* Particle effects */}
            <CombatParticles
              width={8 * (CELL + 2) + CELL}
              height={9 * (CELL + 2) + 20}
              emitters={particleEmitters}
              onEmitterDone={removeEmitter}
            />
          </div>

          {/* Action hint */}
          <div className="mt-3 flex gap-4 text-xs text-gray-600 min-h-[20px]">
            {combatUIMode === "TARGETING" && (
              <span className="text-dmg-physical">点击目标格子使用卡牌 · Esc 取消</span>
            )}
            {combatUIMode === "VIEWING" && selectedUnit && (
              <span className="text-combat-player">
                已选中 {selectedUnit.name} · 移速 {selectedUnit.mobility} · 点击手牌攻击 · 点击蓝框移动 · Esc 取消
              </span>
            )}
            {combatUIMode === "VIEWING" && !selectedUnit && combatState.phase === "PLAYER_TURN" && (
              <span className="text-gray-500">点击角色头像或地图选中 · 按数字键 1-5 快捷出牌</span>
            )}
          </div>
        </div>

        {/* Enemy status — right panel */}
        <div className="w-56 flex-shrink-0 max-h-[calc(100vh-320px)] overflow-y-auto bg-surface-card/90 border border-combat-border rounded-xl p-3 backdrop-blur-sm">
          <UnitStatusPanel
            units={combatState.units}
            activeUnitId={combatState.active_unit_id}
            selectedUnitId={selectedUnitId}
            team="enemy"
            onUnitClick={handleUnitClick}
          />
        </div>
      </div>

      {/* Bottom: hand + controls + event log */}
      <div className="border-t border-combat-divider bg-surface-dark/80 backdrop-blur-sm">
        {/* Action bar */}
        <div className="flex items-center gap-3 px-4 py-2">
          <span className="text-xs text-gray-500 font-display">
            手牌: {displayedHand.length}
            {selectedUnit && (
              <span className="text-combat-player ml-1">({selectedUnit.name})</span>
            )}
          </span>
          <span className="text-xs text-gray-500 font-display">
            AP: <span className="text-white font-bold">{sharedAp}</span>/{sharedApMax}
          </span>
          <div className="flex-1" />
          <button
            className="px-5 py-1.5 text-xs bg-cyan-900/70 hover:bg-cyan-800/70 text-cyan-200 rounded-lg transition-all disabled:opacity-30 border border-cyan-800/50 font-display tracking-wider"
            onClick={handleEndTurn}
            disabled={combatState.phase !== "PLAYER_TURN" || combatState.battle_over || loading}
          >
            结束回合 (F)
          </button>
          {(combatUIMode === "TARGETING" || selectedUnit) && (
            <button
              className="px-4 py-1.5 text-xs bg-surface-hover hover:bg-gray-700 text-gray-300 rounded-lg transition-all border border-combat-border"
              onClick={handleCancel}
            >
              取消 (Esc)
            </button>
          )}
          {combatState.battle_over && (
            <button
              className="px-5 py-1.5 text-xs bg-yellow-900/60 hover:bg-yellow-800/60 text-yellow-200 rounded-lg transition-all border border-yellow-800/50"
              onClick={() => {
                sseRef.current?.close();
                setCombatState(null);
                setCombatTestId(null);
                setSelectedUnitId(null);
                setCurrentView("chat");
              }}
            >
              返回对话
            </button>
          )}
        </div>

        {/* Hand */}
        <CombatHand
          cards={displayedHand}
          activeAp={sharedAp}
          selectedIndex={selectedCardIndex}
          disabled={!!selectedUnit && !isSelectedActive}
          onCardClick={handleCardClick}
          onCardDragStart={handleCardDragStart}
          onCardDragEnd={handleCardDragEnd}
        />

        {/* Event log */}
        <div className="px-3 pb-3">
          <CombatEventLog events={events} />
        </div>
      </div>

      {/* Battle end overlay */}
      {combatState.battle_over && result && (
        <div className="combat-overlay-enter absolute inset-0 flex items-center justify-center bg-black/70 z-40">
          <div className="bg-surface-card border border-combat-border rounded-2xl p-10 text-center shadow-2xl">
            <div className={`text-5xl font-black mb-4 font-display tracking-widest ${
              result === "胜利" ? "text-combat-gold" : "text-combat-enemy"
            }`}>
              {result === "胜利" ? "VICTORY" : "DEFEAT"}
            </div>
            <div className="text-gray-500 text-sm mb-6 font-display">
              战斗结束 — 共 {combatState.round_num} 回合
            </div>
            <button
              className="px-8 py-2.5 bg-cyan-900/70 hover:bg-cyan-800/70 text-cyan-200 rounded-lg transition-all border border-cyan-800/50 font-display tracking-wider"
              onClick={() => {
                sseRef.current?.close();
                setCombatState(null);
                setCombatTestId(null);
                setCurrentView("chat");
              }}
            >
              返回对话
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
