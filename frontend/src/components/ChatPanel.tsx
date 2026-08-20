import { useState, useRef, useEffect, useCallback } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi, createSSE } from "../hooks/useApi";
import { parseDialogue, normalizeSegments } from "../utils/dialogueParser";
import type { ChatMessage } from "../types";
import DialogueBubble from "./chat/DialogueBubble";
import NarrationText from "./chat/NarrationText";
import LoadingIndicator from "./chat/LoadingIndicator";
import TokenUsage from "./chat/TokenUsage";

const EMPTY_MSGS: ChatMessage[] = [];

function filterSceneLog(log: string[]): string[] {
  return log.filter(
    (entry) =>
      !entry.includes("博士加入了场景") &&
      !entry.includes("博士切换")
  );
}

export default function ChatPanel() {
  const { activeSessionId, chatMode, sessions, setSessions, triggerEnvRefresh, triggerMemoryRefresh, chatRefreshKey, characterRefreshKey, editBeforeSend, sceneSwitchKey, dialogueBubbleMode, currentView, setCurrentView, setCombatContext, pendingAutoNarrate, setPendingAutoNarrate, pendingBriefing, setPendingBriefing, resourcePanelOpen, setResourcePanelOpen, chatFontSize, setChatFontSize } = useAppStore();
  const activeMode = sessions.find((s) => s.id === activeSessionId)?.mode || "free";

  const sceneCharacters: string[] = (() => {
    const session = sessions.find((s) => s.id === activeSessionId);
    if (!session) return [];
    const chars = (session.characters || []).map((c: any) =>
      typeof c === "string" ? c : c.name || c.id || ""
    );
    // 玩家身份也参与说话人推断，避免玩家台词被误判给场景角色
    const player = session.player_identity || "博士";
    if (player && !chars.includes(player)) chars.push(player);
    return chars;
  })();

  const [characterColors, setCharacterColors] = useState<Record<string, string>>({});
  const [customPromptOpen, setCustomPromptOpen] = useState(false);
  const [customPromptDraft, setCustomPromptDraft] = useState("");
  const [customPromptSaving, setCustomPromptSaving] = useState(false);
  const customPromptInitSession = useRef<string | null>(null);

  const api = useApi();

  // Fetch character colors from backend whenever session/scene changes
  useEffect(() => {
    if (!activeSessionId) {
      setCharacterColors({});
      return;
    }
    let cancelled = false;
    api.getSceneCharacters(activeSessionId).then((data: any) => {
      if (!cancelled && data.character_colors) {
        setCharacterColors(data.character_colors);
      }
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [activeSessionId, characterRefreshKey, chatRefreshKey, api]);

  // Sync custom prompt draft only when modal opens or active session changes.
  // 不依赖 sessions 轮询更新，避免用户输入过程中被外部刷新覆盖。
  useEffect(() => {
    if (!customPromptOpen) {
      customPromptInitSession.current = null;
      return;
    }
    if (customPromptInitSession.current === activeSessionId) return;
    const session = sessions.find(s => s.id === activeSessionId);
    setCustomPromptDraft(session?.custom_prompt || "");
    customPromptInitSession.current = activeSessionId ?? null;
  }, [customPromptOpen, activeSessionId, sessions]);

  const messages = useAppStore(s => s.sessionMessages[activeSessionId || ""] ?? EMPTY_MSGS);
  const streaming = useAppStore(s => s.sessionStreaming[activeSessionId || ""] ?? false);
  const sending = useAppStore(s => s.sessionSending[activeSessionId || ""] ?? false);
  const narrationCount = useAppStore(s => s.sessionNarrationCount[activeSessionId || ""] ?? 0);
  const [input, setInput] = useState("");
  // 战前简报：d20 检定结果 + 谈判失败后暂存的战斗状态
  const [briefingCheck, setBriefingCheck] = useState<{ d20: number; modifier: number; total: number; dc: number; success: boolean; attr: string; character: string } | null>(null);
  const [briefingCombatState, setBriefingCombatState] = useState<any | null>(null);
  const [initialLoading, setInitialLoading] = useState(false);
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [regeneratingRound, setRegeneratingRound] = useState<number | null>(null);
  const [regenerationPrompt, setRegenerationPrompt] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const waitStartRef = useRef<number>(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  // Wait time counter: tick every second while sending or streaming
  useEffect(() => {
    if (sending || streaming) {
      if (!waitStartRef.current) waitStartRef.current = Date.now();
      setElapsedSeconds(0);
      const timer = setInterval(() => {
        setElapsedSeconds(
          Math.round((Date.now() - waitStartRef.current) / 1000)
        );
      }, 250);
      return () => clearInterval(timer);
    } else {
      waitStartRef.current = 0;
      setElapsedSeconds(0);
    }
  }, [sending, streaming]);

  // ── Session load / restore ──

  useEffect(() => {
    setEditingIdx(null);

    if (!activeSessionId) return;
    const sid: string = activeSessionId;
    const store = useAppStore.getState();

    // If store already has messages for this session (from background SSE), skip loading
    const existing = store.sessionMessages[sid];
    if (existing && existing.length > 0) return;

    const key = `ark_chat_${activeMode}_${sid}`;
    let cancelled = false;

    async function init() {
      // 1. Try localStorage
      const cached = localStorage.getItem(key);
      if (cached) {
        try {
          const parsed = JSON.parse(cached);
          if (Array.isArray(parsed) && parsed.length > 0) {
            if (!cancelled) {
              useAppStore.getState().setSessionMessages(sid, parsed);
              setInitialLoading(false);
              // Restore narrationCount from max round
              const maxRound = Math.max(0, ...parsed
                .filter((m: ChatMessage) => m.round != null)
                .map((m: ChatMessage) => m.round!));
              useAppStore.getState().setSessionNarrationCount(sid, maxRound);
            }
            return;
          }
        } catch { /* corrupt */ }
      }

      // 2. Backend fallback
      setInitialLoading(true);
      try {
        const session = await api.getSession(sid);
        if (cancelled) return;
        useAppStore.getState().setSessionNarrationCount(sid, session.narration_count || 0);

        const initialMessages: ChatMessage[] = [];
        const log = filterSceneLog(session.scene_log || []);
        if (log.length > 0) {
          initialMessages.push({ role: "system", content: `【场景记录】\n${log.join("\n")}` });
        }
        if (session.environment) {
          const { location, weather, time } = session.environment;
          initialMessages.push({
            role: "system",
            content: `【环境】${location || "未知地点"} · ${weather || "未知天气"} · ${time || "未知时间"}`,
          });
        }
        const chars = session.characters || [];
        if (chars.length > 0) {
          const charList = chars
            .map((c: any) => typeof c === "string" ? c : c.name || c.id)
            .join("、");
          initialMessages.push({ role: "system", content: `【已加载角色】${charList}` });
        }
        if (!cancelled) useAppStore.getState().setSessionMessages(sid, initialMessages);
      } catch {
        // Fresh session
      } finally {
        if (!cancelled) setInitialLoading(false);
      }

      // 3. Story mode auto-narrate
      if (chatMode === "story" && !cancelled) {
        triggerNarrate(sid);
      }
    }

    init();
    return () => { cancelled = true; };
  }, [activeSessionId, chatMode, api]);

  // ── Persist (subscribe to store, persists on every change including mid-stream) ──

  useEffect(() => {
    if (!activeSessionId) return;
    const sid = activeSessionId;
    const session = sessions.find(s => s.id === sid);
    if (!session) return;
    const key = `ark_chat_${session.mode}_${sid}`;

    let prevMsgs: ChatMessage[] | undefined;
    const unsub = useAppStore.subscribe((state) => {
      const msgs = state.sessionMessages[sid];
      if (msgs !== prevMsgs && msgs && msgs.length > 0) {
        prevMsgs = msgs;
        try { localStorage.setItem(key, JSON.stringify(msgs)); } catch {}
      }
    });
    return unsub;
  }, [activeSessionId, sessions]);

  // ── External rollback (from MemoryPanel) ──

  useEffect(() => {
    if (!activeSessionId || chatRefreshKey === 0) return;
    (async () => {
      try {
        const session = await api.getSession(activeSessionId);
        const targetRound = session.narration_count || 0;
        useAppStore.getState().setSessionNarrationCount(activeSessionId, targetRound);
        useAppStore.getState().setSessionMessages(activeSessionId, (prev) =>
          prev.filter((m) => !m.round || m.round <= targetRound)
        );
      } catch { /* ignore */ }
    })();
  }, [chatRefreshKey]);

  // ── Scene switch narration (story mode) ──

  useEffect(() => {
    if (!activeSessionId || chatMode !== "story" || sceneSwitchKey === 0) return;
    triggerNarrate(activeSessionId);
  }, [sceneSwitchKey]);

  // ── Rollback ──

  const handleRollback = useCallback(async (targetRound: number) => {
    if (!activeSessionId) return;
    if (!confirm(`回退到第 ${targetRound} 轮？\n之后的对话记录和回忆将被删除。`)) return;

    try {
      await api.rollbackSession(activeSessionId, targetRound);
      useAppStore.getState().setSessionMessages(activeSessionId, (prev) =>
        prev.filter((m) => !m.round || m.round <= targetRound)
      );
      useAppStore.getState().setSessionNarrationCount(activeSessionId, targetRound);
      triggerMemoryRefresh();
    } catch (err: any) {
      alert("回退失败: " + (err.message || "未知错误"));
    }
  }, [activeSessionId, api, triggerMemoryRefresh]);

  // ── Edit user message ──

  const startEdit = useCallback((idx: number, text: string) => {
    setEditingIdx(idx);
    setEditText(text);
  }, []);

  const cancelEdit = useCallback(() => {
    setEditingIdx(null);
    setEditText("");
  }, []);

  const commitEdit = useCallback(async () => {
    if (editingIdx == null || !activeSessionId) return;
    const targetMsg = messages[editingIdx];
    const targetRound = targetMsg?.round;
    const edited = editText.trim();
    if (!edited) {
      cancelEdit();
      return;
    }

    const rollbackTo = targetRound ? targetRound - 1 : 0;
    try {
      if (rollbackTo >= 0) {
        await api.rollbackSession(activeSessionId, rollbackTo);
        useAppStore.getState().setSessionNarrationCount(activeSessionId, rollbackTo);
        triggerMemoryRefresh();
      }

      useAppStore.getState().setSessionMessages(activeSessionId, (prev) => {
        const keep = prev.slice(0, editingIdx);
        return [...keep, { role: "user", content: edited, round: rollbackTo + 1 }];
      });

      setEditingIdx(null);
      setEditText("");

      triggerNarrate(activeSessionId, edited);
    } catch (err: any) {
      alert("编辑失败: " + (err.message || "未知错误"));
      useAppStore.getState().setSessionStreaming(activeSessionId, false);
    }
  }, [editingIdx, editText, activeSessionId, messages, api, triggerMemoryRefresh, cancelEdit]);

  // ── Send ──

  const performSend = useCallback(
    async (text: string) => {
      if (!activeSessionId) return;
      const sid = activeSessionId;

      // Story mode: use SSE streaming for progressive token display
      if (chatMode === "story") {
        triggerNarrate(sid, text);
        return;
      }

      // Free mode: blocking POST (group chat)
      useAppStore.getState().setSessionStreaming(sid, true);
      try {
        const res = await api.groupChat(sid, text);
        const items: any[] = res.responses || res;
        const responses: ChatMessage[] = items.map((r: any) => ({
          role: "character",
          content: r.response,
          character: r.character,
          usage: r.usage,
        }));
        useAppStore.getState().setSessionMessages(sid, (prev) => {
          if (responses.length === 0) {
            return [...prev, { role: "system", content: "（没有角色回复 — 请先在右侧面板加载角色）" }];
          }
          return [...prev, ...responses];
        });
      } catch (err: any) {
        useAppStore.getState().setSessionMessages(sid, (prev) => [...prev, { role: "system", content: `请求失败: ${err.message}` }]);
      } finally {
        useAppStore.getState().setSessionSending(sid, false);
        useAppStore.getState().setSessionStreaming(sid, false);
      }
    },
    [activeSessionId, chatMode, api, triggerEnvRefresh, triggerMemoryRefresh]
  );

  // 战前简报：新简报到来时清空上一轮的检定/暂存状态
  useEffect(() => {
    if (pendingBriefing) {
      setBriefingCheck(null);
      setBriefingCombatState(null);
    }
  }, [pendingBriefing]);

  // 战前简报：选择打法
  const handleBriefingApproach = useCallback(async (approachId: string) => {
    if (!pendingBriefing || !activeSessionId) return;
    const b = pendingBriefing;
    try {
      const resp = await api.combatStart(b.session_id, b.encounter_id, [], approachId);
      if (resp?.state) {
        if (resp.check) {
          // 谈判失败：先展示检定，玩家确认后进入战斗
          setBriefingCheck(resp.check);
          setBriefingCombatState(resp.state);
        } else {
          setCombatContext({ sessionId: b.session_id, state: resp.state });
          setPendingBriefing(null);
          setCurrentView("combat");
        }
      } else if (resp?.kind === "check") {
        setBriefingCheck(resp.check ?? null);
      } else if (resp?.kind === "avoid") {
        setPendingBriefing(null);
        setPendingAutoNarrate({ action: `战斗已避免（${resp.label}），描述当前场景与去向` });
      }
    } catch (err: any) {
      alert("启动战斗失败: " + (err.message || "未知错误"));
    }
  }, [pendingBriefing, activeSessionId, api, setCombatContext, setPendingBriefing, setCurrentView, setPendingAutoNarrate]);

  // Auto-narrate after combat: watch for pendingAutoNarrate being set
  useEffect(() => {
    if (pendingAutoNarrate && activeSessionId) {
      const { action, settlement } = pendingAutoNarrate;
      setPendingAutoNarrate(null);
      if (settlement) {
        const winnerText = settlement.winner === "player" ? "玩家获胜" : settlement.winner === "enemy" ? "敌方获胜" : "战斗结束";
        const survivorsText = settlement.survivors.length > 0 ? `\n幸存：${settlement.survivors.join("、")}` : "";
        const settlementMsg: ChatMessage = {
          role: "system",
          content: `⚔ 战斗结束：遭遇战「${settlement.encounter_id}」— ${winnerText}，共 ${settlement.rounds} 回合。${survivorsText}`,
        };
        useAppStore.getState().setSessionMessages(activeSessionId, prev => [...prev, settlementMsg]);
      }
      performSend(action);
    }
  }, [pendingAutoNarrate, activeSessionId, performSend, setPendingAutoNarrate]);

  // Reconnect SSE when switching back to chat view after combat
  useEffect(() => {
    if (currentView === "chat" && activeSessionId) {
      // ChatPanel is always mounted; when coming back from combat,
      // ensure SSE connection state is fresh by triggering a refresh
    }
  }, [currentView, activeSessionId]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || sending || streaming || !activeSessionId) return;

    const sid = activeSessionId;
    const curRound = useAppStore.getState().sessionNarrationCount[sid] || 0;
    setInput("");
    useAppStore.getState().setSessionSending(sid, true);
    useAppStore.getState().setSessionMessages(sid, (prev) => [...prev, { role: "user", content: text, round: curRound }]);
    performSend(text);
  }, [input, sending, streaming, activeSessionId, performSend]);

  const handleChoiceClick = useCallback(
    (choice: string) => {
      if (editBeforeSend) {
        setInput(choice);
        return;
      }
      if (!activeSessionId) return;
      const sid = activeSessionId;
      const curRound = useAppStore.getState().sessionNarrationCount[sid] || 0;
      setInput("");
      useAppStore.getState().setSessionMessages(sid, (prev) => [...prev, { role: "user", content: choice, round: curRound }]);
      performSend(choice);
    },
    [activeSessionId, performSend, editBeforeSend]
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // ── Variant switching & regeneration ──

  const syncVariantToBackend = useCallback((round: number | undefined, narrative: string) => {
    if (!activeSessionId || round == null) return;
    api.narrateUpdate(activeSessionId, round, narrative).catch(() => {});
  }, [activeSessionId, api]);

  const handleVariantPrev = useCallback((idx: number) => {
    if (!activeSessionId) return;
    const sid = activeSessionId;
    useAppStore.getState().setSessionMessages(sid, (prev) => {
      const msg = prev[idx];
      if (!msg.variants || (msg.variantIndex ?? 0) <= 0) return prev;
      const newIdx = (msg.variantIndex ?? 0) - 1;
      const narrative = msg.variants[newIdx];
      const updated = { ...msg, content: narrative, variantIndex: newIdx, dialogueSegments: undefined };
      syncVariantToBackend(msg.round, narrative);
      return [...prev.slice(0, idx), updated, ...prev.slice(idx + 1)];
    });
  }, [activeSessionId, syncVariantToBackend]);

  const handleVariantNext = useCallback((idx: number) => {
    if (!activeSessionId) return;
    const sid = activeSessionId;
    useAppStore.getState().setSessionMessages(sid, (prev) => {
      const msg = prev[idx];
      if (!msg.variants) return prev;
      const curIdx = msg.variantIndex ?? 0;
      if (curIdx < msg.variants.length - 1) {
        const newIdx = curIdx + 1;
        const narrative = msg.variants[newIdx];
        const updated = { ...msg, content: narrative, variantIndex: newIdx, dialogueSegments: undefined };
        syncVariantToBackend(msg.round, narrative);
        return [...prev.slice(0, idx), updated, ...prev.slice(idx + 1)];
      }
      return prev;
    });
  }, [activeSessionId, syncVariantToBackend]);

  const handleRegeneratePrompt = useCallback((round: number) => {
    setRegeneratingRound(round);
    setRegenerationPrompt("");
  }, []);

  const handleRegenerateCancel = useCallback(() => {
    setRegeneratingRound(null);
    setRegenerationPrompt("");
  }, []);

  const handleRegenerateSubmit = useCallback(async () => {
    if (!activeSessionId || regeneratingRound == null) return;
    const sid = activeSessionId;
    const round = regeneratingRound;
    const prompt = regenerationPrompt.trim();
    setRegenerationPrompt("");
    setRegeneratingRound(null);
    useAppStore.getState().setSessionStreaming(sid, true);
    try {
      const data = await api.narrateVariant(sid, prompt);
      const newNarrative: string = data.narrative;
      useAppStore.getState().setSessionMessages(sid, (prev) => {
        const idx = prev.findIndex(
          (m) => m.role === "narrator" && m.round === round
        );
        if (idx === -1) return prev;
        const msg = prev[idx];
        const variants = msg.variants || [msg.content];
        const newIdx = variants.length;
        const updated: ChatMessage = {
          ...msg,
          content: newNarrative,
          variants: [...variants, newNarrative],
          variantIndex: newIdx,
          dialogueSegments: data.dialogue_segments || msg.dialogueSegments,
          usage: data.usage || msg.usage,
        };
        api.narrateUpdate(sid, round, newNarrative).catch(() => {});
        return [...prev.slice(0, idx), updated, ...prev.slice(idx + 1)];
      });
    } catch (err: any) {
      alert("重新生成失败: " + (err.message || "未知错误"));
    } finally {
      useAppStore.getState().setSessionStreaming(sid, false);
    }
  }, [activeSessionId, regeneratingRound, regenerationPrompt, api]);

  // ── Single message deletion ──

  const handleDeleteMessage = useCallback((idx: number) => {
    if (!activeSessionId) return;
    const sid = activeSessionId;
    useAppStore.getState().setSessionMessages(sid, (prev) => {
      if (idx < 0 || idx >= prev.length) return prev;
      return [...prev.slice(0, idx), ...prev.slice(idx + 1)];
    });
  }, [activeSessionId]);

  // ── Derive round groups for rollback dividers ──

  const roundBoundaries: number[] = [];
  let lastRound: number | undefined;
  messages.forEach((m, i) => {
    if (m.round != null && m.round !== lastRound) {
      if (lastRound != null) roundBoundaries.push(i);
      lastRound = m.round;
    }
  });

  const showEmptyState = messages.length === 0 && !initialLoading;

  const isWaitingForLLM =
    (sending || streaming) &&
    !(streaming && messages.length > 0 && messages[messages.length - 1].role === "narrator");

  // ── Render ──

  function renderMessageContent(msg: ChatMessage): React.ReactNode {
    if (!dialogueBubbleMode) {
      return <div className="whitespace-pre-wrap">{msg.content}</div>;
    }

    const applyBubbles = msg.role === "character" || msg.role === "narrator";
    if (!applyBubbles || !msg.content) {
      return <div className="whitespace-pre-wrap">{msg.content || ""}</div>;
    }

    // Prefer backend-provided segments, fall back to frontend parser
    let segments = msg.dialogueSegments;
    if (!segments || segments.length === 0) {
      segments = parseDialogue(msg.content, msg.character, sceneCharacters);
    }
    // 容错规范化：过滤空段、dialogue 缺 speaker 继承上下文、未知 type 降级叙述
    segments = normalizeSegments(segments);
    const hasDialogue = segments.some((s) => s.type === "dialogue");
    if (!hasDialogue) {
      return <div className="whitespace-pre-wrap">{msg.content}</div>;
    }

    return (
      <div>
        {segments.map((seg, si) => {
          if (seg.type === "narration" || !seg.speaker) {
            return <NarrationText key={si} text={seg.text} />;
          }
          return (
            <DialogueBubble
              key={si}
              text={seg.text}
              speaker={seg.speaker}
              color={characterColors[seg.speaker]}
              sessionId={activeSessionId ?? undefined}
            />
          );
        })}
      </div>
    );
  }

  const activeSession = sessions.find((s) => s.id === activeSessionId);
  const sessionTokens = activeSession?.total_usage;

  return (
    <div className="flex flex-col h-full">
      {/* Header bar — 会话信息 + token 统计 */}
      {activeSession && (
        <div className="flex items-center justify-between px-4 py-1.5 border-b border-gray-700/50 bg-gray-850/30 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-xs text-gray-400 truncate">{activeSession.name}</span>
            <span className="text-[10px] text-gray-600">第{activeSession.narration_count ?? narrationCount}轮</span>
            {activeSession.in_combat && (
              <span className="text-[10px] text-orange-400 font-medium animate-pulse">⚔ 战斗中</span>
            )}
            {chatMode === "story" && activeSession.combat_mode === "tactical" && (
              <span className="text-[10px] text-orange-400/70 font-medium">⚔ 战术</span>
            )}
            {chatMode === "story" && activeSession.combat_mode === "tactical" && !activeSession.in_combat && (
              <button
                onClick={async () => {
                  const encounterId = prompt("输入遭遇 ID（可选）\n可用：初遇整合运动, enc_defense, enc_elite_hunt, enc_mixed_assault, enc_training") || "初遇整合运动";
                  try {
                    await api.combatStart(activeSession.id!, encounterId, []);
                    setCombatContext({ sessionId: activeSession.id! });
                    setCurrentView("combat");
                  } catch (err: any) {
                    alert("启动战斗失败: " + (err.message || "未知错误"));
                  }
                }}
                className="text-[10px] px-1.5 py-0.5 rounded bg-orange-700/30 text-orange-300 hover:bg-orange-700/50 transition-colors"
                title="手动触发战斗"
              >
                ⚔
              </button>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setCurrentView("sessions")}
              className="text-[10px] px-1.5 py-0.5 rounded bg-amber-700/30 text-amber-300 hover:bg-amber-700/50 transition-colors"
              title="会话大厅（管理会话 / 世界书绑定 / 角色阵容）"
            >
              🏛
            </button>
            <button
              onClick={() => setResourcePanelOpen(!resourcePanelOpen)}
              className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${
                resourcePanelOpen
                  ? "bg-blue-700/50 text-blue-200 hover:bg-blue-700/60"
                  : "bg-blue-700/30 text-blue-300 hover:bg-blue-700/50"
              }`}
              title="会话资源管理（可折叠面板）"
            >
              🗂
            </button>
            <div className="flex items-center gap-1 text-[10px] text-gray-400 select-none">
              <button
                onClick={() => setChatFontSize(chatFontSize - 1)}
                className="px-1.5 py-0.5 rounded bg-gray-700/50 hover:bg-gray-600/60 transition-colors"
                title="减小字体"
              >
                A−
              </button>
              <span className="w-6 text-center text-gray-500">{chatFontSize}</span>
              <button
                onClick={() => setChatFontSize(chatFontSize + 1)}
                className="px-1.5 py-0.5 rounded bg-gray-700/50 hover:bg-gray-600/60 transition-colors"
                title="增大字体"
              >
                A+
              </button>
            </div>
            <button
              onClick={() => setCustomPromptOpen(true)}
              className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${
                activeSession.custom_prompt
                  ? "bg-violet-700/50 text-violet-200 hover:bg-violet-700/60"
                  : "bg-violet-700/30 text-violet-300 hover:bg-violet-700/50"
              }`}
              title={activeSession.custom_prompt ? `自定义提示词: ${activeSession.custom_prompt}` : "自定义提示词"}
            >
              T
            </button>
            {sessionTokens && sessionTokens.total_tokens > 0 && (
              <div className="text-[10px] text-gray-500 select-none shrink-0">
                {sessionTokens.total_tokens.toLocaleString()} tokens
                <span className="text-gray-600">
                  {" "}(入 {sessionTokens.prompt_tokens.toLocaleString()} + 出 {sessionTokens.completion_tokens.toLocaleString()})
                </span>
              </div>
            )}
          </div>
        </div>
      )}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3" style={{ fontSize: `${chatFontSize}px` }}>
        {initialLoading && messages.length === 0 && (
          <div className="flex items-center justify-center h-full text-gray-500">
            <span className="text-sm">加载会话中...</span>
          </div>
        )}

        {showEmptyState && (
          <div className="flex flex-col items-center justify-center h-full text-gray-500">
            {chatMode === "story" ? (
              <>
                <p className="text-lg mb-1">📖 剧情模式</p>
                <p className="text-sm">创建一个剧情会话开始新的故事</p>
                <div className="mt-4 flex gap-2">
                  <button
                    onClick={() => {
                      if (!activeSessionId) return;
                      triggerNarrate(activeSessionId);
                    }}
                    className="btn-primary text-sm" disabled={!activeSessionId}
                  >
                    开始剧情
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="text-lg mb-1">💬 自由对话</p>
                <p className="text-sm">在右侧面板加载角色后即可开始对话</p>
                <p className="text-xs text-gray-600 mt-2">提示：点击角色卡片中的"加入"按钮</p>
              </>
            )}
          </div>
        )}

        {messages.map((msg, i) => {
          const isRoundStart = roundBoundaries.includes(i);
          const isEditing = editingIdx === i;

          return (
            <div key={i}>
              {/* Rollback divider between rounds */}
              {isRoundStart && chatMode === "story" && (
                <div className="flex items-center justify-center my-3">
                  <div className="flex-1 border-t border-gray-700/50" />
                  <button
                    onClick={() => {
                      const prevMsgs = messages.slice(0, i);
                      const prevRound = [...prevMsgs].reverse().find((m) => m.round != null)?.round;
                      if (prevRound != null) handleRollback(prevRound);
                    }}
                    className="mx-3 text-xs text-gray-500 hover:text-red-400 transition-colors whitespace-nowrap"
                  >
                    ↩ 回退
                  </button>
                  <div className="flex-1 border-t border-gray-700/50" />
                </div>
              )}

              <div className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[80%] rounded-xl px-4 py-2.5 leading-relaxed relative group ${
                    msg.role === "user"
                      ? "bg-blue-600 text-white"
                      : msg.role === "character"
                        ? dialogueBubbleMode
                          ? "bg-transparent border-0 p-0 max-w-[95%]"
                          : "bg-purple-800/50 border border-purple-700/30"
                        : msg.role === "narrator"
                          ? dialogueBubbleMode
                            ? "bg-transparent border-0 p-0 max-w-[95%]"
                            : "bg-amber-900/30 border border-amber-700/20 italic text-amber-100"
                          : msg.role === "system" && msg.choices
                            ? "bg-transparent border-0 p-0"
                            : msg.role === "system"
                              ? "bg-gray-700/50 text-gray-400 text-xs font-mono whitespace-pre-wrap"
                              : "bg-gray-800 border border-gray-700"
                  }`}
                >
                  {msg.character && !dialogueBubbleMode && (
                    <div className="text-sm font-bold text-purple-300 mb-1">{msg.character}</div>
                  )}
                  {msg.role === "user" && !dialogueBubbleMode && (
                    <div className="text-sm font-bold text-blue-200 mb-1">
                      {activeSession?.player_identity || "博士"}
                    </div>
                  )}

                  {isEditing ? (
                    <div className="space-y-2">
                      <textarea
                        className="input text-sm w-full text-gray-100"
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        rows={2}
                        autoFocus
                      />
                      <div className="flex gap-2">
                        <button onClick={commitEdit} className="btn-primary text-xs px-2 py-1">保存并继续</button>
                        <button onClick={cancelEdit} className="btn-ghost text-xs px-2 py-1">取消</button>
                      </div>
                    </div>
                  ) : (
                    <>
                      {/* Reasoning/thinking display (collapsible) */}
                      {msg.reasoning && (
                        <details className="mb-2 text-xs">
                          <summary className="text-gray-500 cursor-pointer hover:text-gray-400 select-none">
                            思考过程 ({msg.reasoning.length} 字)
                          </summary>
                          <div className="mt-1 p-2 rounded bg-gray-800/60 text-gray-400 whitespace-pre-wrap border-l-2 border-gray-600 max-h-48 overflow-y-auto">
                            {msg.reasoning}
                          </div>
                        </details>
                      )}
                      {msg.content && renderMessageContent(msg)}

                      {/* Variant navigation (narrator messages in story mode) */}
                      {msg.role === "narrator" && chatMode === "story" && !streaming && msg.variants && (
                        <div className="flex items-center justify-end gap-1 mt-1.5">
                          <button
                            onClick={() => handleVariantPrev(i)}
                            disabled={(msg.variantIndex ?? 0) <= 0}
                            className="text-xs px-1.5 py-0.5 rounded text-gray-500 hover:text-gray-300 disabled:opacity-30 transition-colors"
                            title="上一个版本"
                          >
                            ◂
                          </button>
                          <span className="text-[10px] text-gray-600">
                            {(msg.variantIndex ?? 0) + 1}/{msg.variants.length}
                          </span>
                          <button
                            onClick={() => {
                              if ((msg.variantIndex ?? 0) < msg.variants!.length - 1) {
                                handleVariantNext(i);
                              } else {
                                handleRegeneratePrompt(msg.round ?? 0);
                              }
                            }}
                            className="text-xs px-1.5 py-0.5 rounded text-gray-500 hover:text-gray-300 transition-colors"
                            title={(msg.variantIndex ?? 0) < msg.variants!.length - 1 ? "下一个版本" : "重新生成"}
                          >
                            ▸
                          </button>
                        </div>
                      )}

                      {/* Regeneration prompt input */}
                      {msg.role === "narrator" && regeneratingRound === msg.round && (
                        <div className="mt-2 space-y-1.5">
                          <textarea
                            className="input text-xs w-full text-gray-100"
                            placeholder="输入提示词或留空直接重新生成（如：让叙述更紧张一些）"
                            value={regenerationPrompt}
                            onChange={(e) => setRegenerationPrompt(e.target.value)}
                            rows={2}
                            autoFocus
                            onKeyDown={(e) => {
                              if (e.key === "Enter" && !e.shiftKey) {
                                e.preventDefault();
                                handleRegenerateSubmit();
                              }
                              if (e.key === "Escape") handleRegenerateCancel();
                            }}
                          />
                          <div className="flex gap-1.5">
                            <button
                              onClick={handleRegenerateSubmit}
                              className="text-xs px-2 py-0.5 rounded bg-amber-700/30 text-amber-300 hover:bg-amber-700/50"
                            >
                              重新生成
                            </button>
                            <button
                              onClick={handleRegenerateCancel}
                              className="text-xs px-2 py-0.5 rounded text-gray-500 hover:text-gray-300"
                            >
                              取消
                            </button>
                          </div>
                        </div>
                      )}

                      {msg.choices && (
                        <div className="flex flex-wrap gap-2 mt-1">
                          {msg.choices.map((choice, ci) => (
                            <button
                              key={ci}
                              onClick={() => handleChoiceClick(choice)}
                              disabled={sending || streaming || !!activeSession?.in_combat || (msg.round != null && msg.round < narrationCount)}
                              className="px-3 py-1.5 rounded-lg text-sm border border-amber-600/40
                                text-amber-300 hover:bg-amber-600/20 transition-colors disabled:opacity-50"
                            >
                              {msg.choices!.length > 1 ? `${ci + 1}. ` : ""}{choice}
                            </button>
                          ))}
                        </div>
                      )}
                      {msg.role === "narrator" && streaming && i === messages.length - 1 && (
                        <span className="inline-block w-2 h-4 bg-amber-400/70 ml-1 animate-pulse" />
                      )}

                      {/* Delete button (all messages, hover reveal) */}
                      {!streaming && (
                        <button
                          onClick={() => handleDeleteMessage(i)}
                          className="absolute -top-2 -left-2 w-5 h-5 rounded-full bg-gray-600
                            text-gray-300 hover:bg-red-500 text-[10px] leading-5
                            opacity-0 group-hover:opacity-100 transition-opacity"
                          title="删除此消息"
                        >
                          ×
                        </button>
                      )}

                      {/* Edit button on user messages (story mode only) */}
                      {msg.role === "user" && chatMode === "story" && !streaming && (
                        <button
                          onClick={() => startEdit(i, msg.content)}
                          className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-gray-600
                            text-gray-300 hover:bg-gray-500 text-[10px] leading-5
                            opacity-0 group-hover:opacity-100 transition-opacity"
                          title="编辑此消息"
                        >
                          ✎
                        </button>
                      )}

                      {/* Round badge */}
                      {msg.usage && (msg.role === "narrator" || msg.role === "character") && (
                        <TokenUsage usage={msg.usage} />
                      )}
                      {msg.round != null && (
                        <div className={`text-[10px] mt-1 opacity-40 ${
                          msg.role === "user" ? "text-right text-blue-200" : "text-gray-500"
                        }`}>
                          第{msg.round}轮
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            </div>
          );
        })}
        {isWaitingForLLM && (
          <LoadingIndicator elapsedSeconds={elapsedSeconds} />
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-gray-700 bg-gray-850">
        <div className="flex gap-2">
          <textarea
            className="input resize-none text-sm"
            rows={2}
            placeholder={
              !activeSessionId
                ? "请先选择或创建会话"
                : activeSession?.in_combat
                  ? "战斗中，无法对话..."
                  : sending
                    ? "发送中..."
                    : chatMode === "story"
                      ? "输入行动或对话推进剧情..."
                      : "输入消息..."
            }
            value={activeSession?.in_combat ? "（战斗中 — 请先完成战斗）" : input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={!activeSessionId || sending || !!activeSession?.in_combat}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || !activeSessionId || sending || streaming || !!activeSession?.in_combat}
            className="btn-primary self-end shrink-0"
          >
            {activeSession?.in_combat ? "战斗中" : sending ? "发送中..." : "发送"}
          </button>
        </div>
      </div>

      {/* Custom Prompt Modal */}
      {customPromptOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-gray-800 border border-gray-700 rounded-xl w-[520px] flex flex-col shadow-2xl">
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700">
              <h2 className="text-base font-semibold">自定义提示词</h2>
              <button
                onClick={() => setCustomPromptOpen(false)}
                className="text-gray-500 hover:text-gray-300 text-lg leading-none"
              >
                ✕
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-4">
              <p className="text-xs text-gray-500 mb-3">
                输入你对叙事风格、对话语气或剧情走向的指示。提示词将注入到当前会话的所有后续 LLM 调用中。
              </p>
              <textarea
                className="w-full h-40 bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm text-gray-100
                           resize-y focus:outline-none focus:border-violet-500/50 placeholder-gray-500"
                placeholder={`例如：
用更简洁的语言叙述
增加悬疑氛围
角色对话更活泼一些
避免使用过于华丽的修辞`}
                value={customPromptDraft}
                onChange={(e) => setCustomPromptDraft(e.target.value)}
                autoFocus
              />
            </div>
            <div className="flex items-center justify-between px-5 py-3 border-t border-gray-700">
              <button
                onClick={() => setCustomPromptOpen(false)}
                className="text-xs px-3 py-1.5 rounded text-gray-400 hover:text-gray-200 hover:bg-gray-700/50 transition-colors"
              >
                取消
              </button>
              <div className="flex items-center gap-2">
                {customPromptDraft.trim() && (
                  <button
                    onClick={async () => {
                      if (!activeSessionId) return;
                      setCustomPromptSaving(true);
                      try {
                        await api.saveCustomPrompt(activeSessionId, "");
                        setCustomPromptDraft("");
                        setSessions(sessions.map(s =>
                          s.id === activeSessionId ? { ...s, custom_prompt: undefined } : s
                        ));
                      } catch (err: any) {
                        alert("清除失败: " + (err.message || "未知错误"));
                      } finally {
                        setCustomPromptSaving(false);
                      }
                    }}
                    className="text-xs px-3 py-1.5 rounded text-red-400 hover:text-red-300 hover:bg-red-700/20 transition-colors"
                    disabled={customPromptSaving}
                  >
                    清除
                  </button>
                )}
                <button
                  onClick={async () => {
                    if (!activeSessionId) return;
                    setCustomPromptSaving(true);
                    try {
                      await api.saveCustomPrompt(activeSessionId, customPromptDraft.trim());
                      setSessions(sessions.map(s =>
                        s.id === activeSessionId ? { ...s, custom_prompt: customPromptDraft.trim() || undefined } : s
                      ));
                      setCustomPromptOpen(false);
                    } catch (err: any) {
                      alert("保存失败: " + (err.message || "未知错误"));
                    } finally {
                      setCustomPromptSaving(false);
                    }
                  }}
                  className="btn-primary text-xs px-4 py-1.5"
                  disabled={customPromptSaving}
                >
                  {customPromptSaving ? "保存中..." : "保存"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Combat Briefing Modal — 战前打法选择 */}
      {pendingBriefing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-gray-800 border border-gray-700 rounded-xl w-[520px] flex flex-col shadow-2xl">
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700">
              <h2 className="text-base font-semibold">⚔ {pendingBriefing.name}</h2>
              <button
                onClick={() => setPendingBriefing(null)}
                className="text-gray-500 hover:text-gray-300 text-lg leading-none"
              >
                ✕
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {briefingCheck ? (
                <div>
                  <p className="text-xs text-amber-200 font-display mb-2">
                    🎲 {briefingCheck.attr}检定 — {briefingCheck.character} 掷出 d20 = {briefingCheck.d20} {briefingCheck.modifier >= 0 ? "+" : ""}{briefingCheck.modifier} = {briefingCheck.total} vs DC {briefingCheck.dc}
                  </p>
                  <p className={"text-sm font-bold mb-3 " + (briefingCheck.success ? "text-emerald-300" : "text-red-300")}>
                    {briefingCheck.success ? "✅ 成功 — 避免了战斗" : "❌ 失败 — 敌人警觉，被迫开战"}
                  </p>
                  {briefingCheck.success ? (
                    <button
                      onClick={() => {
                        setPendingBriefing(null);
                        setBriefingCheck(null);
                        setPendingAutoNarrate({ action: "描述交涉成功后的场景与去向" });
                      }}
                      className="btn-primary text-xs px-4 py-1.5"
                    >
                      继续
                    </button>
                  ) : briefingCombatState ? (
                    <button
                      onClick={() => {
                        setCombatContext({ sessionId: pendingBriefing.session_id, state: briefingCombatState });
                        setPendingBriefing(null);
                        setBriefingCheck(null);
                        setBriefingCombatState(null);
                        setCurrentView("combat");
                      }}
                      className="btn-primary text-xs px-4 py-1.5"
                    >
                      进入战斗
                    </button>
                  ) : null}
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  <p className="text-xs text-gray-500 mb-1">选择你的打法：</p>
                  {pendingBriefing.approaches.map((ap) => (
                    <button
                      key={ap.id}
                      onClick={() => handleBriefingApproach(ap.id)}
                      className="text-left px-3 py-2.5 bg-gray-900 border border-gray-700 rounded-lg hover:bg-gray-700 transition-colors"
                    >
                      <span className="text-sm text-gray-200 font-medium">{ap.label}</span>
                      <span className="block text-[11px] text-gray-500 mt-0.5">{ap.hint}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

// ── SSE narrate helper ──

function triggerNarrate(
  sessionId: string,
  action?: string,
) {
  const store = useAppStore.getState();

  // Abort previous SSE for the SAME session only
  const prevAbort = store.sessionAbortFns[sessionId];
  prevAbort?.();

  store.setSessionStreaming(sessionId, true);

  const curCount = store.sessionNarrationCount[sessionId] || 0;
  const newRound = curCount + 1;
  store.setSessionNarrationCount(sessionId, newRound);

  // 玩家身份：优先使用会话创建时选择的身份角色
  const session = store.sessions.find((s) => s.id === sessionId);
  const identity = session?.player_identity || "博士";

  let accumulated = "";
  let accumulatedReasoning = "";

  const url = action
    ? `/api/sessions/${sessionId}/narrate?identity=${encodeURIComponent(identity)}&action=${encodeURIComponent(action)}`
    : `/api/sessions/${sessionId}/narrate?identity=${encodeURIComponent(identity)}`;

  const sse = createSSE(url, {
      onReasoning: (token: string) => {
        accumulatedReasoning += token;
        useAppStore.getState().setSessionMessages(sessionId, (prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "narrator" && last.round === newRound) {
            return [...prev.slice(0, -1), { ...last, reasoning: accumulatedReasoning }];
          }
          return [...prev, { role: "narrator", content: "", reasoning: accumulatedReasoning, round: newRound }];
        });
      },
      onText: (token: string) => {
        accumulated += token;
        useAppStore.getState().setSessionMessages(sessionId, (prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "narrator" && last.round === newRound) {
            return [...prev.slice(0, -1), { role: "narrator", content: accumulated, round: newRound }];
          }
          return [...prev, { role: "narrator", content: accumulated, round: newRound }];
        });
      },
      onSceneEvent: () => useAppStore.getState().triggerEnvRefresh(),
      onMemoryEvent: () => useAppStore.getState().triggerMemoryRefresh(),
      onChoice: (options: string[]) => {
        useAppStore.getState().setSessionMessages(sessionId, (prev) => [
          ...prev,
          { role: "system", content: "— 请选择 —", choices: options, round: newRound },
        ]);
      },
      onDialogueSegments: (segments) => {
        useAppStore.getState().setSessionMessages(sessionId, (prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "narrator" && last.round === newRound) {
            return [...prev.slice(0, -1), { ...last, dialogueSegments: segments }];
          }
          return prev;
        });
      },
      onTokenUsage: (usage) => {
        useAppStore.getState().setSessionMessages(sessionId, (prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "narrator" && last.round === newRound) {
            return [...prev.slice(0, -1), { ...last, usage }];
          }
          return prev;
        });
      },
      onCombatTrigger: (data: { encounter_id: string; session_id: string }) => {
        useAppStore.getState().setSessionStreaming(sessionId, false);
        useAppStore.getState().setSessionSending(sessionId, false);
        useAppStore.getState().setCombatContext({ sessionId: data.session_id });
        useAppStore.getState().setCurrentView("combat");
      },
      onCombatBriefing: (data: { encounter_id: string; session_id: string; name: string; approaches: { id: string; label: string; hint: string; kind: "combat" | "check" | "avoid" }[] }) => {
        useAppStore.getState().setSessionStreaming(sessionId, false);
        useAppStore.getState().setSessionSending(sessionId, false);
        useAppStore.getState().setPendingBriefing(data);
      },
      onAttributeRoll: (data: {
        attribute: string; character: string; roll: number;
        modifier: number; total: number; dc: number;
        success: boolean; text: string; source: string; stream_id: string;
      }) => {
        useAppStore.getState().setSessionMessages(sessionId, (prev) => [
          ...prev,
          {
            role: "system",
            content: data.text,
            rollData: data,
          },
        ]);
      },
      onError: (msg: string) => {
        useAppStore.getState().setSessionStreaming(sessionId, false);
        useAppStore.getState().setSessionSending(sessionId, false);
        useAppStore.getState().setSessionMessages(sessionId, (prev) => [...prev, { role: "system", content: `错误: ${msg}` }]);
      },
      onDone: () => {
        useAppStore.getState().setSessionStreaming(sessionId, false);
        useAppStore.getState().setSessionSending(sessionId, false);
        useAppStore.getState().setSessionMessages(sessionId, (prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "narrator" && last.round === newRound) {
            return [...prev.slice(0, -1), { ...last, variants: [last.content], variantIndex: 0 }];
          }
          return prev;
        });
      },
    }
  );

  useAppStore.getState().setSessionAbortFn(sessionId, () => sse.close());
}
