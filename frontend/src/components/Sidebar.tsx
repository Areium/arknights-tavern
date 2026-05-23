import { useAppStore } from "../stores/appStore";

const NAV_ITEMS = [
  { id: "chat" as const, label: "对话", icon: "💬" },
  { id: "documents" as const, label: "资产", icon: "📄" },
  { id: "settings" as const, label: "设置", icon: "⚙️" },
];

export default function Sidebar() {
  const { currentView, setCurrentView, chatMode, setChatMode } =
    useAppStore();

  return (
    <aside className="w-56 bg-gray-850 border-r border-gray-700 flex flex-col shrink-0">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-gray-700">
        <h1 className="text-lg font-bold text-amber-400">Arknights TXT</h1>
        <p className="text-xs text-gray-500 mt-0.5">文字角色扮演</p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-4 space-y-1">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            onClick={() => setCurrentView(item.id)}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
              currentView === item.id
                ? "bg-blue-600/20 text-blue-300 font-medium"
                : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/50"
            }`}
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      {/* Mode switch (only in chat view) */}
      {currentView === "chat" && (
        <div className="px-3 py-3 border-t border-gray-700">
          <p className="panel-title">对话模式</p>
          <div className="flex gap-2">
            <button
              onClick={() => setChatMode("story")}
              className={`flex-1 px-2 py-1.5 text-xs rounded-md transition-colors ${
                chatMode === "story"
                  ? "bg-amber-600 text-white"
                  : "bg-gray-700 text-gray-400 hover:text-gray-200"
              }`}
            >
              剧情
            </button>
            <button
              onClick={() => setChatMode("free")}
              className={`flex-1 px-2 py-1.5 text-xs rounded-md transition-colors ${
                chatMode === "free"
                  ? "bg-purple-600 text-white"
                  : "bg-gray-700 text-gray-400 hover:text-gray-200"
              }`}
            >
              自由
            </button>
          </div>
        </div>
      )}

      {/* Version */}
      <div className="px-4 py-2 text-xs text-gray-600 border-t border-gray-700">
        v0.1.0
      </div>
    </aside>
  );
}
