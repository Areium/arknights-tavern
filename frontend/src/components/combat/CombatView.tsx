import { useEffect, useLayoutEffect, useState, useCallback, useRef, useMemo } from "react";
import { useAppStore } from "../../stores/appStore";
import { useApi, createCombatSSE, createCombatTestSSE } from "../../hooks/useApi";
import type { CombatEventDTO, CombatStateDTO, CardDTO } from "../../types";
import CombatGrid from "./CombatGrid";
import CombatHand from "./CombatHand";
import CombatEventLog from "./CombatEventLog";
import CombatUnitTooltip from "./CombatUnitTooltip";
import UnitStatusPanel from "./UnitStatusPanel";
import CombatParticles from "./CombatParticles";
import CombatCard from "./CombatCard";
import DeckViewer from "./DeckViewer";
import AttackArrow from "./AttackArrow";
import ChibiSprite from "./ChibiSprite";
import { getCellParentRelative } from "./gridUtils";
import { getCombatConfig, type LayoutMode } from "./combatConfig";

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
  const errorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (error) {
      errorTimerRef.current = setTimeout(() => setError(null), 5000);
    }
    return () => {
      if (errorTimerRef.current) {
        clearTimeout(errorTimerRef.current);
        errorTimerRef.current = null;
      }
    };
  }, [error]);
  const [result, setResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [cursor, setCursor] = useState<[number, number] | null>(null);
  const [dragCardIndex, setDragCardIndex] = useState<number | null>(null);
  const [dragCell, setDragCell] = useState<[number, number] | null>(null);
  const [startChars, setStartChars] = useState<string[]>(DEFAULT_CHARACTERS);
  const [encounterId, setEncounterId] = useState(DEFAULT_ENCOUNTER);
  const [charInput, setCharInput] = useState("");
  const [hoveredUnitId, setHoveredUnitId] = useState<string | null>(null);
  const [hoveredUnitRect, setHoveredUnitRect] = useState<DOMRect | null>(null);
  const [showDeckViewer, setShowDeckViewer] = useState(false);
  const [deckFilterMode, setDeckFilterMode] = useState<"all" | "deck" | "discard">("all");
  const [resizeTick, setResizeTick] = useState(0);
  const [unitPositions, setUnitPositions] = useState<Record<string, { x: number; y: number } | null>>({});
  const [isFullscreen, setIsFullscreen] = useState(
    () => window.innerWidth / screen.availWidth > 0.9 && window.innerHeight / screen.availHeight > 0.85
  );
  const layoutMode: LayoutMode = isFullscreen ? "fullscreen" : "windowed";
  const cfg = getCombatConfig(layoutMode);
  const writingBackRef = useRef(false);
  const sseRef = useRef<{ close: () => void } | null>(null);
  const stateRef = useRef(combatState);
  stateRef.current = combatState;
  const gridElRef = useRef<HTMLDivElement | null>(null);
  const relativeRef = useRef<HTMLDivElement | null>(null);
  const dragMouseRef = useRef<{ clientX: number; clientY: number } | null>(null);
  const overlayCentersRef = useRef<({ x: number; y: number } | null)[][]>([]);
  const lastHoveredCellRef = useRef<string | null>(null);

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
      const center = gridElRef.current && relativeRef.current
        ? getCellParentRelative(gridElRef.current, relativeRef.current, pos[0], pos[1])
        : null;
      let x: number, y: number;
      if (center) {
        x = center.x;
        y = center.y;
      } else {
        const gap = 2;
        const sz = cfg.cellSize;
        x = sz + 5 + pos[1] * (sz + gap) + sz / 2;
        y = sz - 12 + pos[0] * (sz + gap) + sz / 2;
      }
      setParticleEmitters((prev) => [...prev.slice(-30), { id, config: { type, x, y, count } }]);
    },
    [cfg.cellSize]
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

  // Re-render chibi overlay on window resize (positions shift with perspective)
  useEffect(() => {
    const handler = () => {
      setResizeTick((t) => t + 1);
      setIsFullscreen(
        window.innerWidth / screen.availWidth > 0.9 &&
        window.innerHeight / screen.availHeight > 0.85
      );
    };
    window.addEventListener("resize", handler);
    return () => window.removeEventListener("resize", handler);
  }, []);

  // Precompute cell screen centers for overlay drag handling
  const recomputeOverlayCenters = useCallback(() => {
    const g = gridElRef.current;
    const rel = relativeRef.current;
    if (!g || !rel) return;
    const size = combatState?.grid_size ?? 7;
    const centers: ({ x: number; y: number } | null)[][] = [];
    for (let r = 0; r < size; r++) {
      const row: ({ x: number; y: number } | null)[] = [];
      for (let c = 0; c < size; c++) {
        row.push(getCellParentRelative(g, rel, r, c));
      }
      centers.push(row);
    }
    overlayCentersRef.current = centers;
  }, [combatState?.grid_size]);

  useEffect(() => {
    recomputeOverlayCenters();
  }, [recomputeOverlayCenters, resizeTick]);

  // Sync unit positions (chibi, damage numbers) after DOM commits — handles cellSize / layout changes
  useLayoutEffect(() => {
    const g = gridElRef.current;
    const rel = relativeRef.current;
    if (!g || !rel) return;
    const positions: Record<string, { x: number; y: number } | null> = {};
    for (const u of combatState?.units ?? []) {
      if (u.is_alive) {
        positions[u.unit_id] = getCellParentRelative(g, rel, u.pos[0], u.pos[1]);
      }
    }
    setUnitPositions(positions);
    recomputeOverlayCenters();
  }, [combatState?.units, cfg.cellSize, resizeTick]);

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

  // Cards to display: always the active unit's hand
  const displayedHand = combatState?.shared_hand ?? [];

  // Arrow start position: the card owner's cell, or fall back to rangeOrigin
  const arrowFrom = useMemo(() => {
    if (dragCardIndex === null || !combatState) return null;
    const card = displayedHand[dragCardIndex];
    if (!card?.owner) return null;
    const ownerUnit = combatState.units.find(
      (u) => u.team === "player" && u.is_alive && u.name === card.owner
    );
    return ownerUnit?.pos ?? null;
  }, [dragCardIndex, combatState, displayedHand]);

  // Highlight cards belonging to the selected character
  const highlightOwner = selectedUnit ? selectedUnit.name : null;

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
    const gs = combatState?.grid_size ?? 7;
    const cells = new Set<string>();
    for (let dr = -mobility; dr <= mobility; dr++) {
      for (let dc = -mobility; dc <= mobility; dc++) {
        if (dr === 0 && dc === 0) continue;
        if (Math.abs(dr) > mobility || Math.abs(dc) > mobility) continue;
        const r = r0 + dr;
        const c = c0 + dc;
        if (r >= 0 && r < gs && c >= 0 && c < gs) {
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

    const gs = combatState?.grid_size ?? 7;

    if (maxRange < 0) {
      for (let r = 0; r < gs; r++) {
        for (let c = 0; c < gs; c++) {
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
        if (r >= 0 && r < gs && c >= 0 && c < gs) {
          cells.add(`${r},${c}`);
        }
      }
    }
    return cells;
  }, [combatUIMode, selectedCardIndex, displayedHand, rangeOrigin]);

  const handleCellClick = useCallback(
    async (row: number, col: number) => {
      if (!effectiveId || !combatState) return;

      const doAction = (action: { action: string; card_index?: number; unit_id?: string; target: [number, number] }) =>
        combatTestId
          ? api.combatTestAction(combatTestId, action)
          : api.combatAction(sessionId!, action);

      // TARGETING: play card
      if (combatUIMode === "TARGETING" && selectedCardIndex !== null) {
        const card = displayedHand[selectedCardIndex];
        // Validate target is within the card's range
        if (!rangeHighlights.has(`${row},${col}`)) {
          const unitAtCell = combatState.units.find(
            (u) => u.is_alive && u.pos[0] === row && u.pos[1] === col
          );
          if (unitAtCell && unitAtCell.team === "enemy") {
            setError("目标不在攻击范围内，无法选中");
          } else if (unitAtCell && unitAtCell.team === "player") {
            setError("无法对己方角色使用攻击卡牌");
          } else {
            setSelectedCardIndex(null);
            setSelectedUnitId(null);
            setCombatUIMode("VIEWING");
          }
          return;
        }
        // AP check
        if (card && (combatState.shared_ap ?? 0) < card.cost) {
          setError(`AP 不足 (${combatState.shared_ap ?? 0} / ${card.cost})`);
          return;
        }

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
        } catch (e: any) {
          setError(e?.message || "操作失败");
        } finally {
          setLoading(false);
        }
        return;
      }

      // Unit selected + clicked a cell → move or show error
      if (selectedUnitId) {
        const unitAtCell = combatState.units.find(
          (u) => u.is_alive && u.pos[0] === row && u.pos[1] === col
        );
        // Clicked an occupied cell that's not in move range
        if (unitAtCell && !moveHighlights.has(`${row},${col}`)) {
          if (unitAtCell.unit_id === selectedUnitId) {
            setSelectedUnitId(null);
          } else {
            setSelectedUnitId(unitAtCell.unit_id);
          }
          setCombatUIMode("VIEWING");
          setSelectedCardIndex(null);
          setCursor([row, col]);
          return;
        }
        // Clicked a move-highlighted cell
        if (moveHighlights.has(`${row},${col}`)) {
          if ((combatState.shared_ap ?? 0) < 1) {
            setError("AP 不足，无法移动 (需要 1 AP)");
            return;
          }
          setLoading(true);
          try {
            await doAction({ action: "move", unit_id: selectedUnitId, target: [row, col] });
            setCursor([row, col]);
            await fetchState();
          } catch (e: any) {
            setError(e?.message || "移动失败");
          } finally {
            setLoading(false);
          }
          return;
        }
      }

      // Click on any unit → select it (player or enemy)
      const unit = combatState.units.find(
        (u) => u.is_alive && u.pos[0] === row && u.pos[1] === col
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
    [effectiveId, combatTestId, sessionId, combatState, combatUIMode, selectedCardIndex, selectedUnitId, moveHighlights, rangeHighlights, displayedHand, api, fetchState, setSelectedCardIndex, setCombatUIMode, setSelectedUnitId]
  );

  const handleCardClick = useCallback(
    (index: number) => {
      if (combatUIMode === "TARGETING" && selectedCardIndex === index) {
        setSelectedCardIndex(null);
        setCombatUIMode("VIEWING");
        setSelectedUnitId(null);
        return;
      }
      setSelectedCardIndex(index);
      setCombatUIMode("TARGETING");
      const state = stateRef.current;
      if (state) {
        const card = state.shared_hand[index];
        if (card?.owner) {
          const ownerUnit = state.units.find(
            (u) => u.team === "player" && u.is_alive && u.name === card.owner
          );
          if (ownerUnit) {
            setSelectedUnitId(ownerUnit.unit_id);
          }
        }
      }
    },
    [combatUIMode, selectedCardIndex, setSelectedCardIndex, setCombatUIMode, setSelectedUnitId]
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
    } catch (e: any) {
      setError(e?.message || "结束回合失败");
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

  // Click on main area → map to grid cell or deselect.
  // Cell mapping handles 3D-transformed cells (rows 4-8) that don't
  // receive events directly because of browser 3D hit-testing quirks.
  const handleGridBackgroundClick = useCallback(
    (e: React.MouseEvent) => {
      const rel = relativeRef.current;
      if (rel && combatState) {
        const rect = rel.getBoundingClientRect();
        const rx = e.clientX - rect.left;
        const ry = e.clientY - rect.top;
        const centers = overlayCentersRef.current;
        const gs = combatState.grid_size;
        let best: [number, number] | null = null;
        let bestDist = Infinity;
        for (let r = 0; r < gs; r++) {
          const row = centers[r];
          if (!row) continue;
          for (let c = 0; c < gs; c++) {
            const pt = row[c];
            if (!pt) continue;
            const dx = rx - pt.x;
            const dy = ry - pt.y;
            const dist = dx * dx + dy * dy;
            if (dist < bestDist) {
              bestDist = dist;
              best = [r, c];
            }
          }
        }
        // Only treat as cell click if within ~45px of cell center (cell half-diagonal)
        if (best && bestDist <= 2000) {
          handleCellClick(best[0], best[1]);
          return;
        }
      }
      // Background click — deselect
      setSelectedUnitId(null);
      setSelectedCardIndex(null);
      setCombatUIMode("VIEWING");
      setCursor(null);
      setError(null);
    },
    [combatState, handleCellClick, setSelectedUnitId, setSelectedCardIndex, setCombatUIMode],
  );

  const handleCardDragStart = useCallback((index: number) => {
    setDragCardIndex(index);
    setSelectedCardIndex(index);
    setCombatUIMode("TARGETING");
    const state = stateRef.current;
    if (state) {
      const card = state.shared_hand[index];
      if (card?.owner) {
        const ownerUnit = state.units.find(
          (u) => u.team === "player" && u.is_alive && u.name === card.owner
        );
        if (ownerUnit) {
          setSelectedUnitId(ownerUnit.unit_id);
        }
      }
    }
  }, [setSelectedCardIndex, setCombatUIMode, setSelectedUnitId]);

  const handleCardDragEnd = useCallback(() => {
    setDragCardIndex(null);
    setDragCell(null);
    setSelectedCardIndex(null);
    setSelectedUnitId(null);
    setCombatUIMode("VIEWING");
  }, [setSelectedCardIndex, setSelectedUnitId, setCombatUIMode]);

  const handleGridDragMove = useCallback((cell: [number, number] | null, clientX?: number, clientY?: number) => {
    setDragCell(cell);
    if (clientX !== undefined && clientY !== undefined) {
      dragMouseRef.current = { clientX, clientY };
    } else {
      dragMouseRef.current = null;
    }
  }, []);

  const handleGridDrop = useCallback(
    async (row: number, col: number) => {
      if (!effectiveId || !combatState || dragCardIndex === null) return;

      const card = displayedHand[dragCardIndex];
      // Validate target is within the card's range
      if (!rangeHighlights.has(`${row},${col}`)) {
        const unitAtCell = combatState.units.find(
          (u) => u.is_alive && u.pos[0] === row && u.pos[1] === col
        );
        if (unitAtCell && unitAtCell.team === "enemy") {
          setError("目标不在攻击范围内，无法选中");
        } else if (unitAtCell && unitAtCell.team === "player") {
          setError("无法对己方角色使用攻击卡牌");
        }
        setDragCardIndex(null);
        setDragCell(null);
        setSelectedCardIndex(null);
        setSelectedUnitId(null);
        setCombatUIMode("VIEWING");
        return;
      }
      // AP check
      if (card && (combatState.shared_ap ?? 0) < card.cost) {
        setError(`AP 不足 (${combatState.shared_ap ?? 0} / ${card.cost})`);
        setDragCardIndex(null);
        setDragCell(null);
        return;
      }

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
      } catch (e: any) {
        setError(e?.message || "操作失败");
      } finally {
        setLoading(false);
        setDragCardIndex(null);
        setDragCell(null);
      }
    },
    [effectiveId, combatTestId, sessionId, combatState, dragCardIndex, rangeHighlights, displayedHand, api, fetchState, setSelectedCardIndex, setCombatUIMode, setSelectedUnitId]
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

  return (
    <div className="flex flex-col h-full bg-combat-bg relative" onDragOver={(e) => e.preventDefault()}>
      {/* Main area: status panels + grid */}
      <div className="flex-1 flex items-start justify-between px-2 gap-2 relative z-10 select-none" onClick={handleGridBackgroundClick}>
        {/* Player status — left panel */}
        <div className="w-56 flex-shrink-0 max-h-[calc(100vh-320px)] overflow-y-auto bg-surface-card/90 border border-combat-border rounded-xl p-3 backdrop-blur-sm" onClick={(e) => e.stopPropagation()}>
          <UnitStatusPanel
            units={combatState.units}
            activeUnitId={combatState.active_unit_id}
            selectedUnitId={selectedUnitId}
            team="player"
            sharedAp={sharedAp}
            sharedApMax={sharedApMax}
            onUnitClick={handleUnitClick}
            onUnitHover={handleUnitHover}
            onUnitLeave={handleHoverLeave}
          />
        </div>

        {/* Grid area — positioned with relative+top to avoid layout conflicts with bottom bar */}
        <div className="flex flex-col items-center relative" style={{ top: `${cfg.gridMarginTop}px` }}>
          {/* Turn info + error toast (error uses absolute positioning to avoid pushing grid) */}
          <div className="relative mb-2 text-center" style={{ marginTop: isFullscreen ? '-28px' : undefined }}>
            <span className="text-sm text-gray-300 font-display tracking-wider">
              ROUND {combatState.round_num}
            </span>
            <span className={`ml-3 text-xs font-bold ${
              combatState.phase === "PLAYER_TURN" ? "text-combat-player" : "text-combat-enemy"
            }`}>
              {combatState.phase === "PLAYER_TURN" ? "Player Turn" : "Enemy Turn"}
            </span>
            {error && (
              <div className="absolute left-1/2 -translate-x-1/2 top-full mt-1 z-50 bg-red-950/95 border border-red-800 text-red-200 px-4 py-1.5 rounded-lg text-xs shadow-lg animate-pulse whitespace-nowrap">
                {error}
                <button className="ml-2 text-red-400 hover:text-red-200" onClick={() => setError(null)}>×</button>
              </div>
            )}
          </div>

          {/* Grid with damage numbers overlay */}
          <div className="relative" ref={relativeRef} style={{ "--cell-size": `${cfg.cellSize}px` } as React.CSSProperties}
            onMouseMove={(e) => {
              const rel = relativeRef.current;
              if (!rel) return;
              const rect = rel.getBoundingClientRect();
              const rx = e.clientX - rect.left;
              const ry = e.clientY - rect.top;
              const centers = overlayCentersRef.current;
              const gs = combatState.grid_size;
              let best: [number, number] | null = null;
              let bestDist = Infinity;
              for (let r = 0; r < gs; r++) {
                const row = centers[r];
                if (!row) continue;
                for (let c = 0; c < gs; c++) {
                  const pt = row[c];
                  if (!pt) continue;
                  const dx = rx - pt.x;
                  const dy = ry - pt.y;
                  const dist = dx * dx + dy * dy;
                  if (dist < bestDist) {
                    bestDist = dist;
                    best = [r, c];
                  }
                }
              }
              const cellKey = best ? `${best[0]},${best[1]}` : null;
              if (cellKey === lastHoveredCellRef.current) return;
              lastHoveredCellRef.current = cellKey;
              if (best && combatState) {
                const unit = combatState.units.find(
                  (u) => u.is_alive && u.pos[0] === best![0] && u.pos[1] === best![1]
                );
                if (unit) {
                  const c = centers[best[0]]?.[best[1]];
                  setHoveredUnitId(unit.unit_id);
                  setHoveredUnitRect(c
                    ? new DOMRect(rect.left + c.x - 28, rect.top + c.y - 28, 56, 56)
                    : new DOMRect(0, 0, 0, 0));
                } else {
                  setHoveredUnitId(null);
                  setHoveredUnitRect(null);
                }
              } else {
                setHoveredUnitId(null);
                setHoveredUnitRect(null);
              }
            }}
            onMouseLeave={() => {
              lastHoveredCellRef.current = null;
              setHoveredUnitId(null);
              setHoveredUnitRect(null);
            }}
            onDragOver={(e) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = "move";
              const centers = overlayCentersRef.current;
              const gs = combatState.grid_size;
              let best: [number, number] | null = null;
              let bestDist = Infinity;
              for (let r = 0; r < gs; r++) {
                const row = centers[r];
                if (!row) continue;
                for (let c = 0; c < gs; c++) {
                  const pt = row[c];
                  if (!pt) continue;
                  const relRect = relativeRef.current?.getBoundingClientRect();
                  const sx = pt.x + (relRect?.left ?? 0);
                  const sy = pt.y + (relRect?.top ?? 0);
                  const dx = e.clientX - sx;
                  const dy = e.clientY - sy;
                  const dist = dx * dx + dy * dy;
                  if (dist < bestDist) {
                    bestDist = dist;
                    best = [r, c];
                  }
                }
              }
              handleGridDragMove(best, e.clientX, e.clientY);
            }}
            onDrop={(e) => {
              e.preventDefault();
              const centers = overlayCentersRef.current;
              const gs = combatState.grid_size;
              let best: [number, number] | null = null;
              let bestDist = Infinity;
              for (let r = 0; r < gs; r++) {
                const row = centers[r];
                if (!row) continue;
                for (let c = 0; c < gs; c++) {
                  const pt = row[c];
                  if (!pt) continue;
                  const relRect = relativeRef.current?.getBoundingClientRect();
                  const sx = pt.x + (relRect?.left ?? 0);
                  const sy = pt.y + (relRect?.top ?? 0);
                  const dx = e.clientX - sx;
                  const dy = e.clientY - sy;
                  const dist = dx * dx + dy * dy;
                  if (dist < bestDist) {
                    bestDist = dist;
                    best = [r, c];
                  }
                }
              }
              if (best) handleGridDrop(best[0], best[1]);
              handleGridDragMove(null);
            }}
          >
            <CombatGrid
              gridSize={combatState.grid_size}
              cellSize={cfg.cellSize}
              units={combatState.units}
              moveHighlights={moveHighlights}
              rangeHighlights={rangeHighlights}
              selectedUnitId={selectedUnitId}
              uiMode={combatUIMode}
              cursor={cursor}
              dragCell={dragCell}
              onCellClick={handleCellClick}
              onCellHover={handleCellHover}
              onCellLeave={handleHoverLeave}
              onCellDrop={handleGridDrop}
              onGridDragMove={handleGridDragMove}
              onGridMount={(el) => { gridElRef.current = el; }}
            />

            {/* Chibi sprite overlay — uses pre-computed positions from useLayoutEffect */}
            {combatState.units
              .filter((u) => u.is_alive)
              .map((u) => {
                const center = unitPositions[u.unit_id];
                if (!center) return null;
                return (
                  <div
                    key={u.unit_id}
                    className="chibi-overlay"
                    style={{
                      position: "absolute",
                      left: center.x - 24,
                      top: center.y - 30,
                      zIndex: 25,
                      pointerEvents: "none",
                    }}
                  >
                    <ChibiSprite unit={u} />
                  </div>
                );
              })}

            {/* Damage numbers */}
            {damageNumbers.map((d) => {
              const center = gridElRef.current && relativeRef.current
                ? getCellParentRelative(gridElRef.current, relativeRef.current, d.pos[0], d.pos[1])
                : null;
              return (
                <span
                  key={d.id}
                  className={`damage-number ${d.type === "heal" ? "heal" : d.type === "arts" ? "arts" : "physical"}`}
                  style={{
                    position: "absolute",
                    left: center ? `${center.x - 14}px` : `${cfg.cellSize + d.pos[1] * (cfg.cellSize + 2)}px`,
                    top: center ? `${center.y - 14}px` : `${d.pos[0] * (cfg.cellSize + 2)}px`,
                    zIndex: 100,
                    pointerEvents: "none",
                  }}
                >
                  {d.type === "heal" ? `+${d.value}` : `-${d.value}`}
                </span>
              );
            })}

            {/* Particle effects */}
            <CombatParticles
              emitters={particleEmitters}
              onEmitterDone={removeEmitter}
            />

            {/* Attack arrow during card drag */}
            {arrowFrom && dragCell && gridElRef.current && relativeRef.current && (() => {
              const m = dragMouseRef.current;
              const pr = relativeRef.current.getBoundingClientRect();
              const toPoint = m ? { x: m.clientX - pr.left, y: m.clientY - pr.top } : null;
              return (
                <AttackArrow
                  from={arrowFrom}
                  to={dragCell}
                  toPoint={toPoint}
                  gridEl={gridElRef.current!}
                  parentEl={relativeRef.current}
                />
              );
            })()}
          </div>

          {/* Action hint */}
          <div className="mt-3 flex gap-4 text-xs text-gray-600 min-h-[20px]" onClick={(e) => e.stopPropagation()}>
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
        <div className="w-56 flex-shrink-0 max-h-[calc(100vh-320px)] overflow-y-auto bg-surface-card/90 border border-combat-border rounded-xl p-3 backdrop-blur-sm" onClick={(e) => e.stopPropagation()}>
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
      </div>

      {/* Bottom: hand + controls + event log */}
      <div className="border-t border-combat-divider bg-surface-dark/80 pointer-events-none" style={{ marginTop: cfg.bottomBarMarginTop }}>
        {/* Action bar */}
        <div className="flex items-center gap-3 px-4 py-1 relative z-20 pointer-events-auto">
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
            className="px-3 py-1.5 text-xs bg-surface-hover hover:bg-gray-700 text-gray-300 rounded-lg transition-all border border-combat-border font-display tracking-wider"
            onClick={() => { setDeckFilterMode("all"); setShowDeckViewer(true); }}
          >
            卡组
          </button>
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
              onClick={handleReturnToChat}
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
          disabled={combatState.phase !== "PLAYER_TURN"}
          highlightOwner={highlightOwner}
          onCardClick={handleCardClick}
          onCardDragStart={handleCardDragStart}
          onCardDragEnd={handleCardDragEnd}
          cardWidth={cfg.cardWidth}
          cardHeight={cfg.cardHeight}
          fanMarginTop={cfg.handFanMarginTop}
        />

        {/* Event log */}
        <div className="px-3 pb-3 pointer-events-auto">
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
              onClick={handleReturnToChat}
            >
              返回对话
            </button>
          </div>
        </div>
      )}

      {/* Floating deck/discard pile buttons */}
      {combatState && combatState.phase === "PLAYER_TURN" && !combatState.battle_over && (
        <>
          <button
            className="fixed left-60 bottom-24 z-30 flex items-center gap-2 px-3 py-2 bg-surface-card/90 hover:bg-surface-card border border-combat-border rounded-xl shadow-lg transition-all backdrop-blur-sm pointer-events-auto"
            onClick={() => { setDeckFilterMode("deck"); setShowDeckViewer(true); }}
            title="抽牌堆"
          >
            <span className="text-lg">🂠</span>
            <span className="text-[11px] text-gray-300 font-display tracking-wider">抽牌堆</span>
            <span className="text-xs text-cyan-300 font-mono bg-cyan-950/50 px-1.5 py-0.5 rounded">
              {combatState.shared_pool?.deck?.length ?? 0}
            </span>
          </button>
          <button
            className="fixed right-4 bottom-24 z-30 flex items-center gap-2 px-3 py-2 bg-surface-card/90 hover:bg-surface-card border border-combat-border rounded-xl shadow-lg transition-all backdrop-blur-sm pointer-events-auto"
            onClick={() => { setDeckFilterMode("discard"); setShowDeckViewer(true); }}
            title="弃牌堆"
          >
            <span className="text-[11px] text-gray-300 font-display tracking-wider">弃牌堆</span>
            <span className="text-xs text-amber-300 font-mono bg-amber-950/50 px-1.5 py-0.5 rounded">
              {combatState.shared_pool?.discard?.length ?? 0}
            </span>
            <span className="text-lg">🗂</span>
          </button>
        </>
      )}

      {/* Deck viewer modal */}
      {showDeckViewer && combatState && (
        <DeckViewer
          units={combatState.units}
          sharedPool={combatState.shared_pool ?? { deck: [], hand: [], discard: [], exhaust: [] }}
          filterMode={deckFilterMode}
          onClose={() => setShowDeckViewer(false)}
        />
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
