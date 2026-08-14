/**
 * 对话页（沉浸式）— 全屏无 sidebar。
 * 顶栏提供：返回大厅 / 主菜单、对话模式切换、场景面板折叠。
 * 进入会话即沉浸体验故事；调整世界书/阵容等请退出到会话大厅。
 */
import { useState } from "react";
import { useAppStore } from "../stores/appStore";
import CharacterPanel from "./CharacterPanel";
import ItemPanel from "./ItemPanel";
import EnvironmentPanel from "./EnvironmentPanel";
import ChatPanel from "./ChatPanel";
import CharacterBrowser from "./CharacterBrowser";
import ItemBrowser from "./ItemBrowser";
import MemoryPanel from "./MemoryPanel";
import QuestPanel from "./QuestPanel";
import SessionResourcePanel from "./session/SessionResourcePanel";

export default function ChatView() {
  const resourcePanelOpen = useAppStore((s) => s.resourcePanelOpen);
  const { setCurrentView, chatMode, setChatMode, activeSessionId, sessions } = useAppStore();
  const [panelsOpen, setPanelsOpen] = useState(true);
  const [charBrowserOpen, setCharBrowserOpen] = useState(false);
  const [itemBrowserOpen, setItemBrowserOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const activeSession = sessions.find((s) => s.id === activeSessionId);

  return (
    <div className="flex flex-col h-full">
      {/* ═══ 沉浸式顶栏 ═══ */}
      <div className="h-10 shrink-0 flex items-center gap-1.5 px-2 border-b border-gray-700/50 bg-gray-900/95 backdrop-blur-sm relative z-20">
        <button
          onClick={() => setCurrentView("sessions")}
          className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs text-amber-300/90 hover:text-amber-200 hover:bg-amber-500/10 transition-colors"
          title="退出会话，返回会话大厅（调节世界书 / 阵容 / 设置）"
        >
          <span>◀</span>
          <span>返回大厅</span>
        </button>
        <button
          onClick={() => setCurrentView("home")}
          className="px-2 py-1 rounded-lg text-xs text-gray-500 hover:text-gray-300 hover:bg-gray-700/50 transition-colors"
          title="返回主菜单"
        >
          🏠
        </button>

        <div className="w-px h-4 bg-gray-700/70 mx-1" />

        {/* 对话模式切换（迁移自旧 sidebar） */}
        <div className="flex gap-1">
          <button
            onClick={() => setChatMode("story")}
            className={"px-2.5 py-0.5 text-[11px] rounded-md transition-colors " + (
              chatMode === "story"
                ? "bg-amber-600/80 text-white"
                : "bg-gray-800 text-gray-500 hover:text-gray-300"
            )}
          >
            剧情
          </button>
          <button
            onClick={() => setChatMode("free")}
            className={"px-2.5 py-0.5 text-[11px] rounded-md transition-colors " + (
              chatMode === "free"
                ? "bg-purple-600/80 text-white"
                : "bg-gray-800 text-gray-500 hover:text-gray-300"
            )}
          >
            自由
          </button>
        </div>

        {activeSession && (
          <span className="ml-2 text-[11px] text-gray-500 truncate hidden md:inline">
            {activeSession.name || "未命名会话"}
          </span>
        )}

        <div className="flex-1" />

        {/* 场景面板折叠：收起后聊天区全宽，完全沉浸 */}
        <button
          onClick={() => setPanelsOpen((v) => !v)}
          className={"px-2.5 py-1 rounded-lg text-xs transition-colors " + (
            panelsOpen
              ? "text-gray-400 hover:text-gray-200 hover:bg-gray-700/50"
              : "text-blue-300 bg-blue-600/20 hover:bg-blue-600/30"
          )}
          title={panelsOpen ? "收起场景面板，全屏沉浸" : "展开场景面板"}
        >
          {panelsOpen ? "◧ 收起面板" : "◨ 场景面板"}
        </button>
      </div>

      {/* ═══ 主体 ═══ */}
      <div className="flex flex-1 min-h-0">
        {/* Left: scene panels（可折叠） */}
        {panelsOpen && (
          <div className="w-72 border-r border-gray-700 overflow-y-auto p-3 space-y-3 shrink-0">
            <CharacterPanel
              refreshKey={refreshKey}
              onAddClick={() => setCharBrowserOpen(true)}
            />
            <ItemPanel
              refreshKey={refreshKey}
              onAddClick={() => setItemBrowserOpen(true)}
            />
            <EnvironmentPanel />
            <MemoryPanel />
            <QuestPanel />
          </div>
        )}

        {/* Right: chat */}
        <div className="flex-1 flex flex-col min-w-0">
          <ChatPanel />
        </div>

        {/* Right panel: 会话资源（可折叠） */}
        {resourcePanelOpen && <SessionResourcePanel />}
      </div>

      {/* Character browser modal */}
      <CharacterBrowser
        open={charBrowserOpen}
        onClose={() => setCharBrowserOpen(false)}
        onAdded={() => setRefreshKey((k) => k + 1)}
      />

      {/* Item browser modal */}
      <ItemBrowser
        open={itemBrowserOpen}
        onClose={() => setItemBrowserOpen(false)}
        onAdded={() => setRefreshKey((k) => k + 1)}
      />
    </div>
  );
}
