import { useEffect } from "react";
import { useAppStore } from "./stores/appStore";
import { useApi } from "./hooks/useApi";
import Sidebar from "./components/Sidebar";
import StatusBar from "./components/StatusBar";
import ChatView from "./components/ChatView";
import DocumentManager from "./components/DocumentManager";
import SettingsPanel from "./components/SettingsPanel";

export default function App() {
  const { currentView, setBackendStatus, setLLMStatus, setSessions } =
    useAppStore();
  const api = useApi();

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
