import { useState } from "react";
import SessionList from "./SessionList";
import CharacterPanel from "./CharacterPanel";
import ItemPanel from "./ItemPanel";
import EnvironmentPanel from "./EnvironmentPanel";
import ChatPanel from "./ChatPanel";
import CharacterBrowser from "./CharacterBrowser";
import ItemBrowser from "./ItemBrowser";

export default function ChatView() {
  const [charBrowserOpen, setCharBrowserOpen] = useState(false);
  const [itemBrowserOpen, setItemBrowserOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className="flex h-full">
      {/* Left: sessions + panels */}
      <div className="w-72 border-r border-gray-700 overflow-y-auto p-3 space-y-3 shrink-0">
        <SessionList />
        <CharacterPanel
          key={refreshKey}
          onAddClick={() => setCharBrowserOpen(true)}
        />
        <ItemPanel
          key={`items-${refreshKey}`}
          onAddClick={() => setItemBrowserOpen(true)}
        />
        <EnvironmentPanel />
      </div>

      {/* Right: chat */}
      <div className="flex-1 flex flex-col min-w-0">
        <ChatPanel />
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
