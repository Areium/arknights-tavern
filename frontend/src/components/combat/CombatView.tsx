import { useEffect, useLayoutEffect, useState, useCallback, useRef, useMemo } from "react";
import { useAppStore } from "../../stores/appStore";
import { useApi, createCombatSSE, createCombatTestSSE } from "../../hooks/useApi";
import type { CombatEventDTO, CombatStateDTO, CardDTO } from "../../types";
import PixiCombatScene, { type PixiCombatSceneHandle } from "./PixiCombatScene";
import { audioManager } from "../../audio/audioManager";
import CombatGrid from "./CombatGrid";
import { getCellCenter, resolveTargetPattern } from "./gridUtils";
import CombatHand from "./CombatHand";
import CombatEventLog from "./CombatEventLog";
import CombatUnitTooltip from "./CombatUnitTooltip";
import UnitStatusPanel from "./UnitStatusPanel";
import CombatParticles from "./CombatParticles";
import DeckViewer from "./DeckViewer";
import AttackArrow from "./AttackArrow";
import CharacterIllustration from "./CharacterIllustration";
import CombatQuestBar from "./CombatQuestBar";
import CardFlyOverlay, { type CardFlight } from "./CardFlyOverlay";
import { getCombatConfig, type LayoutMode } from "./combatConfig";

const DEFAULT_CHARACTERS = ["阿米娅", "博士", "银灰", "霜星"];
const DEFAULT_ENCOUNTER = "初遇整合运动";

const INTENT_BADGE: Record<string, { icon: string; cls: string }> = {
  attack: { icon: "⚔", cls: "bg-red-950/85 text-red-200 border-red-700" },
  heavy: { icon: "💢", cls: "bg-red-900/85 text-red-100 border-red-600" },
  aoe: { icon: "🌐", cls: "bg-orange-950/85 text-orange-200 border-orange-700" },
  move: { icon: "👣", cls: "bg-amber-950/85 text-amber-200 border-amber-700" },
  defend: { icon: "🛡", cls: "bg-gray-800/85 text-gray-300 border-gray-600" },
};

export default function CombatView() {
  const {
    activeSessionId,
    sessions,
    setSessions,
    combatContext: ctx,
    setCombatContext,
    setCurrentView,
    setPendingAutoNarrate,
  } = useAppStore();
  const {
    state: combatState,
    uiMode: combatUIMode,
    selectedCardIndex,
    testId: combatTestId,
    sessionId: combatSessionId,
    selectedUnitId,
  } = ctx;
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
  // 战斗奖励结算结果（胜利后展示）
  const [rewards, setRewards] = useState<{
    xp: number;
    items: string[];
    level_ups: { name: string; level: number; attribute: string }[];
    card_choices?: CardDTO[];
  } | null>(null);
  const [showRewards, setShowRewards] = useState(false);
  const [pickedCardId, setPickedCardId] = useState<string | null>(null);
  // 战前打法（Approach）选择
  const [approaches, setApproaches] = useState<{ id: string; label: string; hint: string; kind: string }[] | null>(null);
  const [checkResult, setCheckResult] = useState<{ d20: number; modifier: number; total: number; dc: number; success: boolean; attr: string; character: string } | null>(null);
  const [avoidMsg, setAvoidMsg] = useState<string | null>(null);
  const [cursor, setCursor] = useState<[number, number] | null>(null);
  const [hoverCell, setHoverCell] = useState<[number, number] | null>(null);
  const [dragCardIndex, setDragCardIndex] = useState<number | null>(null);
  const [dragCell, setDragCell] = useState<[number, number] | null>(null);
  const [playingCardIndex, setPlayingCardIndex] = useState<number | null>(null);
  const [cardFlight, setCardFlight] = useState<CardFlight | null>(null);
  const clearCardFlight = useCallback(() => setCardFlight(null), []);
  const cardPlayInProgressRef = useRef(false);
  const [startChars, setStartChars] = useState<string[]>(DEFAULT_CHARACTERS);
  const [encounterId, setEncounterId] = useState(DEFAULT_ENCOUNTER);
  const [charInput, setCharInput] = useState("");
  const [hoveredUnitId, setHoveredUnitId] = useState<string | null>(null);
  const [hoveredUnitRect, setHoveredUnitRect] = useState<DOMRect | null>(null);
  const [showDeckViewer, setShowDeckViewer] = useState(false);
  const [deckFilterMode, setDeckFilterMode] = useState<"all" | "deck" | "discard">("all");
  const [resizeTick, setResizeTick] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(
    () => window.innerWidth / screen.availWidth > 0.9 && window.innerHeight / screen.availHeight > 0.85
  );
  const layoutMode: LayoutMode = isFullscreen ? "fullscreen" : "windowed";
  const cfg = getCombatConfig(layoutMode);
  const writingBackRef = useRef(false);
  const pixiRef = useRef<PixiCombatSceneHandle>(null);
  const [muted, setMuted] = useState(audioManager.getSettings().muted);

  // 首次用户点击解锁 AudioContext（浏览器自动播放策略）
  useEffect(() => {
    const unlock = () => audioManager.ensureCtx();
    document.addEventListener("click", unlock, { once: true });
    return () => document.removeEventListener("click", unlock);
  }, []);
  const sseRef = useRef<{ close: () => void } | null>(null);
  const stateRef = useRef(combatState);
  stateRef.current = combatState;
  const gridRef = useRef<HTMLDivElement | null>(null);
  const relativeRef = useRef<HTMLDivElement | null>(null);
  const [gridEl, setGridEl] = useState<HTMLDivElement | null>(null);
  const [containerEl, setContainerEl] = useState<HTMLDivElement | null>(null);
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
      const grid = gridRef.current;
      const rel = relativeRef.current;
      let x: number = 0, y: number = 0;
      if (grid && rel) {
        const sp = getCellCenter(grid, pos[0], pos[1]);
        if (sp) {
          const relRect = rel.getBoundingClientRect();
          x = sp.x - relRect.left;
          y = sp.y - relRect.top;
        }
      }
      setParticleEmitters((prev) => [...prev.slice(-30), { id, config: { type, x, y, count } }]);
    },
    [],
  );

  const removeEmitter = useCallback((id: string) => {
    setParticleEmitters((prev) => prev.filter((e) => e.id !== id));
  }, []);

  const sessionId = combatSessionId || activeSessionId || (sessions.length > 0 ? sessions[0].id : null);
  const effectiveId = combatTestId || sessionId;

  const fetchState = useCallback(async () => {
    if (!effectiveId) return;
    try {
      const state = combatTestId
        ? await api.combatTestState(combatTestId)
        : await api.combatState(sessionId!);
      setCombatContext({ state: state as CombatStateDTO });
      if (state.battle_over && state.winner) {
        setResult(state.winner === "player" ? "胜利" : "失败");
      }
    } catch {
      // no combat active
    }
  }, [effectiveId, combatTestId, sessionId, api, setCombatContext]);

  const connectSSE = useCallback(() => {
    if (!effectiveId) return;
    sseRef.current?.close();
    const handlers = {
      onEvent: (ev: any) => {
        setEvents((prev) => [...prev.slice(-200), ev as CombatEventDTO]);
        // Spawn damage numbers + particles
        if (ev.type === "damage") {
          const pos = ev.data.target_pos || [4, 4];
          const hr = ev.data.hit_result || "";
          if (ev.data?.damage > 0) {
            addDamageNumber(ev.data.damage, ev.data.damage_type || "physical", pos);
            spawnParticles("spark", pos, 8 + Math.floor(ev.data.damage / 5));
            // Spine 动作：攻击者播攻击、目标播受击
            pixiRef.current?.playAttack(ev.data.unit_id);
            pixiRef.current?.playHit(ev.data.target_id);
            if (/crit/i.test(hr)) audioManager.playSfx("crit");
            else {
              const dtype = ev.data.damage_type || "physical";
              audioManager.playSfx(
                dtype === "arts" ? "hit_arts" : dtype === "mixed" ? "hit_mixed" : "hit_physical"
              );
            }
          } else if (/miss|dodge/i.test(hr)) {
            // 闪避/未命中：浮动文字 + miss 音效
            addDamageNumber(0, "miss", pos);
            pixiRef.current?.playAttack(ev.data.unit_id);
            audioManager.playSfx("miss");
          }
        }
        if (ev.type === "heal" && ev.data?.amount > 0) {
          const pos = ev.data.target_pos || [4, 4];
          addDamageNumber(ev.data.amount, "heal", pos);
          spawnParticles("heal", pos, 6);
          audioManager.playSfx("heal");
        }
        if (ev.type === "status") {
          // 状态效果音效：护盾 → shield，其余 → ui
          if (ev.data.type === "shield") audioManager.playSfx("shield");
          else audioManager.playSfx("ui");
        }
        if (ev.type === "death") {
          const pos = ev.data.pos || [4, 4];
          spawnParticles("death", pos, 15);
          pixiRef.current?.playDeath(ev.data.unit_id);
          audioManager.playSfx(ev.data.team === "enemy" ? "enemy_death" : "death");
        }
        if (ev.type === "move") {
          pixiRef.current?.moveTo(ev.data.unit_id, ev.data.to_pos, 300);
        }
        if (ev.type === "card_played") {
          audioManager.playSfx("card");
        }
        if (ev.type === "battle_start") {
          audioManager.startBgm();
        }
        if (ev.type === "battle_end") {
          const w = ev.data.winner;
          setResult(w === "player" ? "胜利" : w === "escaped" ? "撤退" : "失败");
          if (w === "player") {
            spawnParticles("victory", [4, 4], 40);
            audioManager.playSfx("victory");
          } else {
            audioManager.playSfx("defeat");
          }
          audioManager.stopBgm();
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

  // Auto-fetch when entering via LLM combat trigger (combat already started externally)
  useEffect(() => {
    if (combatSessionId && !combatState && !loading) {
      setLoading(true);
      fetchState().then(() => {
        setLoading(false);
        connectSSE();
      }).catch(() => setLoading(false));
    }
  }, [combatSessionId]);

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
    const grid = gridRef.current;
    const rel = relativeRef.current;
    if (!grid || !rel) return;
    const size = combatState?.grid_size ?? 7;
    const relRect = rel.getBoundingClientRect();
    const centers: ({ x: number; y: number } | null)[][] = [];
    for (let r = 0; r < size; r++) {
      const row: ({ x: number; y: number } | null)[] = [];
      for (let c = 0; c < size; c++) {
        const sp = getCellCenter(grid, r, c);
        if (sp) {
          row.push({ x: sp.x - relRect.left, y: sp.y - relRect.top });
        } else {
          row.push(null);
        }
      }
      centers.push(row);
    }
    overlayCentersRef.current = centers;
  }, [combatState?.grid_size]);

  useEffect(() => {
    recomputeOverlayCenters();
  }, [recomputeOverlayCenters, resizeTick]);

  // Recompute cell screen centers when units or cell size changes
  useLayoutEffect(() => {
    recomputeOverlayCenters();
  }, [combatState?.units, cfg.cellSize, resizeTick, recomputeOverlayCenters]);

  const startCombat = useCallback(async (approachId?: string) => {
    if (!sessionId || startChars.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const resp = await api.combatStart(sessionId, encounterId, startChars, approachId);
      if (resp?.state) {
        setCombatContext({ state: resp.state as CombatStateDTO });
        setEvents([]);
        setResult(null);
        setDamageNumbers([]);
        setApproaches(null);
        setAvoidMsg(null);
        setCheckResult(resp.check ?? null);
        connectSSE();
      } else if (resp?.kind === "approaches") {
        setApproaches(resp.approaches || []);
        setCheckResult(null);
        setAvoidMsg(null);
      } else if (resp?.kind === "check") {
        setCheckResult(resp.check ?? null);
        setApproaches(null);
        setAvoidMsg(null);
      } else if (resp?.kind === "avoid") {
        setAvoidMsg(resp.label || "已撤退");
        setApproaches(null);
        setCheckResult(null);
      }
    } catch (e: any) {
      setError(e.message || "启动战斗失败");
    } finally {
      setLoading(false);
    }
  }, [sessionId, encounterId, startChars, api, setCombatContext, connectSSE]);

  const handleStartBattle = useCallback(() => {
    startCombat(undefined);
  }, [startCombat]);

  const handleSelectApproach = useCallback((approachId: string) => {
    startCombat(approachId);
  }, [startCombat]);

  const handleStartTestBattle = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.combatTestStart(encounterId);
      setCombatContext({ state: result.state as CombatStateDTO, testId: result.test_id });
      setEvents([]);
      setResult(null);
      setDamageNumbers([]);
    } catch (e: any) {
      setError(e.message || "启动战斗测试失败");
    } finally {
      setLoading(false);
    }
  }, [encounterId, api, setCombatContext]);

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

  // Calculate total available AP for a card (owner's personal AP + shared AP)
  const getCardAp = useCallback((card: CardDTO) => {
    if (!combatState) return 0;
    const owner = combatState.units.find(
      u => u.team === "player" && u.is_alive && u.name === card.owner
    );
    return (owner?.personal_ap ?? 0) + (combatState.shared_ap ?? 0);
  }, [combatState]);

  // Build owner name → {url, crop} mapping for card face images
  const ownerSkins = useMemo(() => {
    if (!combatState) return {};
    const map: Record<string, { url: string; crop: import("../../types").SkinCrop | null }> = {};
    for (const u of combatState.units) {
      if (u.team === "player" && u.skin_url) {
        map[u.name] = { url: u.skin_url, crop: u.skin_crop ?? null };
      }
    }
    return map;
  }, [combatState]);

  // 出牌飞行动画：从手牌卡面飞向目标格子（视口坐标，与 getBoundingClientRect 一致）
  const launchCardFlight = useCallback((cardIdx: number, row: number, col: number) => {
    const card = displayedHand[cardIdx];
    const grid = gridRef.current;
    if (!card || !grid || cardFlight) return;
    const to = getCellCenter(grid, row, col);
    if (!to) return;
    const el = document.querySelector(
      '.hand-card-wrapper[data-hand-index="' + cardIdx + '"] .combat-card'
    );
    const from = el?.getBoundingClientRect();
    if (!from) return;
    setCardFlight({
      card,
      from,
      to,
      skinUrl: card.owner ? ownerSkins?.[card.owner]?.url : undefined,
    });
  }, [displayedHand, ownerSkins, cardFlight]);

  // Hovered unit for tooltip
  const hoveredUnit = hoveredUnitId
    ? combatState?.units.find((u) => u.unit_id === hoveredUnitId) ?? null
    : null;

  // Move range from selected unit's mobility (Chebyshev distance, mobility//2)
  const moveHighlights = useMemo(() => {
    if (!selectedUnit || !selectedUnit.is_alive || selectedUnit.team !== "player") {
      return new Set<string>();
    }
    const moveRange = Math.floor((selectedUnit.mobility || 1) / 2);
    const [r0, c0] = selectedUnit.pos;
    const gs = combatState?.grid_size ?? 7;
    const cells = new Set<string>();
    for (let dr = -moveRange; dr <= moveRange; dr++) {
      for (let dc = -moveRange; dc <= moveRange; dc++) {
        if (dr === 0 && dc === 0) continue;
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

  // AOE pattern preview: cells affected by target pattern when hovering a valid range cell
  const aoeHighlights = useMemo(() => {
    // Prefer dragCell during drag, hoverCell during normal hover
    const effectiveCell = dragCell ?? hoverCell;
    if (combatUIMode !== "TARGETING" || selectedCardIndex === null || !effectiveCell || !rangeOrigin) {
      return new Set<string>();
    }
    const [hr, hc] = effectiveCell;
    if (!rangeHighlights.has(`${hr},${hc}`)) {
      return new Set<string>();
    }
    const card = displayedHand[selectedCardIndex];
    if (!card) return new Set<string>();
    const gs = combatState?.grid_size ?? 7;
    const patternCells = resolveTargetPattern(card.target, effectiveCell, gs);
    // Filter by range from origin (mirrors backend engine.py range filter)
    const [r0, c0] = rangeOrigin.pos;
    const cells = new Set<string>();
    for (const [pr, pc] of patternCells) {
      if (card.range < 0) {
        cells.add(`${pr},${pc}`);
      } else {
        const dist = Math.max(Math.abs(pr - r0), Math.abs(pc - c0));
        if (dist <= card.range) {
          cells.add(`${pr},${pc}`);
        }
      }
    }
    return cells;
  }, [combatUIMode, selectedCardIndex, hoverCell, dragCell, rangeOrigin, rangeHighlights, displayedHand, combatState?.grid_size]);

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
            setCombatContext({ selectedCardIndex: null, selectedUnitId: null, uiMode: "VIEWING" });
          }
          return;
        }
        // AP check: personal AP + shared AP
        if (card && getCardAp(card) < card.cost) {
          const owner = combatState?.units.find(u => u.name === card.owner && u.team === "player");
          const pa = owner?.personal_ap ?? 0;
          const sa = combatState?.shared_ap ?? 0;
          setError(`AP 不足 (个人 ${pa} + 共享 ${sa} < ${card.cost})`);
          return;
        }

        if (cardPlayInProgressRef.current) return;
        cardPlayInProgressRef.current = true;
        const cardIdx = selectedCardIndex;
        setPlayingCardIndex(cardIdx);
        launchCardFlight(cardIdx, row, col);
        setCombatContext({ selectedCardIndex: null, selectedUnitId: null, uiMode: "VIEWING" });

        setLoading(true);
        const playStart = Date.now();
        try {
          const state = await doAction({
            action: "play_card",
            card_index: cardIdx,
            target: [row, col],
          });
          if (state) setCombatContext({ state });
          const elapsed = Date.now() - playStart;
          if (elapsed < 400) {
            await new Promise(r => setTimeout(r, 400 - elapsed));
          }
        } catch (e: any) {
          setError(e?.message || "操作失败");
        } finally {
          setLoading(false);
          setPlayingCardIndex(null);
          cardPlayInProgressRef.current = false;
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
            setCombatContext({ selectedUnitId: null });
          } else {
            setCombatContext({ selectedUnitId: unitAtCell.unit_id });
          }
          setCombatContext({ uiMode: "VIEWING", selectedCardIndex: null });
          setCursor([row, col]);
          return;
        }
        // Clicked a move-highlighted cell
        if (moveHighlights.has(`${row},${col}`)) {
          const totalAp = (selectedUnit?.personal_ap ?? 0) + (combatState?.shared_ap ?? 0);
          if (totalAp < 1) {
            const pa = selectedUnit?.personal_ap ?? 0;
            const sa = combatState?.shared_ap ?? 0;
            setError(`AP 不足，无法移动 (个人 ${pa} + 共享 ${sa} < 1)`);
            return;
          }
          setLoading(true);
          try {
            const state = await doAction({ action: "move", unit_id: selectedUnitId, target: [row, col] });
            // 移动后取消选中，避免残留的 selectedUnitId 导致下次移动仍指向旧角色
            if (state) setCombatContext({ state, selectedUnitId: null, uiMode: "VIEWING", selectedCardIndex: null });
            setCursor([row, col]);
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
        setCombatContext({ selectedUnitId: selectedUnitId === unit.unit_id ? null : unit.unit_id, uiMode: "VIEWING", selectedCardIndex: null });
        setCursor([row, col]);
        return;
      }

      // Clicked empty/invalid cell → deselect
      setCombatContext({ selectedUnitId: null, uiMode: "VIEWING", selectedCardIndex: null });
      setCursor([row, col]);
    },
    [effectiveId, combatTestId, sessionId, combatState, combatUIMode, selectedCardIndex, selectedUnitId, moveHighlights, rangeHighlights, displayedHand, api, fetchState, setCombatContext, launchCardFlight]
  );

  const handleCardClick = useCallback(
    (index: number) => {
      if (cardPlayInProgressRef.current) return;
      if (combatUIMode === "TARGETING" && selectedCardIndex === index) {
        setCombatContext({ selectedCardIndex: null, uiMode: "VIEWING", selectedUnitId: null });
        return;
      }
      setCombatContext({ selectedCardIndex: index, uiMode: "TARGETING" });
      const state = stateRef.current;
      if (state) {
        const card = state.shared_hand[index];
        if (card?.owner) {
          const ownerUnit = state.units.find(
            (u) => u.team === "player" && u.is_alive && u.name === card.owner
          );
          if (ownerUnit) {
            setCombatContext({ selectedUnitId: ownerUnit.unit_id });
          }
        }
      }
    },
    [combatUIMode, selectedCardIndex, setCombatContext]
  );

  const handleEndTurn = useCallback(async () => {
    if (!effectiveId) return;
    setLoading(true);
    try {
      const state = combatTestId
        ? await api.combatTestEndTurn(combatTestId)
        : await api.combatEndTurn(sessionId!);
      // 用响应里的最新 state 直接更新（弃牌/抽牌后手牌立即刷新）
      setCombatContext({ state: state ?? undefined, uiMode: "VIEWING", selectedCardIndex: null, selectedUnitId: null });
    } catch (e: any) {
      setError(e?.message || "结束回合失败");
    } finally {
      setLoading(false);
    }
  }, [effectiveId, combatTestId, sessionId, api, setCombatContext]);

  const handleCancel = useCallback(() => {
    setCombatContext({ uiMode: "VIEWING", selectedCardIndex: null, selectedUnitId: null });
    setCursor(null);
    setHoverCell(null);
  }, [setCombatContext]);

  const handleAbandon = useCallback(async () => {
    if (!sessionId || combatTestId) return;
    sseRef.current?.close();
    try {
      const resp = await api.combatAbandon(sessionId);
      if (resp.auto_narrate_action) {
        setPendingAutoNarrate({ action: resp.auto_narrate_action });
      }
    } catch {
      alert("放弃战斗失败，请重试");
      return;
    }
    setCombatContext(null);
    setCurrentView("chat");
  }, [sessionId, combatTestId, api, setCombatContext, setCurrentView, setPendingAutoNarrate]);

  const handleEscape = useCallback(async () => {
    if (!sessionId || combatTestId) return;
    setLoading(true);
    try {
      const state = await api.combatAction(sessionId, { action: "escape" });
      if (state) {
        setCombatContext({ state });
        if (state.battle_over && state.winner) {
          setResult(state.winner === "player" ? "胜利" : state.winner === "escaped" ? "撤退" : "失败");
        }
      }
    } catch (e: any) {
      setError(e?.message || "撤退失败");
    } finally {
      setLoading(false);
    }
  }, [sessionId, combatTestId, api, setCombatContext]);

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
        const resp = await api.combatComplete(sessionId, {
          encounter_id: encounterId,
          winner: combatState.winner || "unknown",
          survivors,
          rounds: combatState.round_num,
          character_stats: characterStats,
        });
        // 立即更新 session 状态，不等 15s 轮询
        setSessions(sessions.map(s => s.id === sessionId ? { ...s, in_combat: false, combat: null } : s));
        // 传递自动叙述指令和结算数据给 ChatPanel
        if (resp.auto_narrate_action) {
          setPendingAutoNarrate({
            action: resp.auto_narrate_action,
            settlement: {
              winner: combatState.winner || "unknown",
              survivors,
              rounds: combatState.round_num,
              encounter_id: encounterId,
            },
          });
        }
        // 有奖励则展示奖励面板，等用户确认后再切回 chat
        const r = resp.rewards;
        if (r && (r.xp > 0 || (r.items && r.items.length > 0) || (r.level_ups && r.level_ups.length > 0))) {
          setRewards(r);
          setShowRewards(true);
          writingBackRef.current = false;
          return;
        }
      } catch (e: any) {
        // 后端已无战斗状态（结果已保存过，或战斗已被清理）：写回无从谈起，
        // 不应把玩家卡在结算界面，直接返回对话
        if (e?.status === 404) {
          console.warn("combat/complete: 后端无进行中的战斗，跳过写回", e?.message);
          setSessions(sessions.map(s => s.id === sessionId ? { ...s, in_combat: false, combat: null } : s));
          writingBackRef.current = false;
          setCombatContext(null);
          setCurrentView("chat");
          return;
        }
        alert(`战斗结果保存失败：${e?.message || "未知错误"}，请重试`);
        writingBackRef.current = false;
        return; // Don't clear state or switch view on failure
      }
      writingBackRef.current = false;
    }

    setCombatContext(null);
    setCurrentView("chat");
  }, [combatTestId, sessionId, combatState, encounterId, api, setCombatContext, setCurrentView, setPendingAutoNarrate, setSessions, sessions]);

  const handleCardPick = useCallback(async (cardId: string) => {
    if (!sessionId) return;
    try {
      await api.combatCardPick(sessionId, cardId);
      setPickedCardId(cardId);
    } catch (e: any) {
      setError(e?.message || "选卡失败");
    }
  }, [sessionId, api]);

  const handleRewardsContinue = useCallback(() => {
    setShowRewards(false);
    setRewards(null);
    setPickedCardId(null);
    setCombatContext(null);
    setCurrentView("chat");
  }, [setCombatContext, setCurrentView]);

  const handleUseItem = useCallback(async (itemName: string) => {
    if (!selectedUnit || selectedUnit.team !== "player") {
      setError("请先选中要使用道具的干员");
      return;
    }
    if (!effectiveId) return;
    setLoading(true);
    try {
      const state = combatTestId
        ? await api.combatTestAction(combatTestId, { action: "use_item", item_name: itemName, unit_id: selectedUnit.unit_id })
        : await api.combatAction(sessionId!, { action: "use_item", item_name: itemName, unit_id: selectedUnit.unit_id });
      if (state) setCombatContext({ state });
    } catch (e: any) {
      setError(e?.message || "使用道具失败");
    } finally {
      setLoading(false);
    }
  }, [effectiveId, combatTestId, sessionId, selectedUnit, api, setCombatContext]);

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
      setCombatContext({ selectedUnitId: null, selectedCardIndex: null, uiMode: "VIEWING" });
      setCursor(null);
      setError(null);
    },
    [combatState, handleCellClick, setCombatContext],
  );

  const handleCardDragStart = useCallback((index: number) => {
    if (cardPlayInProgressRef.current) return;
    setDragCardIndex(index);
    setCombatContext({ selectedCardIndex: index, uiMode: "TARGETING" });
    const state = stateRef.current;
    if (state) {
      const card = state.shared_hand[index];
      if (card?.owner) {
        const ownerUnit = state.units.find(
          (u) => u.team === "player" && u.is_alive && u.name === card.owner
        );
        if (ownerUnit) {
          setCombatContext({ selectedUnitId: ownerUnit.unit_id });
        }
      }
    }
  }, [setCombatContext]);

  const handleCardDragEnd = useCallback(() => {
    setDragCardIndex(null);
    setDragCell(null);
    setCombatContext({ selectedCardIndex: null, selectedUnitId: null, uiMode: "VIEWING" });
  }, [setCombatContext]);

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
        setCombatContext({ selectedCardIndex: null, selectedUnitId: null, uiMode: "VIEWING" });
        return;
      }
      // AP check：个人 AP + 共享 AP（与点击路径及后端一致）
      if (card && getCardAp(card) < card.cost) {
        const owner = combatState.units.find(u => u.team === "player" && u.is_alive && u.name === card.owner);
        const pa = owner?.personal_ap ?? 0;
        const sa = combatState.shared_ap ?? 0;
        setError(`AP 不足 (个人 ${pa} + 共享 ${sa} < ${card.cost})`);
        setDragCardIndex(null);
        setDragCell(null);
        return;
      }

      if (cardPlayInProgressRef.current) return;
      cardPlayInProgressRef.current = true;
      const cardIdx = dragCardIndex;
      setPlayingCardIndex(cardIdx);
      launchCardFlight(cardIdx, row, col);
      setDragCardIndex(null);
      setDragCell(null);
      setCombatContext({ selectedCardIndex: null, selectedUnitId: null, uiMode: "VIEWING" });

      setLoading(true);
      const playStart = Date.now();
      try {
        const doAction = (action: { action: string; card_index?: number; target: [number, number] }) =>
          combatTestId
            ? api.combatTestAction(combatTestId, action)
            : api.combatAction(sessionId!, action);
        const state = await doAction({
          action: "play_card",
          card_index: cardIdx,
          target: [row, col],
        });
        if (state) setCombatContext({ state });
        const elapsed = Date.now() - playStart;
        if (elapsed < 400) {
          await new Promise(r => setTimeout(r, 400 - elapsed));
        }
      } catch (e: any) {
        setError(e?.message || "操作失败");
      } finally {
        setLoading(false);
        setPlayingCardIndex(null);
        cardPlayInProgressRef.current = false;
        setDragCardIndex(null);
        setDragCell(null);
      }
    },
    [effectiveId, combatTestId, sessionId, combatState, dragCardIndex, rangeHighlights, displayedHand, api, fetchState, getCardAp, setCombatContext, launchCardFlight]
  );

  const handleUnitClick = useCallback((unitId: string) => {
    if (selectedUnitId === unitId) {
      setCombatContext({ selectedUnitId: null, uiMode: "VIEWING", selectedCardIndex: null });
    } else {
      setCombatContext({ selectedUnitId: unitId, uiMode: "VIEWING", selectedCardIndex: null });
    }
  }, [selectedUnitId, setCombatContext]);

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

  // Track hovered cell for AOE preview in TARGETING mode
  const handleGridCellHover = useCallback((cell: [number, number] | null) => {
    setHoverCell(cell);
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!combatState || combatState.battle_over) return;
      if (cardPlayInProgressRef.current) return;
      if (e.key === "f" || e.key === "F") {
        handleEndTurn();
        return;
      }
      if (e.key === "Escape") {
        if (selectedUnitId) {
          setCombatContext({ selectedUnitId: null, uiMode: "VIEWING", selectedCardIndex: null });
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
  }, [combatState, selectedUnitId, handleEndTurn, handleCancel, handleCardClick, setCombatContext]);

  if (!combatState) {
    return (
      <div className="flex items-center justify-center h-full bg-combat-bg">
        <div className="bg-surface-card border border-combat-border rounded-xl p-6 w-96 shadow-2xl">
          <h2 className="text-lg font-bold text-gray-200 mb-4 font-display tracking-wide">
            {combatSessionId && loading ? "加载战斗中..." : "开始战斗"}
          </h2>

          {combatSessionId && loading && (
            <p className="text-sm text-gray-400 mb-3">正在加载已触发的战斗...</p>
          )}

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

          {approaches && approaches.length > 0 && (
            <div className="mb-3">
              <p className="text-xs text-gray-400 mb-1.5 font-display tracking-wider">选择打法</p>
              <div className="flex flex-col gap-1.5">
                {approaches.map((ap) => (
                  <button
                    key={ap.id}
                    className="text-left px-3 py-2 bg-surface-hover hover:bg-gray-700 rounded-lg border border-combat-border transition-colors"
                    onClick={() => handleSelectApproach(ap.id)}
                    disabled={loading}
                  >
                    <span className="text-sm text-gray-200 font-medium">{ap.label}</span>
                    <span className="block text-[10px] text-gray-500 mt-0.5">{ap.hint}</span>
                  </button>
                ))}
              </div>
              <button className="text-[10px] text-gray-500 hover:text-gray-300 mt-1.5" onClick={() => setApproaches(null)}>返回</button>
            </div>
          )}

          {checkResult && (
            <div className="mb-3 px-3 py-2 rounded-lg border border-amber-800/50 bg-amber-950/30">
              <p className="text-xs text-amber-200 font-display">
                🎲 {checkResult.attr}检定 — {checkResult.character} 掷出 d20 = {checkResult.d20} {checkResult.modifier >= 0 ? "+" : ""}{checkResult.modifier} = {checkResult.total} vs DC {checkResult.dc}
              </p>
              <p className={"text-xs font-bold mt-0.5 " + (checkResult.success ? "text-emerald-300" : "text-red-300")}>
                {checkResult.success ? "✅ 成功 — 避免战斗" : "❌ 失败 — 敌人警觉，被迫开战"}
              </p>
              <button className="text-[10px] text-gray-500 hover:text-gray-300 mt-1" onClick={() => setCheckResult(null)}>关闭</button>
            </div>
          )}

          {avoidMsg && (
            <div className="mb-3 px-3 py-2 rounded-lg border border-gray-700 bg-surface-hover">
              <p className="text-xs text-gray-300">已{avoidMsg} — 未进入战斗</p>
              <button className="text-[10px] text-gray-500 hover:text-gray-300 mt-1" onClick={() => setAvoidMsg(null)}>关闭</button>
            </div>
          )}

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
  const bgUrl = combatState.background_url ?? null;

  return (
    <div
      className="flex flex-col h-full bg-combat-bg relative"
      style={bgUrl ? {
        // 场景图之上叠压暗渐变：顶部托住回合文字、底部托住手牌区，中部尽量露出画面
        backgroundImage: [
          "linear-gradient(to bottom, rgba(10,14,23,0.72) 0%, rgba(10,14,23,0.30) 30%, rgba(10,14,23,0.28) 55%, rgba(10,14,23,0.80) 100%)",
          `url(${bgUrl})`,
        ].join(", "),
        backgroundSize: "cover",
        backgroundPosition: "center",
      } : undefined}
      onDragOver={(e) => e.preventDefault()}
    >
      {/* Main area: status panels + grid */}
      <div className="flex-1 flex items-start justify-between px-2 gap-2 relative z-10 select-none" onClick={handleGridBackgroundClick}>
        {/* Player status — left panel */}
        <div className="w-56 flex-shrink-0 max-h-[calc(100vh-320px)] overflow-y-auto bg-surface-card/90 border border-combat-border rounded-xl p-3 backdrop-blur-sm relative z-[1]" onClick={(e) => e.stopPropagation()}>
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

        {/* Character illustration — shown when a player unit is selected (fullscreen only) */}
        {isFullscreen && selectedUnit && selectedUnit.team === "player" && (
          <CharacterIllustration key={selectedUnit.name} characterName={selectedUnit.name} />
        )}

        {/* Grid area — positioned with relative+top to avoid layout conflicts with bottom bar */}
        <div className="flex flex-col items-center relative" style={{ top: `${cfg.gridMarginTop}px` }}>
          {/* Turn info + error toast (error uses absolute positioning to avoid pushing grid) */}
          <div className="relative mb-2 text-center" style={{ marginTop: isFullscreen ? '-28px' : undefined }}>
            <span className="text-sm text-gray-300 font-display tracking-wider">
              第 {combatState.round_num}{combatState.max_rounds > 0 ? " / " + combatState.max_rounds : ""} 回合
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
          <div className="relative" ref={(el) => { relativeRef.current = el; setContainerEl(el); }} style={{ "--cell-size": `${cfg.cellSize}px` } as React.CSSProperties}
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
              aoeHighlights={aoeHighlights}
              selectedUnitId={selectedUnitId}
              uiMode={combatUIMode}
              cursor={cursor}
              dragCell={dragCell}
              onCellClick={handleCellClick}
              onCellHover={handleCellHover}
              onCellLeave={handleHoverLeave}
              onCellHoverCell={handleGridCellHover}
              onCellDrop={handleGridDrop}
              onGridDragMove={handleGridDragMove}
              onGridMount={(el) => { gridRef.current = el; setGridEl(el); }}
            />
            <PixiCombatScene
              ref={pixiRef}
              units={combatState.units}
              gridEl={gridEl}
              containerEl={containerEl}
              resizeTick={resizeTick}
              cellSize={cfg.cellSize}
            />

            {/* Damage numbers */}
            {damageNumbers.map((d) => {
              const center = (() => {
                const grid = gridRef.current;
                const rel = relativeRef.current;
                if (!grid || !rel) return null;
                const sp = getCellCenter(grid, d.pos[0], d.pos[1]);
                if (!sp) return null;
                const relRect = rel.getBoundingClientRect();
                return { x: sp.x - relRect.left, y: sp.y - relRect.top };
              })();
              return (
                <span
                  key={d.id}
                  className={`damage-number ${d.type === "heal" ? "heal" : d.type === "arts" ? "arts" : d.type === "miss" ? "miss" : "physical"}`}
                  style={{
                    position: "absolute",
                    left: center ? `${center.x - 14}px` : `${cfg.cellSize + d.pos[1] * (cfg.cellSize + 2)}px`,
                    top: center ? `${center.y - 14}px` : `${d.pos[0] * (cfg.cellSize + 2)}px`,
                    zIndex: 100,
                    pointerEvents: "none",
                  }}
                >
                  {d.type === "miss" ? "闪避" : d.type === "heal" ? `+${d.value}` : `-${d.value}`}
                </span>
              );
            })}

            {/* Enemy intent badges（敌人意图头顶图标）— 仅玩家回合展示 */}
            {combatState.phase === "PLAYER_TURN" && combatState.enemy_intents && Object.entries(combatState.enemy_intents).map(([uid, it]: [string, any]) => {
              const enemy = combatState.units.find((u) => u.unit_id === uid && u.team === "enemy" && u.is_alive);
              if (!enemy) return null;
              const badge = INTENT_BADGE[it.type] || INTENT_BADGE.attack;
              const center = (() => {
                const grid = gridRef.current;
                const rel = relativeRef.current;
                if (!grid || !rel) return null;
                const sp = getCellCenter(grid, enemy.pos[0], enemy.pos[1]);
                if (!sp) return null;
                const relRect = rel.getBoundingClientRect();
                return { x: sp.x - relRect.left, y: sp.y - relRect.top };
              })();
              if (!center) return null;
              return (
                <span
                  key={uid}
                  className={"absolute -translate-x-1/2 px-1.5 py-0.5 rounded-full text-[10px] font-display border whitespace-nowrap " + badge.cls}
                  style={{ left: center.x, top: center.y - cfg.cellSize * 0.85, zIndex: 90, pointerEvents: "none" }}
                >
                  {badge.icon} {it.label}
                </span>
              );
            })}

            {/* Particle effects */}
            <CombatParticles
              emitters={particleEmitters}
              onEmitterDone={removeEmitter}
            />

            {/* Attack arrow during card drag */}
            {arrowFrom && dragCell && relativeRef.current && (() => {
              const m = dragMouseRef.current;
              const rel = relativeRef.current!;
              const pr = rel.getBoundingClientRect();
              const grid = gridRef.current;
              const fromPos = (() => {
                if (!grid) return null;
                const sp = getCellCenter(grid, arrowFrom[0], arrowFrom[1]);
                return sp ? { x: sp.x - pr.left, y: sp.y - pr.top } : null;
              })();
              const toPos = (() => {
                if (!grid) return null;
                const sp = getCellCenter(grid, dragCell[0], dragCell[1]);
                return sp ? { x: sp.x - pr.left, y: sp.y - pr.top } : null;
              })();
              const toPoint = m ? { x: m.clientX - pr.left, y: m.clientY - pr.top } : null;
              if (!fromPos) return null;
              return (
                <AttackArrow
                  fromPos={fromPos}
                  toPos={toPos}
                  toPoint={toPoint}
                  containerWidth={rel.clientWidth}
                  containerHeight={rel.clientHeight}
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
            intents={combatState.enemy_intents}
            onUnitClick={handleUnitClick}
            onUnitHover={handleUnitHover}
            onUnitLeave={handleHoverLeave}
          />
        </div>
      </div>

      {/* Bottom: hand + controls + event log */}
      <div className="border-t border-combat-divider bg-surface-dark/80 pointer-events-none relative" style={{ marginTop: cfg.bottomBarMarginTop }}>
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
          {combatState.inventory && combatState.inventory.length > 0 && (
            <div className="flex items-center gap-1">
              {combatState.inventory.map((item) => (
                <button
                  key={item.name}
                  className="px-2 py-1 text-xs bg-emerald-900/60 hover:bg-emerald-800/60 text-emerald-200 rounded-lg border border-emerald-800/50 font-display tracking-wider disabled:opacity-30"
                  onClick={() => handleUseItem(item.name)}
                  disabled={combatState.phase !== "PLAYER_TURN" || combatState.battle_over || loading}
                  title={`使用 ${item.name}（恢复生命）`}
                >
                  {item.name} × {item.count}
                </button>
              ))}
            </div>
          )}
          <div className="flex-1" />
          <button
            className="px-3 py-1.5 text-xs bg-surface-hover hover:bg-gray-700 text-gray-300 rounded-lg transition-all border border-combat-border font-display tracking-wider"
            onClick={() => {
              const m = !muted;
              setMuted(m);
              audioManager.setMuted(m);
            }}
            title={muted ? "取消静音" : "静音"}
          >
            {muted ? "🔇" : "🔊"}
          </button>
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
          {combatState.escape_enabled && !combatState.battle_over && !combatTestId && (
            <button
              className="px-4 py-1.5 text-xs bg-orange-900/50 hover:bg-orange-800/50 text-orange-200 rounded-lg transition-all disabled:opacity-30 border border-orange-800/50 font-display tracking-wider"
              onClick={handleEscape}
              disabled={combatState.phase !== "PLAYER_TURN" || loading}
              title="撤退（放弃本场战斗与奖励，剧情继续推进）"
            >
              撤退
            </button>
          )}
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
          {!combatState.battle_over && !combatTestId && (
            <button
              className="px-4 py-1.5 text-xs bg-red-900/40 hover:bg-red-800/50 text-red-300 rounded-lg transition-all border border-red-800/30"
              onClick={handleAbandon}
            >
              放弃战斗
            </button>
          )}
        </div>

        {/* Hand */}
        <CombatHand
          cards={displayedHand}
          getCardAp={getCardAp}
          selectedIndex={selectedCardIndex}
          disabled={combatState.phase !== "PLAYER_TURN"}
          highlightOwner={highlightOwner}
          ownerSkins={ownerSkins}
          onCardClick={handleCardClick}
          onCardDragStart={handleCardDragStart}
          onCardDragEnd={handleCardDragEnd}
          playingIndex={playingCardIndex}
          cardWidth={cfg.cardWidth}
          cardHeight={cfg.cardHeight}
          fanMarginTop={cfg.handFanMarginTop}
          compact={!isFullscreen}
        />

        {/* Event log */}
        <div className="px-3 pb-3 pointer-events-auto">
          <CombatEventLog events={events} />
        </div>
      </div>

      {/* 任务状态栏（会话战斗 · 剧情任务） */}
      <CombatQuestBar sessionId={combatTestId ? null : sessionId} />

      {/* 出牌飞行动画 */}
      <CardFlyOverlay flight={cardFlight} onDone={clearCardFlight} />

      {/* Battle end overlay */}
      {combatState.battle_over && result && (
        <div className="combat-overlay-enter absolute inset-0 flex items-center justify-center bg-black/70 z-40">
          <div className="bg-surface-card border border-combat-border rounded-2xl p-10 text-center shadow-2xl">
            {showRewards && rewards ? (
              <>
                <div className="text-3xl font-black mb-4 font-display tracking-widest text-combat-gold">
                  战利品结算
                </div>
                <div className="text-gray-200 text-sm mb-3 font-display">
                  获得 {rewards.xp} 点经验
                </div>
                {rewards.items && rewards.items.length > 0 && (
                  <div className="text-gray-300 text-sm mb-3 font-display">
                    掉落物品：{rewards.items.join("、")}
                  </div>
                )}
                {rewards.level_ups && rewards.level_ups.length > 0 && (
                  <div className="text-amber-300 text-sm mb-4 font-display">
                    {rewards.level_ups.map((lu, i) => (
                      <div key={i}>{lu.name} 升至 Lv.{lu.level}，{lu.attribute} +1</div>
                    ))}
                  </div>
                )}
                {rewards.card_choices && rewards.card_choices.length > 0 && (
                  <div className="mb-4">
                    <div className="text-gray-400 text-xs mb-2 font-display tracking-wider">
                      选择一张卡加入卡组（下场战斗可用）
                    </div>
                    <div className="flex gap-2">
                      {rewards.card_choices.map((c) => (
                        <button
                          key={c.card_id}
                          className={"flex-1 text-left px-3 py-2 rounded-lg border transition-all " + (
                            pickedCardId === c.card_id
                              ? "border-cyan-400 bg-cyan-900/40 text-cyan-100"
                              : pickedCardId
                              ? "border-gray-700 bg-gray-900/40 text-gray-500 opacity-60"
                              : "border-gray-700 bg-gray-900/60 hover:bg-gray-800 text-gray-200"
                          )}
                          onClick={() => handleCardPick(c.card_id)}
                          disabled={!!pickedCardId}
                        >
                          <div className="text-xs font-bold">{c.name}</div>
                          <div className="text-[10px] text-gray-500 mt-0.5">{c.description}</div>
                          <div className="text-[9px] text-gray-600 mt-1">费用 {c.cost} · {c.class_required}</div>
                        </button>
                      ))}
                    </div>
                    {pickedCardId && (
                      <div className="text-emerald-300 text-xs mt-2">✅ 已加入卡组（下场战斗可用）</div>
                    )}
                  </div>
                )}
                <button
                  className="px-8 py-2.5 bg-cyan-900/70 hover:bg-cyan-800/70 text-cyan-200 rounded-lg transition-all border border-cyan-800/50 font-display tracking-wider"
                  onClick={handleRewardsContinue}
                >
                  继续
                </button>
              </>
            ) : (
              <>
                <div className={`text-5xl font-black mb-4 font-display tracking-widest ${
                  result === "胜利" ? "text-combat-gold" : "text-combat-enemy"
                }`}>
                  {result === "胜利" ? "VICTORY" : result === "撤退" ? "RETREAT" : "DEFEAT"}
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
              </>
            )}
          </div>
        </div>
      )}

      {/* Deck/discard pile buttons — absolute relative to bottom container */}
      {combatState && combatState.phase === "PLAYER_TURN" && !combatState.battle_over && (
        <>
          <button
            className="absolute left-4 bottom-full mb-2 z-30 flex items-center gap-2 px-3 py-2 bg-surface-card/90 hover:bg-surface-card border border-combat-border rounded-xl shadow-lg transition-all backdrop-blur-sm pointer-events-auto"
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
            className="absolute right-4 bottom-full mb-2 z-30 flex items-center gap-2 px-3 py-2 bg-surface-card/90 hover:bg-surface-card border border-combat-border rounded-xl shadow-lg transition-all backdrop-blur-sm pointer-events-auto"
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
