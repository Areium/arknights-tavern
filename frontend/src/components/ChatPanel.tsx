import { useState, useRef, useEffect, useCallback } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi, createSSE } from "../hooks/useApi";
import { parseDialogue } from "../utils/dialogueParser";
import DialogueBubble from "./chat/DialogueBubble";
import NarrationText from "./chat/NarrationText";
import LoadingIndicator from "./chat/LoadingIndicator";
import TokenUsage from "./chat/TokenUsage";

interface Message {
  role: "user" | "assistant" | "character" | "system" | "narrator";
  content: string;
  character?: string;
  choices?: string[];
  round?: number;
  variants?: string[];
  variantIndex?: number;
  dialogueSegments?: { type: string; text: string; speaker?: string }[];
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  reasoning?: string;
}

function filterSceneLog(log: string[]): string[] {
  return log.filter(
    (entry) =>
      !entry.includes("博士加入了场景") &&
      !entry.includes("博士切换")
  );
}

export default function ChatPanel() {
  const { activeSessionId, chatMode, sessions, setSessions, triggerEnvRefresh, triggerMemoryRefresh, chatRefreshKey, characterRefreshKey, editBeforeSend, sceneSwitchKey, dialogueBubbleMode, currentView, setCurrentView, setCombatContext, pendingAutoNarrate, setPendingAutoNarrate } = useAppStore();
  const activeMode = sessions.find((s) => s.id === activeSessionId)?.mode || "free";

  const sceneCharacters: string[] = (() => {
    const session = sessions.find((s) => s.id === activeSessionId);
    if (!session || !session.characters) return [];
    return session.characters.map((c: any) =>
      typeof c === "string" ? c : c.name || c.id || ""
    );
  })();

  const [characterColors, setCharacterColors] = useState<Record<string, string>>({});

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
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sending, setSending] = useState(false);
  const [initialLoading, setInitialLoading] = useState(false);
  const [narrationCount, setNarrationCount] = useState(0);
  const narrationCountRef = useRef(0);
  const updateNarrationCount = (value: number) => {
    narrationCountRef.current = value;
    setNarrationCount(value);
  };
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [regeneratingRound, setRegeneratingRound] = useState<number | null>(null);
  const [regenerationPrompt, setRegenerationPrompt] = useState("");
  const abortRef = useRef<(() => void) | null>(null);
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

  const storageKey = activeSessionId ? `ark_chat_${activeMode}_${activeSessionId}` : null;

  // ── Session load / restore ──

  useEffect(() => {
    setMessages([]);
    setStreaming(false);
    setSending(false);
    updateNarrationCount(0);
    setEditingIdx(null);
    abortRef.current?.();
    abortRef.current = null;

    if (!activeSessionId) return;
    const sid: string = activeSessionId;
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
              setMessages(parsed);
              setInitialLoading(false);
              // Restore narrationCount from max round
              const maxRound = Math.max(0, ...parsed
                .filter((m: Message) => m.round != null)
                .map((m: Message) => m.round!));
              updateNarrationCount(maxRound);
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
        updateNarrationCount(session.narration_count || 0);

        const initialMessages: Message[] = [];
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
        if (!cancelled) setMessages(initialMessages);
      } catch {
        // Fresh session
      } finally {
        if (!cancelled) setInitialLoading(false);
      }

      // 3. Story mode auto-narrate
      if (chatMode === "story" && !cancelled) {
        triggerNarrate(sid, setMessages, setStreaming, abortRef, triggerEnvRefresh, triggerMemoryRefresh, setNarrationCount, narrationCountRef);
      }
    }

    init();
    return () => {
      cancelled = true;
      abortRef.current?.();
    };
  }, [activeSessionId, chatMode, api]);

  // ── Persist ──

  useEffect(() => {
    if (!storageKey || messages.length === 0) return;
    try {
      localStorage.setItem(storageKey, JSON.stringify(messages));
    } catch { /* full */ }
  }, [messages, storageKey]);

  // ── External rollback (from MemoryPanel) ──

  useEffect(() => {
    if (!activeSessionId || chatRefreshKey === 0) return;
    (async () => {
      try {
        const session = await api.getSession(activeSessionId);
        const targetRound = session.narration_count || 0;
        updateNarrationCount(targetRound);
        setMessages((prev) => prev.filter((m) => !m.round || m.round <= targetRound));
      } catch { /* ignore */ }
    })();
  }, [chatRefreshKey]);

  // ── Scene switch narration (story mode) ──

  useEffect(() => {
    if (!activeSessionId || chatMode !== "story" || sceneSwitchKey === 0) return;
    triggerNarrate(
      activeSessionId, setMessages, setStreaming, abortRef,
      triggerEnvRefresh, triggerMemoryRefresh, setNarrationCount, narrationCountRef,
    );
  }, [sceneSwitchKey]);

  // ── Rollback ──

  const handleRollback = useCallback(async (targetRound: number) => {
    if (!activeSessionId) return;
    if (!confirm(`回退到第 ${targetRound} 轮？\n之后的对话记录和回忆将被删除。`)) return;

    try {
      await api.rollbackSession(activeSessionId, targetRound);
      setMessages((prev) => prev.filter((m) => !m.round || m.round <= targetRound));
      updateNarrationCount(targetRound);
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
        updateNarrationCount(rollbackTo);
        triggerMemoryRefresh();
      }

      // 截断消息列表，添加用户编辑后的消息
      setMessages((prev) => {
        const keep = prev.slice(0, editingIdx);
        return [...keep, { role: "user", content: edited, round: rollbackTo + 1 }];
      });

      setEditingIdx(null);
      setEditText("");

      // SSE 流式生成编辑后的叙述（newRound = rollbackTo + 1）
      triggerNarrate(
        activeSessionId, setMessages, setStreaming, abortRef,
        triggerEnvRefresh, triggerMemoryRefresh, setNarrationCount,
        narrationCountRef, edited,
      );
    } catch (err: any) {
      alert("编辑失败: " + (err.message || "未知错误"));
      setStreaming(false);
    }
  }, [editingIdx, editText, activeSessionId, messages, api, triggerMemoryRefresh, cancelEdit]);

  // ── Send ──

  const performSend = useCallback(
    async (text: string) => {
      if (!activeSessionId) return;

      // Story mode: use SSE streaming for progressive token display
      if (chatMode === "story") {
        triggerNarrate(
          activeSessionId, setMessages, setStreaming, abortRef,
          triggerEnvRefresh, triggerMemoryRefresh, setNarrationCount, narrationCountRef,
          text, setSending,
        );
        return;
      }

      // Free mode: blocking POST (group chat)
      setStreaming(true);
      try {
        const res = await api.groupChat(activeSessionId, text);
        const items: any[] = res.responses || res;
        const responses: Message[] = items.map((r: any) => ({
          role: "character",
          content: r.response,
          character: r.character,
          usage: r.usage,
        }));
        setMessages((prev) => {
          if (responses.length === 0) {
            return [...prev, { role: "system", content: "（没有角色回复 — 请先在右侧面板加载角色）" }];
          }
          return [...prev, ...responses];
        });
      } catch (err: any) {
        setMessages((prev) => [...prev, { role: "system", content: `请求失败: ${err.message}` }]);
      } finally {
        setSending(false);
        setStreaming(false);
      }
    },
    [activeSessionId, chatMode, api, triggerEnvRefresh, triggerMemoryRefresh]
  );

  // Auto-narrate after combat: watch for pendingAutoNarrate being set
  useEffect(() => {
    if (pendingAutoNarrate && activeSessionId) {
      const action = pendingAutoNarrate;
      setPendingAutoNarrate(null);
      // Delay slightly to ensure view switch completes before narrating
      const timer = setTimeout(() => {
        performSend(action);
      }, 300);
      return () => clearTimeout(timer);
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
    if (!text || sending || streaming) return;

    const curRound = narrationCountRef.current;
    setInput("");
    setSending(true);
    setMessages((prev) => [...prev, { role: "user", content: text, round: curRound }]);
    performSend(text);
  }, [input, sending, streaming, performSend]);

  const handleChoiceClick = useCallback(
    (choice: string) => {
      if (editBeforeSend) {
        setInput(choice);
        return;
      }
      const curRound = narrationCountRef.current;
      setInput("");
      setMessages((prev) => [...prev, { role: "user", content: choice, round: curRound }]);
      performSend(choice);
    },
    [performSend, editBeforeSend]
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
    setMessages((prev) => {
      const msg = prev[idx];
      if (!msg.variants || (msg.variantIndex ?? 0) <= 0) return prev;
      const newIdx = (msg.variantIndex ?? 0) - 1;
      const narrative = msg.variants[newIdx];
      const updated = { ...msg, content: narrative, variantIndex: newIdx, dialogueSegments: undefined };
      syncVariantToBackend(msg.round, narrative);
      return [...prev.slice(0, idx), updated, ...prev.slice(idx + 1)];
    });
  }, [syncVariantToBackend]);

  const handleVariantNext = useCallback((idx: number) => {
    setMessages((prev) => {
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
  }, [syncVariantToBackend]);

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
    const prompt = regenerationPrompt.trim();
    setRegenerationPrompt("");
    setRegeneratingRound(null);
    setStreaming(true);
    try {
      const data = await api.narrateVariant(activeSessionId, prompt);
      const newNarrative: string = data.narrative;
      setMessages((prev) => {
        // Find the narrator message for this round
        const idx = prev.findIndex(
          (m) => m.role === "narrator" && m.round === regeneratingRound
        );
        if (idx === -1) return prev;
        const msg = prev[idx];
        const variants = msg.variants || [msg.content];
        const newIdx = variants.length;
        const updated: Message = {
          ...msg,
          content: newNarrative,
          variants: [...variants, newNarrative],
          variantIndex: newIdx,
          dialogueSegments: data.dialogue_segments || msg.dialogueSegments,
          usage: data.usage || msg.usage,
        };
        // Sync selected variant to backend
        api.narrateUpdate(activeSessionId, regeneratingRound, newNarrative).catch(() => {});
        return [...prev.slice(0, idx), updated, ...prev.slice(idx + 1)];
      });
    } catch (err: any) {
      alert("重新生成失败: " + (err.message || "未知错误"));
    } finally {
      setStreaming(false);
    }
  }, [activeSessionId, regeneratingRound, regenerationPrompt, api]);

  const handleSelectVariant = useCallback(async (idx: number, variantIdx: number) => {
    if (!activeSessionId) return;
    setMessages((prev) => {
      const msg = prev[idx];
      if (!msg.variants) return prev;
      const updated = { ...msg, content: msg.variants[variantIdx], variantIndex: variantIdx };
      // Sync selected variant to backend
      if (msg.round != null) {
        api.narrateUpdate(activeSessionId, msg.round, msg.variants[variantIdx]).catch(() => {});
      }
      return [...prev.slice(0, idx), updated, ...prev.slice(idx + 1)];
    });
  }, [activeSessionId, api]);

  // ── Single message deletion ──

  const handleDeleteMessage = useCallback((idx: number) => {
    setMessages((prev) => {
      if (idx < 0 || idx >= prev.length) return prev;
      return [...prev.slice(0, idx), ...prev.slice(idx + 1)];
    });
  }, []);

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

  function renderMessageContent(msg: Message): React.ReactNode {
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
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
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
                      triggerNarrate(activeSessionId, setMessages, setStreaming, abortRef,
                        triggerEnvRefresh, triggerMemoryRefresh, setNarrationCount, narrationCountRef);
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
                  className={`max-w-[80%] rounded-xl px-4 py-2.5 text-sm leading-relaxed relative group ${
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
    </div>
  );
}

// ── SSE narrate helper ──

function triggerNarrate(
  sessionId: string | null,
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>,
  setStreaming: (v: boolean) => void,
  abortRef: React.MutableRefObject<(() => void) | null>,
  triggerEnvRefresh: () => void,
  triggerMemoryRefresh: () => void,
  setNarrationCount: React.Dispatch<React.SetStateAction<number>>,
  narrationCountRef: React.MutableRefObject<number>,
  action?: string,
  setSending?: (v: boolean) => void,
) {
  if (!sessionId) return;
  abortRef.current?.();
  setStreaming(true);
  let accumulated = "";
  let accumulatedReasoning = "";

  const newRound = narrationCountRef.current + 1;
  narrationCountRef.current = newRound;
  setNarrationCount(newRound);

  const url = action
    ? `/api/sessions/${sessionId}/narrate?identity=${encodeURIComponent("博士")}&action=${encodeURIComponent(action)}`
    : `/api/sessions/${sessionId}/narrate?identity=${encodeURIComponent("博士")}`;

  const sse = createSSE(url, {
      onReasoning: (token: string) => {
        accumulatedReasoning += token;
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "narrator" && last.round === newRound) {
            return [...prev.slice(0, -1), { ...last, reasoning: accumulatedReasoning }];
          }
          return [...prev, { role: "narrator", content: "", reasoning: accumulatedReasoning, round: newRound }];
        });
      },
      onText: (token: string) => {
        accumulated += token;
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "narrator" && last.round === newRound) {
            return [...prev.slice(0, -1), { role: "narrator", content: accumulated, round: newRound }];
          }
          return [...prev, { role: "narrator", content: accumulated, round: newRound }];
        });
      },
      onSceneEvent: () => triggerEnvRefresh(),
      onMemoryEvent: () => triggerMemoryRefresh(),
      onChoice: (options: string[]) => {
        setMessages((prev) => [
          ...prev,
          { role: "system", content: "— 请选择 —", choices: options, round: newRound },
        ]);
      },
      onDialogueSegments: (segments) => {
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "narrator" && last.round === newRound) {
            return [...prev.slice(0, -1), { ...last, dialogueSegments: segments }];
          }
          return prev;
        });
      },
      onTokenUsage: (usage) => {
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "narrator" && last.round === newRound) {
            return [...prev.slice(0, -1), { ...last, usage }];
          }
          return prev;
        });
      },
      onCombatTrigger: (data: { encounter_id: string; session_id: string }) => {
        setStreaming(false);
        setSending?.(false);
        useAppStore.getState().setCombatContext({ sessionId: data.session_id });
        useAppStore.getState().setCurrentView("combat");
      },
      onError: (msg: string) => {
        setStreaming(false);
        setSending?.(false);
        setMessages((prev) => [...prev, { role: "system", content: `错误: ${msg}` }]);
      },
      onDone: () => {
        setStreaming(false);
        setSending?.(false);
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "narrator" && last.round === newRound) {
            return [...prev.slice(0, -1), { ...last, variants: [last.content], variantIndex: 0 }];
          }
          return prev;
        });
      },
    }
  );

  abortRef.current = () => sse.close();
}
