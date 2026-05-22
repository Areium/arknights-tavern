import { useState, useRef, useEffect, useCallback } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi, createSSE } from "../hooks/useApi";

interface Message {
  role: "user" | "assistant" | "character" | "system" | "narrator";
  content: string;
  character?: string;
  choices?: string[];
}

/** 过滤 scene_log，排除"博士加入"等冗余条目 */
function filterSceneLog(log: string[]): string[] {
  return log.filter(
    (entry) =>
      !entry.includes("博士加入了场景") &&
      !entry.includes("博士切换")
  );
}

export default function ChatPanel() {
  const { activeSessionId, chatMode, sessions } = useAppStore();
  const activeMode = sessions.find((s) => s.id === activeSessionId)?.mode || "free";
  const api = useApi();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sending, setSending] = useState(false);
  const [initialLoading, setInitialLoading] = useState(false);
  const abortRef = useRef<(() => void) | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  const storageKey = activeSessionId ? `ark_chat_${activeMode}_${activeSessionId}` : null;

  // On session/mode change: load from localStorage or backend, then optionally auto-narrate
  useEffect(() => {
    setMessages([]);
    setStreaming(false);
    setSending(false);
    abortRef.current?.();
    abortRef.current = null;

    if (!activeSessionId) return;
    const sid: string = activeSessionId;
    const key = `ark_chat_${activeMode}_${sid}`;

    let cancelled = false;

    async function init() {
      // 1. Try localStorage first
      const cached = localStorage.getItem(key);
      if (cached) {
        try {
          const parsed = JSON.parse(cached);
          if (Array.isArray(parsed) && parsed.length > 0) {
            if (!cancelled) {
              setMessages(parsed);
              setInitialLoading(false);
            }
            return; // skip backend fetch — localStorage is the source of truth
          }
        } catch { /* corrupt cache, fall through to backend */ }
      }

      // 2. Fallback: load from backend scene_log
      setInitialLoading(true);
      try {
        const session = await api.getSession(sid);
        if (cancelled) return;

        const initialMessages: Message[] = [];

        const log = filterSceneLog(session.scene_log || []);
        if (log.length > 0) {
          initialMessages.push({
            role: "system",
            content: `【场景记录】\n${log.join("\n")}`,
          });
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
            .map((c: any) =>
              typeof c === "string" ? c : c.name || c.id
            )
            .join("、");
          initialMessages.push({
            role: "system",
            content: `【已加载角色】${charList}`,
          });
        }

        if (!cancelled) setMessages(initialMessages);
      } catch {
        // Session might be fresh with no history — that's fine
      } finally {
        if (!cancelled) setInitialLoading(false);
      }

      // 3. Story mode: auto-start narration
      if (chatMode === "story" && !cancelled) {
        triggerNarrate(sid, setMessages, setStreaming, abortRef);
      }
    }

    init();
    return () => {
      cancelled = true;
      abortRef.current?.();
    };
  }, [activeSessionId, chatMode, api]);

  // Persist messages to localStorage whenever they change
  useEffect(() => {
    if (!storageKey || messages.length === 0) return;
    try {
      localStorage.setItem(storageKey, JSON.stringify(messages));
    } catch { /* localStorage full or unavailable */ }
  }, [messages, storageKey]);

  // Extracted send logic for both handleSend and handleChoiceClick
  const performSend = useCallback(
    async (text: string) => {
      if (!activeSessionId) return;
      setStreaming(true);

      try {
        if (chatMode === "free") {
          const res = await api.groupChat(activeSessionId, text);
          const items: any[] = res.responses || res;
          const responses: Message[] = items.map((r: any) => ({
            role: "character",
            content: r.response,
            character: r.character,
          }));
          setMessages((prev) => {
            if (responses.length === 0) {
              return [
                ...prev,
                {
                  role: "system",
                  content: "（没有角色回复 — 请先在右侧面板加载角色）",
                },
              ];
            }
            return [...prev, ...responses];
          });
        } else {
          const data = await api.narrateContinue(
            activeSessionId,
            "博士",
            text
          );

          const newMsgs: Message[] = [];

          if (data.narrative) {
            newMsgs.push({ role: "narrator", content: data.narrative });
          }

          if (data.env_updates && Object.keys(data.env_updates).length > 0) {
            const changes = Object.entries(data.env_updates)
              .filter(([, v]) => v)
              .map(([k, v]) => `${k}: ${v}`)
              .join(" · ");
            newMsgs.push({ role: "system", content: `【环境更新】${changes}` });
          }

          const defaultChoices = data.choices || (() => {
            const opts = ["继续推进剧情"];
            if (data.active_character) {
              opts.push(`对${data.active_character}说话`);
            }
            return opts;
          })();
          newMsgs.push({
            role: "system",
            content: "— 请选择 —",
            choices: defaultChoices,
          });

          setMessages((prev) => [...prev, ...newMsgs]);
        }
      } catch (err: any) {
        setMessages((prev) => [
          ...prev,
          { role: "system", content: `请求失败: ${err.message}` },
        ]);
      } finally {
        setSending(false);
        setStreaming(false);
      }
    },
    [activeSessionId, chatMode, api]
  );

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || sending || streaming) return;

    setInput("");
    setSending(true);
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    performSend(text);
  }, [input, sending, streaming, performSend]);

  // Choice button click → auto-fill or send
  const handleChoiceClick = useCallback(
    (choice: string) => {
      setInput("");
      setMessages((prev) => [...prev, { role: "user", content: choice }]);
      performSend(choice);
    },
    [performSend]
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const showEmptyState = messages.length === 0 && !initialLoading;

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {/* Initial loading */}
        {initialLoading && messages.length === 0 && (
          <div className="flex items-center justify-center h-full text-gray-500">
            <span className="text-sm">加载会话中...</span>
          </div>
        )}

        {/* Empty state */}
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
                      triggerNarrate(
                        activeSessionId,
                        setMessages,
                        setStreaming,
                        abortRef
                      );
                    }}
                    className="btn-primary text-sm"
                    disabled={!activeSessionId}
                  >
                    开始剧情
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="text-lg mb-1">💬 自由对话</p>
                <p className="text-sm">
                  在右侧面板加载角色后即可开始对话
                </p>
                <p className="text-xs text-gray-600 mt-2">
                  提示：点击角色卡片中的"加入"按钮
                </p>
              </>
            )}
          </div>
        )}

        {/* Message list */}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-xl px-4 py-2.5 text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-blue-600 text-white"
                  : msg.role === "character"
                    ? "bg-purple-800/50 border border-purple-700/30"
                    : msg.role === "narrator"
                      ? "bg-amber-900/30 border border-amber-700/20 italic text-amber-100"
                      : msg.role === "system" && msg.choices
                        ? "bg-transparent border-0 p-0"
                        : msg.role === "system"
                          ? "bg-gray-700/50 text-gray-400 text-xs font-mono whitespace-pre-wrap"
                          : "bg-gray-800 border border-gray-700"
              }`}
            >
              {msg.character && (
                <div className="text-xs font-bold text-purple-300 mb-1">
                  {msg.character}
                </div>
              )}
              {msg.content && (
                <div className="whitespace-pre-wrap">{msg.content}</div>
              )}
              {msg.choices && (
                <div className="flex flex-wrap gap-2 mt-1">
                  {msg.choices.map((choice, ci) => (
                    <button
                      key={ci}
                      onClick={() => handleChoiceClick(choice)}
                      disabled={sending || streaming}
                      className="px-3 py-1.5 rounded-lg text-sm border border-amber-600/40
                        text-amber-300 hover:bg-amber-600/20 transition-colors
                        disabled:opacity-50"
                    >
                      {msg.choices!.length > 1 ? `${ci + 1}. ` : ""}{choice}
                    </button>
                  ))}
                </div>
              )}
              {msg.role === "narrator" && streaming && i === messages.length - 1 && (
                <span className="inline-block w-2 h-4 bg-amber-400/70 ml-1 animate-pulse" />
              )}
            </div>
          </div>
        ))}
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
                : sending
                  ? "发送中..."
                  : chatMode === "story"
                    ? "输入行动或对话推进剧情..."
                    : "输入消息..."
            }
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={!activeSessionId || sending}
          />
          <button
            onClick={handleSend}
            disabled={
              !input.trim() || !activeSessionId || sending || streaming
            }
            className="btn-primary self-end shrink-0"
          >
            {sending ? "发送中..." : "发送"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Separate helper: trigger initial narrative SSE ──

function triggerNarrate(
  sessionId: string | null,
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>,
  setStreaming: (v: boolean) => void,
  abortRef: React.MutableRefObject<(() => void) | null>
) {
  if (!sessionId) return;
  abortRef.current?.();
  setStreaming(true);
  let accumulated = "";

  const sse = createSSE(
    `/api/sessions/${sessionId}/narrate?identity=${encodeURIComponent("博士")}`,
    {
      onText: (token: string) => {
        accumulated += token;
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "narrator") {
            return [
              ...prev.slice(0, -1),
              { role: "narrator", content: accumulated },
            ];
          }
          return [...prev, { role: "narrator", content: accumulated }];
        });
      },
      onChoice: (options: string[]) => {
        setMessages((prev) => [
          ...prev,
          { role: "system", content: "— 请选择 —", choices: options },
        ]);
      },
      onError: (msg: string) => {
        setStreaming(false);
        setMessages((prev) => [
          ...prev,
          { role: "system", content: `错误: ${msg}` },
        ]);
      },
      onDone: () => {
        setStreaming(false);
      },
    }
  );

  abortRef.current = () => sse.close();
}
