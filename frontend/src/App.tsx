import { useEffect } from "react";
import { useAppStore } from "./stores/appStore";
import { useApi } from "./hooks/useApi";
import { audioManager } from "./audio/audioManager";
import HomeMenu from "./components/HomeMenu";
import GameTopBar from "./components/GameTopBar";
import StatusBar from "./components/StatusBar";
import ChatView from "./components/ChatView";
import SessionManagerView from "./components/session/SessionManagerView";
import CombatView from "./components/combat/CombatView";
import DocumentManager from "./components/DocumentManager";
import SettingsPanel from "./components/SettingsPanel";
import IndexManager from "./components/IndexManager";
import WorldBookManager from "./components/WorldBookManager";
import ContentHub from "./components/ContentHub";
import DocsView from "./components/DocsView";
import CharacterManager from "./components/CharacterManager";

/** 沉浸式视图：全屏无顶栏（对话 = 故事沉浸，战斗 = 战场沉浸） */
const IMMERSIVE_VIEWS = new Set(["chat", "combat"]);
/** 菜单氛围视图：播放主菜单 BGM（战斗 BGM 由 CombatView 自管，对话页静默沉浸） */
const MENU_BGM_VIEWS = new Set(["home", "sessions", "content", "docs", "settings"]);

export default function App() {
  const { currentView, setBackendStatus, setLLMStatus, setSessions, theme, setTheme, setEditBeforeSend, setDialogueBubbleMode } =
    useAppStore();
  const api = useApi();

  // 启动时从配置文件加载主题设置
  useEffect(() => {
    const initConfig = async () => {
      try {
        const config = await api.getLLMConfig();
        if (config.theme === "light" || config.theme === "dark") {
          setTheme(config.theme);
        }
        if (typeof config.edit_before_send === "boolean") {
          setEditBeforeSend(config.edit_before_send);
        }
        if (typeof config.dialogue_bubble_mode === "boolean") {
          setDialogueBubbleMode(config.dialogue_bubble_mode);
        }
      } catch {
        // 后端不可用时使用默认深色主题
      }
    };
    initConfig();
  }, []); // 仅启动时执行一次

  // 应用主题 class 到 <html>
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "light") {
      root.classList.add("light");
    } else {
      root.classList.remove("light");
    }
  }, [theme]);

  // BGM 编排：菜单类页面播主菜单 BGM；进入对话（沉浸故事）时静默；战斗 BGM 由 CombatView 接管
  useEffect(() => {
    if (MENU_BGM_VIEWS.has(currentView)) {
      audioManager.startMenuBgm();
    } else if (currentView === "chat") {
      audioManager.stopBgm();
    }
  }, [currentView]);

  // Poll backend status
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        await api.getStatus();
        if (!cancelled) {
          setBackendStatus({ status: "connected", url: "" });
        }
      } catch {
        if (!cancelled) {
          setBackendStatus({ status: "disconnected", url: "" });
        }
      }
    };
    poll();
    const timer = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [api, setBackendStatus]);

  // Poll LLM status
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const status = await api.getLLMStatus();
        if (!cancelled) setLLMStatus(status);
      } catch {
        /* ignore */
      }
    };
    poll();
    const timer = setInterval(poll, 10000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [api, setLLMStatus]);

  // Load sessions
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const sessions = await api.listSessions();
        if (!cancelled) setSessions(sessions);
      } catch {
        /* ignore */
      }
    };
    load();
    const timer = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [api, setSessions]);

  const renderManageView = () => {
    switch (currentView) {
      case "sessions":
        return <SessionManagerView />;
      case "documents":
        return <DocumentManager />;
      case "settings":
        return <SettingsPanel />;
      case "index":
        return <IndexManager />;
      case "worldbook":
        return <WorldBookManager />;
      case "characters":
        return <CharacterManager />;
      case "content":
        return <ContentHub />;
      case "docs":
        return <DocsView />;
      default:
        return null;
    }
  };

  const immersive = IMMERSIVE_VIEWS.has(currentView);

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden">
      {/* 主页：游戏主菜单（全屏居中栏目 + 背景 + BGM） */}
      {currentView === "home" && <HomeMenu />}

      {/* 管理页顶栏（取代旧 sidebar 导航） */}
      {currentView !== "home" && !immersive && <GameTopBar />}

      <main className="flex-1 overflow-hidden min-h-0">
        {/* ChatView 始终挂载以保留 SSE 流（导航时不中断叙述） */}
        <div style={{ display: currentView === "chat" ? undefined : "none", height: "100%" }}>
          <ChatView />
        </div>
        {currentView === "combat" && <CombatView />}
        {currentView !== "home" && !immersive && (
          <div className="h-full overflow-auto">{renderManageView()}</div>
        )}
      </main>

      {/* 状态栏：仅管理页显示（主页有自带状态，沉浸式页面隐藏） */}
      {currentView !== "home" && !immersive && <StatusBar />}
    </div>
  );
}
