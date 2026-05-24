/**
 * 应用全局状态
 */
import { create } from "zustand";
import type { BackendStatus, Session, LLMStatus, CombatStateDTO } from "../types";

type Theme = "dark" | "light";

interface AppState {
  // 视图
  currentView: "chat" | "documents" | "settings" | "combat" | "index";
  setCurrentView: (view: "chat" | "documents" | "settings" | "combat" | "index") => void;

  // 主题
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;

  // 后端连接
  backend: BackendStatus;
  llmStatus: LLMStatus | null;
  setBackendStatus: (status: BackendStatus) => void;
  setLLMStatus: (status: LLMStatus) => void;

  // 当前对话模式
  chatMode: "free" | "story";
  setChatMode: (mode: "free" | "story") => void;

  // 会话
  sessions: Session[];
  activeSessionId: string | null;
  setSessions: (sessions: Session[]) => void;
  setActiveSession: (id: string | null) => void;

  // 环境刷新触发器（SSE scene_event / 手动切换后 +1）
  envRefreshKey: number;
  triggerEnvRefresh: () => void;

  // 回忆刷新触发器（SSE memory_event / 手动切换后 +1）
  memoryRefreshKey: number;
  triggerMemoryRefresh: () => void;

  // 聊天刷新触发器（回退后 +1，通知 ChatPanel 重新加载）
  chatRefreshKey: number;
  triggerChatRefresh: () => void;

  // 发送前编辑模式：点击选项后填入输入框而非直接发送
  editBeforeSend: boolean;
  setEditBeforeSend: (v: boolean) => void;

  // 场景切换触发器（剧情模式切换场景后 +1，通知 ChatPanel 触发叙述）
  sceneSwitchKey: number;
  triggerSceneSwitch: () => void;

  // 索引管理跳转（从会话列表跳转到索引管理器并选中指定会话）
  indexSessionId: string | null;
  setIndexSessionId: (id: string | null) => void;

  // 战斗
  combatState: CombatStateDTO | null;
  setCombatState: (state: CombatStateDTO | null) => void;
  combatUIMode: "VIEWING" | "TARGETING" | "MOVING";
  setCombatUIMode: (mode: "VIEWING" | "TARGETING" | "MOVING") => void;
  selectedCardIndex: number | null;
  setSelectedCardIndex: (index: number | null) => void;
  combatTestId: string | null;
  setCombatTestId: (id: string | null) => void;
  selectedUnitId: string | null;
  setSelectedUnitId: (id: string | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  // 视图
  currentView: "chat",
  setCurrentView: (view) => set({ currentView: view }),

  // 主题
  theme: "dark",
  setTheme: (theme) => set({ theme }),
  toggleTheme: () => set((state) => ({ theme: state.theme === "dark" ? "light" : "dark" })),

  // 后端
  backend: { status: "connecting", url: "" },
  llmStatus: null,
  setBackendStatus: (status) => set((state) => {
    if (state.backend.status === status.status && state.backend.url === status.url) return {};
    return { backend: status };
  }),
  setLLMStatus: (status) => set({ llmStatus: status }),

  // 对话模式
  chatMode: "story",
  setChatMode: (mode) => set({ chatMode: mode }),

  // 会话
  sessions: [],
  activeSessionId: null,
  setSessions: (sessions) => set({ sessions }),
  setActiveSession: (id) => set({ activeSessionId: id }),

  // 环境刷新触发器
  envRefreshKey: 0,
  triggerEnvRefresh: () => set((state) => ({ envRefreshKey: state.envRefreshKey + 1 })),

  // 回忆刷新触发器
  memoryRefreshKey: 0,
  triggerMemoryRefresh: () => set((state) => ({ memoryRefreshKey: state.memoryRefreshKey + 1 })),

  // 聊天刷新触发器
  chatRefreshKey: 0,
  triggerChatRefresh: () => set((state) => ({ chatRefreshKey: state.chatRefreshKey + 1 })),

  // 发送前编辑模式
  editBeforeSend: false,
  setEditBeforeSend: (v) => set({ editBeforeSend: v }),

  // 场景切换触发器
  sceneSwitchKey: 0,
  triggerSceneSwitch: () => set((state) => ({ sceneSwitchKey: state.sceneSwitchKey + 1 })),

  // 索引管理跳转
  indexSessionId: null,
  setIndexSessionId: (id) => set({ indexSessionId: id }),

  // 战斗
  combatState: null,
  setCombatState: (state) => set({ combatState: state }),
  combatUIMode: "VIEWING",
  setCombatUIMode: (mode) => set({ combatUIMode: mode }),
  selectedCardIndex: null,
  setSelectedCardIndex: (index) => set({ selectedCardIndex: index }),
  combatTestId: null,
  setCombatTestId: (id) => set({ combatTestId: id }),
  selectedUnitId: null,
  setSelectedUnitId: (id) => set({ selectedUnitId: id }),
}));
