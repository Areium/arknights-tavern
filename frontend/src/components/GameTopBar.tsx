/**
 * 管理页面顶栏 — 取代原 sidebar：返回主菜单 + 管理页导航 + 音频开关。
 * 仅在非沉浸式页面（会话大厅/资产/世界书/索引/文档/设置）显示。
 */
import { useState } from "react";
import { useAppStore } from "../stores/appStore";
import { audioManager } from "../audio/audioManager";

type ManageView = "sessions" | "documents" | "worldbook" | "index" | "docs" | "settings";

const NAV_ITEMS: { id: ManageView; label: string; icon: string }[] = [
  { id: "sessions", label: "会话大厅", icon: "🏛️" },
  { id: "documents", label: "资产", icon: "📄" },
  { id: "worldbook", label: "世界书", icon: "📖" },
  { id: "index", label: "索引", icon: "🔗" },
  { id: "docs", label: "文档", icon: "📘" },
  { id: "settings", label: "设置", icon: "⚙️" },
];

export default function GameTopBar() {
  const { currentView, setCurrentView } = useAppStore();
  const [muted, setMuted] = useState(audioManager.getSettings().muted);
  const [bgmVol, setBgmVol] = useState(audioManager.getSettings().bgmVolume);

  const toggleMute = () => {
    const m = !muted;
    setMuted(m);
    audioManager.setMuted(m);
    if (!m) audioManager.resumeMenuBgmAfterUnmute();
  };

  const changeBgmVol = (v: number) => {
    setBgmVol(v);
    audioManager.setBgmVolume(v);
  };

  return (
    <header className="h-11 shrink-0 flex items-center gap-2 px-3 border-b border-gray-700/70 bg-gray-900/95 backdrop-blur-sm z-30">
      {/* 返回主菜单 */}
      <button
        onClick={() => setCurrentView("home")}
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs text-gray-400 hover:text-amber-300 hover:bg-amber-500/10 transition-colors"
        title="返回主菜单"
      >
        <span>◀</span>
        <span>主菜单</span>
      </button>

      <div className="w-px h-5 bg-gray-700/70 mx-1" />

      {/* 管理页导航 */}
      <nav className="flex items-center gap-1 overflow-x-auto">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            onClick={() => setCurrentView(item.id)}
            className={
              "flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs whitespace-nowrap transition-colors " +
              (currentView === item.id
                ? "bg-amber-600/20 text-amber-300 font-medium border border-amber-500/30"
                : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/50 border border-transparent")
            }
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="flex-1" />

      {/* 音频：静音（暂停/继续）+ BGM 音量 */}
      <div className="flex items-center gap-1.5">
        <button
          onClick={toggleMute}
          className="px-2 py-1.5 rounded-lg text-xs text-gray-400 hover:text-gray-200 hover:bg-gray-700/50 transition-colors"
          title={muted ? "取消静音（继续播放）" : "静音（暂停，再次点击继续）"}
        >
          {muted ? "🔇" : "🔊"}
        </button>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={bgmVol}
          onChange={(e) => changeBgmVol(parseFloat(e.target.value))}
          className="w-20 h-1.5 accent-amber-500 cursor-pointer"
          title={"BGM 音量 " + Math.round(bgmVol * 100) + "%"}
        />
      </div>
    </header>
  );
}
