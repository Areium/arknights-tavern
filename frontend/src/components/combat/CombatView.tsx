import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useAppStore } from "../../stores/appStore";
import { useApi, createCombatSSE, createCombatTestSSE } from "../../hooks/useApi";
import type { CombatEventDTO, CombatStateDTO } from "../../types";
import CombatGrid from "./CombatGrid";
import CombatHand from "./CombatHand";
import CombatEventLog from "./CombatEventLog";
import CombatUnitTooltip from "./CombatUnitTooltip";
import UnitStatusPanel from "./UnitStatusPanel";

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
  const [startChars, setStartChars] = useState<string[]>(DEFAULT_CHARACTERS);
  const [encounterId, setEncounterId] = useState(DEFAULT_ENCOUNTER);
  const [charInput, setCharInput] = useState("");
  const [hoveredUnitId, setHoveredUnitId] = useState<string | null>(null);
  const [hoveredUnitRect, setHoveredUnitRect] = useState<DOMRect | null>(null);
  const writingBackRef = useRef(false);
  const sseRef = useRef<{ close: () => void } | null>(null);
  const stateRef = useRef(combatState);
  stateRef.current = combatState;

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
        if (ev.type === "battle_end") {
          setResult(ev.data.winner === "player" ? "胜利" : "失败");
          fetchState();
        }
      },
      onError: (msg: string) => setError(msg),
      onDone: () => fetchState(),
    };
    sseRef.current = combatTestId
      ? createCombatTestSSE(combatTestId, handlers)
      : createCombatSSE(sessionId!, handlers);
  }, [effectiveId, combatTestId, sessionId, fetchState]);

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
      // SSE will connect via the useEffect that triggers on combatTestId change
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

  // Cards to display: always the active unit's hand
  const displayedHand = combatState?.shared_hand ?? [];

  const isSelectedActive = selectedUnit?.unit_id === combatState?.active_unit_id;

  // Highlight cards belonging to the selected character (if not active)
  const highlightOwner = selectedUnit && !isSelectedActive ? selectedUnit.name : null;

  // Hovered unit for tooltip
  const hoveredUnit = hoveredUnitId
    ? combatState?.units.find((u) => u.unit_id === hoveredUnitId) ?? null
    : null;

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

  const handleReturnToChat = useCallback(async () => {
    if (writingBackRef.current) return;
    sseRef.current?.close();

    // Writeback: only for session-based combat (not test)
    if (!combatTestId && sessionId && combatState) {
      writingBackRef.current = true;
      const survivors = combatState.units
        .filter((u) => u.is_alive && u.team === "player")
        .map((u) => u.name);
      const characterStats: Record<string, any> = {};
      for (const u of combatState.units) {
        if (u.team === "player") {
          characterStats[u.name] = {
            hp: u.hp,
            max_hp: u.max_hp,
            attributes: u.attributes,
            is_alive: u.is_alive,
          };
        }
      }
      try {
        await api.combatComplete(sessionId, {
          encounter_id: encounterId,
          winner: combatState.winner || "unknown",
          survivors,
          rounds: combatState.round_num,
          character_stats: characterStats,
        });
      } catch {
        // Non-critical — silently ignore writeback failures
      }
      writingBackRef.current = false;
    }

    setCombatState(null);
    setCombatTestId(null);
    setSelectedUnitId(null);
    setCurrentView("chat");
  }, [combatTestId, sessionId, combatState, encounterId, api, setCombatState, setCombatTestId, setSelectedUnitId, setCurrentView]);

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

  // Hover tooltip
  const handleCellHover = useCallback((unit: CombatStateDTO["units"][number], rect: DOMRect) => {
    setHoveredUnitId(unit.unit_id);
    setHoveredUnitRect(rect);
  }, []);

  const handleUnitHover = useCallback((unitId: string, rect: DOMRect) => {
    setHoveredUnitId(unitId);
    setHoveredUnitRect(rect);
  }, []);

  const handleHoverLeave = useCallback(() => {
    setHoveredUnitId(null);
    setHoveredUnitRect(null);
  }, []);

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
      <div className="flex items-center justify-center h-full">
        <div className="bg-gray-900 border border-gray-700 rounded-lg p-6 w-96">
          <h2 className="text-lg font-bold text-gray-200 mb-4">开始战斗</h2>

          {!sessionId && (
            <p className="text-sm text-yellow-400 mb-3">
              未选择会话 — 可使用下方"战斗测试"直接开战，或先在对话页面创建会话
            </p>
          )}

          {error && (
            <div className="bg-red-900/50 border border-red-700 rounded px-3 py-2 mb-3 text-sm text-red-300">
              {error}
              <button className="ml-2 text-red-400 hover:text-red-200" onClick={() => setError(null)}>x</button>
            </div>
          )}

          <label className="block text-xs text-gray-400 mb-1">遭遇战</label>
          <input
            className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 mb-3"
            value={encounterId}
            onChange={(e) => setEncounterId(e.target.value)}
          />

          <label className="block text-xs text-gray-400 mb-1">出战角色 (会话模式)</label>
          <div className="flex flex-wrap gap-1 mb-2">
            {startChars.map((c) => (
              <span key={c} className="inline-flex items-center gap-1 px-2 py-0.5 text-xs bg-cyan-900/60 text-cyan-200 rounded">
                {c}
                <button className="text-gray-400 hover:text-red-300" onClick={() => removeChar(c)}>x</button>
              </span>
            ))}
          </div>
          <div className="flex gap-1 mb-3">
            <input
              className="flex-1 bg-gray-800 border border-gray-600 rounded px-2 py-1 text-xs text-gray-200"
              placeholder="输入角色名"
              value={charInput}
              onChange={(e) => setCharInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addChar()}
            />
            <button className="px-3 py-1 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded" onClick={addChar}>
              添加
            </button>
          </div>

          <button
            className="w-full py-2 bg-cyan-700 hover:bg-cyan-600 text-cyan-200 rounded text-sm font-medium transition-colors disabled:opacity-40 mb-2"
            onClick={handleStartBattle}
            disabled={!sessionId || startChars.length === 0 || loading}
          >
            {loading ? "启动中..." : "开始战斗"}
          </button>

          <div className="border-t border-gray-700 pt-3 mt-1">
            <p className="text-xs text-gray-500 mb-2">
              测试模式：无需会话，从 data/plots/combat-test/index.md 加载角色和随机敌人
            </p>
            <button
              className="w-full py-2 bg-emerald-800 hover:bg-emerald-700 text-emerald-200 rounded text-sm font-medium transition-colors disabled:opacity-40"
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
  const activeUnitName = activeUnit?.name ?? "?";

  return (
    <div className="flex flex-col h-full">
      {/* Error toast */}
      {error && (
        <div className="absolute top-2 right-2 z-50 bg-red-900/90 text-red-200 px-3 py-1.5 rounded text-sm">
          {error}
          <button className="ml-2 text-red-400 hover:text-red-200" onClick={() => setError(null)}>
            x
          </button>
        </div>
      )}

      {/* Main area: grid */}
      <div className="flex-1 flex flex-col items-center justify-center p-4 relative">
        {/* Player status — top-left overlay */}
        <div className="absolute top-2 left-2 z-30 w-48 max-h-72 overflow-y-auto bg-gray-900/90 border border-gray-700 rounded-lg p-2">
          <UnitStatusPanel
            units={combatState.units}
            activeUnitId={combatState.active_unit_id}
            selectedUnitId={selectedUnitId}
            team="player"
            sharedAp={combatState.shared_ap}
            sharedApMax={combatState.shared_ap_max}
            onUnitClick={handleUnitClick}
            onUnitHover={handleUnitHover}
            onUnitLeave={handleHoverLeave}
          />
        </div>

        {/* Enemy status — top-right overlay */}
        <div className="absolute top-2 right-2 z-30 w-48 max-h-72 overflow-y-auto bg-gray-900/90 border border-gray-700 rounded-lg p-2">
          <UnitStatusPanel
            units={combatState.units}
            activeUnitId={combatState.active_unit_id}
            selectedUnitId={selectedUnitId}
            team="enemy"
            onUnitClick={handleUnitClick}
            onUnitHover={handleUnitHover}
            onUnitLeave={handleHoverLeave}
          />
        </div>

        {/* Turn info */}
        <div className="mb-3 text-center">
          <span className="text-sm text-gray-300">
            Round {combatState.round_num} —{" "}
            {combatState.phase === "PLAYER_TURN" ? "我方回合" : "敌方回合"}
          </span>
          {activeUnit && combatState.phase === "PLAYER_TURN" && (
            <span className="text-xs text-cyan-400 ml-3">当前: {activeUnitName}</span>
          )}
        </div>

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
          onCellClick={handleCellClick}
          onCellHover={handleCellHover}
          onCellLeave={handleHoverLeave}
        />

        {/* Action hint */}
        <div className="mt-2 flex gap-4 text-xs text-gray-500">
          {combatUIMode === "TARGETING" && (
            <span className="text-green-400">点击目标格子使用卡牌 · Esc 取消</span>
          )}
          {combatUIMode === "VIEWING" && selectedUnit && (
            <span className="text-blue-400">
              已选中 {selectedUnit.name} · 移动力 {selectedUnit.mobility} · 点击手牌攻击 · 点击格子移动 · Esc 取消
            </span>
          )}
          {combatUIMode === "VIEWING" && !selectedUnit && combatState.phase === "PLAYER_TURN" && (
            <span>点击角色头像或状态栏选中 · 点击手牌攻击</span>
          )}
        </div>
      </div>

      {/* Bottom: hand + controls + event log */}
      <div className="border-t border-gray-700 bg-gray-950/60">
        {/* Action bar */}
        <div className="flex items-center gap-3 px-3 py-1.5">
          <span className="text-xs text-gray-500">
            手牌: {displayedHand.length}
            {selectedUnit && (
              <span className="text-cyan-400 ml-1">({selectedUnit.name})</span>
            )}
          </span>
          <div className="flex-1" />
          <button
            className="px-4 py-1 text-xs bg-cyan-800 hover:bg-cyan-700 text-cyan-200 rounded transition-colors disabled:opacity-30"
            onClick={handleEndTurn}
            disabled={combatState.phase !== "PLAYER_TURN" || combatState.battle_over || loading}
          >
            结束回合 (F)
          </button>
          {(combatUIMode === "TARGETING" || selectedUnit) && (
            <button
              className="px-3 py-1 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded transition-colors"
              onClick={handleCancel}
            >
              取消 (Esc)
            </button>
          )}
          {combatState.battle_over && (
            <button
              className="px-4 py-1 text-xs bg-yellow-700 hover:bg-yellow-600 text-yellow-200 rounded transition-colors"
              onClick={handleReturnToChat}
            >
              返回
            </button>
          )}
        </div>

        {/* Hand */}
        <CombatHand
          cards={displayedHand}
          activeAp={sharedAp}
          selectedIndex={selectedCardIndex}
          disabled={!!selectedUnit && !isSelectedActive}
          highlightOwner={highlightOwner}
          onCardClick={handleCardClick}
        />

        {/* Event log */}
        <div className="px-2 pb-2">
          <CombatEventLog events={events} />
        </div>
      </div>

      {/* Battle end overlay */}
      {combatState.battle_over && result && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/60 z-40">
          <div className="bg-gray-900 border border-gray-600 rounded-lg p-8 text-center">
            <div className={`text-4xl font-bold mb-4 ${result === "胜利" ? "text-yellow-300" : "text-red-400"}`}>
              {result === "胜利" ? "VICTORY" : "DEFEAT"}
            </div>
            <div className="text-gray-400 text-sm mb-6">
              战斗结束 — 共 {combatState.round_num} 回合
            </div>
            <button
              className="px-6 py-2 bg-cyan-700 hover:bg-cyan-600 text-cyan-200 rounded transition-colors"
              onClick={handleReturnToChat}
            >
              返回对话
            </button>
          </div>
        </div>
      )}

      {/* Hover tooltip */}
      {hoveredUnit && hoveredUnitRect && (
        <CombatUnitTooltip
          unit={hoveredUnit}
          anchorRect={hoveredUnitRect}
          onMouseLeave={handleHoverLeave}
        />
      )}
    </div>
  );
}
