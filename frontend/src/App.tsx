import { useEffect } from "react";
import { useAppStore } from "./stores/appStore";
import { useApi } from "./hooks/useApi";
import Sidebar from "./components/Sidebar";
import StatusBar from "./components/StatusBar";
import ChatView from "./components/ChatView";
import DocumentManager from "./components/DocumentManager";
import SettingsPanel from "./components/SettingsPanel";

export default function App() {
  const { currentView, setBackendStatus, setLLMStatus, setSessions, theme, setTheme, setEditBeforeSend } =
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

  // Poll backend status
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const status = await api.getStatus();
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

  const renderView = () => {
    switch (currentView) {
      case "chat":
        return <ChatView />;
      case "documents":
        return <DocumentManager />;
      case "settings":
        return <SettingsPanel />;
    }
  };

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden">
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-auto">{renderView()}</main>
      </div>
      <StatusBar />
    </div>
  );
}
