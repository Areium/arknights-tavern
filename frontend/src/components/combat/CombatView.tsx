import { useEffect, useState, useCallback, useRef } from "react";
import { useAppStore } from "../../stores/appStore";
import { useApi, createCombatSSE } from "../../hooks/useApi";
import type { CombatEventDTO, CombatStateDTO } from "../../types";
import CombatGrid from "./CombatGrid";
import CombatHand from "./CombatHand";
import CombatEventLog from "./CombatEventLog";
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
  const sseRef = useRef<{ close: () => void } | null>(null);
  const stateRef = useRef(combatState);
  stateRef.current = combatState;

  const sessionId = activeSessionId || (sessions.length > 0 ? sessions[0].id : null);

  const fetchState = useCallback(async () => {
    if (!sessionId) return;
    try {
      const state = await api.combatState(sessionId);
      setCombatState(state as CombatStateDTO);
      if (state.battle_over && state.winner) {
        setResult(state.winner === "player" ? "胜利" : "失败");
      }
    } catch {
      // no combat active
    }
  }, [sessionId, api, setCombatState]);

  const connectSSE = useCallback(() => {
    if (!sessionId) return;
    sseRef.current?.close();
    sseRef.current = createCombatSSE(sessionId, {
      onEvent: (ev) => {
        setEvents((prev) => [...prev.slice(-200), ev as CombatEventDTO]);
        if (ev.type === "battle_end") {
          setResult(ev.data.winner === "player" ? "胜利" : "失败");
          fetchState();
        }
      },
      onError: (msg) => setError(msg),
      onDone: () => fetchState(),
    });
  }, [sessionId, fetchState]);

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

  const handleCellClick = useCallback(
    async (row: number, col: number) => {
      if (!sessionId || !combatState) return;

      if (combatUIMode === "TARGETING" && selectedCardIndex !== null) {
        setLoading(true);
        try {
          await api.combatAction(sessionId, {
            action: "play_card",
            card_index: selectedCardIndex,
            target: [row, col],
          });
          setSelectedCardIndex(null);
          setCombatUIMode("VIEWING");
          await fetchState();
        } catch {
          setError("操作失败");
        } finally {
          setLoading(false);
        }
        return;
      }

      if (combatUIMode === "MOVING") {
        setLoading(true);
        try {
          await api.combatAction(sessionId, {
            action: "move",
            target: [row, col],
          });
          setCombatUIMode("VIEWING");
          await fetchState();
        } catch {
          setError("移动失败");
        } finally {
          setLoading(false);
        }
        return;
      }

      // VIEWING mode: click an own unit to prepare movement
      const unit = combatState.units.find(
        (u) => u.is_alive && u.pos[0] === row && u.pos[1] === col && u.team === "player"
      );
      if (unit && combatState.phase === "PLAYER_TURN") {
        setCursor([row, col]);
        setCombatUIMode("MOVING");
        // fetch state to get valid moves — or reuse current if engine sets them
        return;
      }

      setCursor([row, col]);
    },
    [sessionId, combatState, combatUIMode, selectedCardIndex, api, fetchState, setSelectedCardIndex, setCombatUIMode]
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
    if (!sessionId) return;
    setLoading(true);
    try {
      await api.combatEndTurn(sessionId);
      setCombatUIMode("VIEWING");
      setSelectedCardIndex(null);
      await fetchState();
    } catch {
      setError("结束回合失败");
    } finally {
      setLoading(false);
    }
  }, [sessionId, api, fetchState, setCombatUIMode, setSelectedCardIndex]);

  const handleCancel = useCallback(() => {
    setCombatUIMode("VIEWING");
    setSelectedCardIndex(null);
    setCursor(null);
  }, [setCombatUIMode, setSelectedCardIndex]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!combatState || combatState.battle_over) return;
      if (e.key === "f" || e.key === "F") {
        handleEndTurn();
        return;
      }
      if (e.key === "Escape") {
        handleCancel();
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
  }, [combatState, handleEndTurn, handleCancel, handleCardClick]);

  if (!combatState) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="bg-gray-900 border border-gray-700 rounded-lg p-6 w-96">
          <h2 className="text-lg font-bold text-gray-200 mb-4">开始战斗</h2>

          {!sessionId && (
            <p className="text-sm text-red-400 mb-3">请先在对话页面创建或选择一个会话</p>
          )}

          <label className="block text-xs text-gray-400 mb-1">遭遇战</label>
          <input
            className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 mb-3"
            value={encounterId}
            onChange={(e) => setEncounterId(e.target.value)}
          />

          <label className="block text-xs text-gray-400 mb-1">出战角色</label>
          <div className="flex flex-wrap gap-1 mb-2">
            {startChars.map((c) => (
              <span key={c} className="inline-flex items-center gap-1 px-2 py-0.5 text-xs bg-cyan-900/60 text-cyan-200 rounded">
                {c}
                <button className="text-gray-400 hover:text-red-300" onClick={() => removeChar(c)}>x</button>
              </span>
            ))}
          </div>
          <div className="flex gap-1 mb-4">
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
            className="w-full py-2 bg-cyan-700 hover:bg-cyan-600 text-cyan-200 rounded text-sm font-medium transition-colors disabled:opacity-40"
            onClick={handleStartBattle}
            disabled={!sessionId || startChars.length === 0 || loading}
          >
            {loading ? "启动中..." : "开始战斗"}
          </button>
        </div>
      </div>
    );
  }

  const activeAp =
    combatState.units
      .filter((u) => u.team === "player" && u.is_alive)
      .reduce((sum, u) => sum + u.personal_ap, 0) ?? 0;

  const activeUnit = combatState.units.find((u) => u.unit_id === combatState.active_unit_id) ?? null;
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

      {/* Main area: grid + sidebar */}
      <div className="flex flex-1 overflow-hidden">
        {/* Grid area */}
        <div className="flex-1 flex flex-col items-center justify-center p-4">
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
            uiMode={combatUIMode}
            cursor={cursor}
            onCellClick={handleCellClick}
          />

          {/* Action hint */}
          <div className="mt-2 flex gap-4 text-xs text-gray-500">
            {combatUIMode === "TARGETING" && (
              <span className="text-green-400">点击目标格子使用卡牌 · Esc 取消</span>
            )}
            {combatUIMode === "MOVING" && (
              <span className="text-blue-400">点击目标格子移动单位 · Esc 取消</span>
            )}
            {combatUIMode === "VIEWING" && combatState.phase === "PLAYER_TURN" && (
              <span>点击手牌使用卡牌 · 点击单位移动</span>
            )}
          </div>
        </div>

        {/* Right sidebar: unit status */}
        <div className="w-56 border-l border-gray-700 overflow-y-auto p-1">
          <UnitStatusPanel units={combatState.units} activeUnitId={combatState.active_unit_id} />
        </div>
      </div>

      {/* Bottom: hand + controls + event log */}
      <div className="border-t border-gray-700 bg-gray-950/60">
        {/* Action bar */}
        <div className="flex items-center gap-3 px-3 py-1.5">
          <span className="text-xs text-gray-400">
            AP: <span className="text-cyan-400 font-mono">{activeAp}</span>
          </span>
          <span className="text-xs text-gray-500">
            | 手牌: {combatState.shared_hand.length}
          </span>
          <div className="flex-1" />
          <button
            className="px-4 py-1 text-xs bg-cyan-800 hover:bg-cyan-700 text-cyan-200 rounded transition-colors disabled:opacity-30"
            onClick={handleEndTurn}
            disabled={combatState.phase !== "PLAYER_TURN" || combatState.battle_over || loading}
          >
            结束回合 (F)
          </button>
          {(combatUIMode === "TARGETING" || combatUIMode === "MOVING") && (
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
              onClick={() => {
                setCombatState(null);
                setCurrentView("chat");
              }}
            >
              返回
            </button>
          )}
        </div>

        {/* Hand */}
        <CombatHand
          cards={combatState.shared_hand}
          activeAp={activeAp}
          selectedIndex={selectedCardIndex}
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
              onClick={() => {
                sseRef.current?.close();
                setCombatState(null);
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
