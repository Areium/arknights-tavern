import { useState } from "react";
import { useAppStore } from "../stores/appStore";
import SessionList from "./SessionList";
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
  const [charBrowserOpen, setCharBrowserOpen] = useState(false);
  const [itemBrowserOpen, setItemBrowserOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className="flex h-full">
      {/* Left: sessions + panels */}
      <div className="w-72 border-r border-gray-700 overflow-y-auto p-3 space-y-3 shrink-0">
        <SessionList />
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

      {/* Right: chat */}
      <div className="flex-1 flex flex-col min-w-0">
        <ChatPanel />
      </div>

      {/* Right panel: 会话资源（可折叠） */}
      {resourcePanelOpen && <SessionResourcePanel />}

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
