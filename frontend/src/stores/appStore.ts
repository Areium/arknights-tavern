/**
 * 应用全局状态
 */
import { create } from "zustand";
import type { BackendStatus, Session, LLMStatus } from "../types";

interface AppState {
  // 视图
  currentView: "chat" | "documents" | "settings";
  setCurrentView: (view: "chat" | "documents" | "settings") => void;

  // 后端连接
  backend: BackendStatus;
  llmStatus: LLMStatus | null;
  setBackendStatus: (status: BackendStatus) => void;
  setLLMStatus: (status: LLMStatus) => void;

  // 当前对话模式
  chatMode: "free" | "story";
  setChatMode: (mode: "free" | "story") => void;

  // 会话列表
  sessions: Session[];
  activeSessionId: string | null;
  setSessions: (sessions: Session[]) => void;
  setActiveSession: (id: string | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  // 视图
  currentView: "chat",
  setCurrentView: (view) => set({ currentView: view }),

  // 后端
  backend: { status: "connecting", url: "" },
  llmStatus: null,
  setBackendStatus: (status) => set({ backend: status }),
  setLLMStatus: (status) => set({ llmStatus: status }),

  // 对话模式
  chatMode: "free",
  setChatMode: (mode) => set({ chatMode: mode }),

  // 会话
  sessions: [],
  activeSessionId: null,
  setSessions: (sessions) => set({ sessions }),
  setActiveSession: (id) => set({ activeSessionId: id }),
}));
