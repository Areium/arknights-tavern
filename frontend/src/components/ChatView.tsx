import { useState } from "react";
import SessionList from "./SessionList";
import CharacterPanel from "./CharacterPanel";
import EnvironmentPanel from "./EnvironmentPanel";
import ChatPanel from "./ChatPanel";
import CharacterBrowser from "./CharacterBrowser";

export default function ChatView() {
  const [browserOpen, setBrowserOpen] = useState(false);

  return (
    <div className="flex h-full">
      {/* Left: sessions + panels */}
      <div className="w-72 border-r border-gray-700 overflow-y-auto p-3 space-y-3 shrink-0">
        <SessionList />
        <CharacterPanel onAddClick={() => setBrowserOpen(true)} />
        <EnvironmentPanel />
      </div>

      {/* Right: chat */}
      <div className="flex-1 flex flex-col min-w-0">
        <ChatPanel />
      </div>

      {/* Character browser modal */}
      <CharacterBrowser
        open={browserOpen}
        onClose={() => setBrowserOpen(false)}
      />
    </div>
  );
}
