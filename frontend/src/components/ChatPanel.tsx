import { useState, useRef, useEffect, useCallback } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi, createSSE, createPostSSE } from "../hooks/useApi";

interface Message {
  role: "user" | "assistant" | "character" | "system" | "narrator";
  content: string;
  character?: string;
}

export default function ChatPanel() {
  const { activeSessionId, chatMode } = useAppStore();
  const api = useApi();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [sending, setSending] = useState(false);
  const [narrated, setNarrated] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  // On session/mode change, reset messages
  useEffect(() => {
    setMessages([]);
    setNarrated(false);
  }, [activeSessionId, chatMode]);

  // Story mode: fetch initial narration on mount
  useEffect(() => {
    if (!activeSessionId || chatMode !== "story" || narrated) return;
    setNarrated(true);
    setStreaming(true);
    let accumulated = "";

    const sse = createSSE(`/api/sessions/${activeSessionId}/narrate`, {
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
          {
            role: "system",
            content: `【选项】\n${options
              .map((o, i) => `${i + 1}. ${o}`)
              .join("\n")}`,
          },
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
    });

    return () => sse.close();
  }, [activeSessionId, chatMode, narrated, api]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || !activeSessionId || sending || streaming) return;

    setInput("");
    setSending(true);

    // Add user message
    setMessages((prev) => [...prev, { role: "user", content: text }]);

    try {
      if (chatMode === "free") {
        // Free mode: group chat — all characters respond in parallel
        const res = await api.groupChat(activeSessionId, text);
        const items: any[] = res.responses || res;
        const responses: Message[] = items.map((r: any) => ({
          role: "character",
          content: r.response,
          character: r.character,
        }));
        setMessages((prev) => [...prev, ...responses]);
      } else {
        // Story mode: POST narrate-continue (returns JSON with full narrative)
        setStreaming(true);
        const data = await api.narrateContinue(activeSessionId, "博士", text);

        if (data.narrative) {
          setMessages((prev) => [
            ...prev,
            { role: "narrator", content: data.narrative },
          ]);
        }

        // Show follow-up choices
        const choices = ["继续推进剧情"];
        if (data.active_character) {
          choices.push(`对${data.active_character}说话`);
        }
        choices.push("自行输入...");
        setMessages((prev) => [
          ...prev,
          {
            role: "system",
            content: `【选项】\n${choices
              .map((o, i) => `${i + 1}. ${o}`)
              .join("\n")}`,
          },
        ]);
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
  }, [input, activeSessionId, chatMode, sending, streaming, api]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-gray-500">
            <p className="text-lg mb-1">
              {chatMode === "story" ? "📖 剧情模式" : "💬 自由对话"}
            </p>
            <p className="text-sm">
              {chatMode === "story"
                ? "正在开启新的故事..."
                : "与已加载的角色自由对话"}
            </p>
            <div className="mt-4 flex gap-2">
              <button
                onClick={() => setNarrated(false)}
                className="btn-primary text-sm"
              >
                开始剧情
              </button>
            </div>
          </div>
        )}
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
              <div className="whitespace-pre-wrap">{msg.content}</div>
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
              activeSessionId
                ? sending
                  ? "发送中..."
                  : chatMode === "story"
                    ? "输入行动或对话推进剧情..."
                    : "输入消息..."
                : "请先选择或创建会话"
            }
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={!activeSessionId || sending}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || !activeSessionId || sending || streaming}
            className="btn-primary self-end shrink-0"
          >
            {sending ? "发送中..." : "发送"}
          </button>
        </div>
      </div>
    </div>
  );
}
