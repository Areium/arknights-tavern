/**
 * 应用全局状态
 */
import { create } from "zustand";
import type { BackendStatus, Session, LLMStatus, CombatStateDTO, ChatMessage } from "../types";

type Theme = "dark" | "light";

export interface CombatContext {
  state: CombatStateDTO | null;
  uiMode: "VIEWING" | "TARGETING";
  selectedCardIndex: number | null;
  testId: string | null;
  sessionId: string | null;
  selectedUnitId: string | null;
}

interface AppState {
  // 视图
  currentView: "chat" | "sessions" | "documents" | "settings" | "combat" | "index" | "worldbook" | "docs";
  setCurrentView: (view: "chat" | "sessions" | "documents" | "settings" | "combat" | "index" | "worldbook" | "docs") => void;

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

  // 对话气泡模式：将角色对话以聊天气泡形式显示
  dialogueBubbleMode: boolean;
  setDialogueBubbleMode: (v: boolean) => void;

  // 角色变更触发器（加载/卸载角色后 +1）
  characterRefreshKey: number;
  triggerCharacterRefresh: () => void;

  // 场景切换触发器（剧情模式切换场景后 +1，通知 ChatPanel 触发叙述）
  sceneSwitchKey: number;
  triggerSceneSwitch: () => void;

  // 索引管理跳转（从会话列表跳转到索引管理器并选中指定会话）
  indexSessionId: string | null;
  setIndexSessionId: (id: string | null) => void;

  // 会话资源面板（右侧可折叠）
  resourcePanelOpen: boolean;
  setResourcePanelOpen: (open: boolean) => void;
  // 会话覆盖图缓存爆破（上传/删除覆盖后 +1，通知头像等刷新）
  resourceVersion: number;
  bumpResourceVersion: () => void;

  // 战斗
  combatContext: CombatContext;
  setCombatContext: (partial: Partial<CombatContext> | null) => void;

  // 战斗后自动叙述
  pendingAutoNarrate: { action: string; settlement?: { winner: string; survivors: string[]; rounds: number; encounter_id: string } } | null;
  setPendingAutoNarrate: (data: { action: string; settlement?: { winner: string; survivors: string[]; rounds: number; encounter_id: string } } | null) => void;

  // 按会话存储的消息/流式状态（跨会话切换保留）
  sessionMessages: Record<string, ChatMessage[]>;
  sessionStreaming: Record<string, boolean>;
  sessionSending: Record<string, boolean>;
  sessionNarrationCount: Record<string, number>;
  sessionAbortFns: Record<string, (() => void) | null>;

  setSessionMessages: (sessionId: string, updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) => void;
  setSessionStreaming: (sessionId: string, streaming: boolean) => void;
  setSessionSending: (sessionId: string, sending: boolean) => void;
  setSessionNarrationCount: (sessionId: string, count: number) => void;
  setSessionAbortFn: (sessionId: string, fn: (() => void) | null) => void;
  clearSessionStream: (sessionId: string) => void;
}

export const useAppStore = create<AppState>((set, get) => ({
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

  // 对话气泡模式
  dialogueBubbleMode: false,
  setDialogueBubbleMode: (v) => set({ dialogueBubbleMode: v }),

  // 角色变更触发器
  characterRefreshKey: 0,
  triggerCharacterRefresh: () => set((state) => ({ characterRefreshKey: state.characterRefreshKey + 1 })),

  // 场景切换触发器
  sceneSwitchKey: 0,
  triggerSceneSwitch: () => set((state) => ({ sceneSwitchKey: state.sceneSwitchKey + 1 })),

  // 索引管理跳转
  indexSessionId: null,
  setIndexSessionId: (id) => set({ indexSessionId: id }),

  // 会话资源面板
  resourcePanelOpen: false,
  setResourcePanelOpen: (open) => set({ resourcePanelOpen: open }),
  resourceVersion: 0,
  bumpResourceVersion: () => set((state) => ({ resourceVersion: state.resourceVersion + 1 })),

  // 战斗
  combatContext: {
    state: null,
    uiMode: "VIEWING" as const,
    selectedCardIndex: null,
    testId: null,
    sessionId: null,
    selectedUnitId: null,
  },
  setCombatContext: (partial) => set((s) => {
    if (partial === null) {
      return {
        combatContext: {
          state: null,
          uiMode: "VIEWING",
          selectedCardIndex: null,
          testId: null,
          sessionId: null,
          selectedUnitId: null,
        },
      };
    }
    return { combatContext: { ...s.combatContext, ...partial } };
  }),

  // 战斗后自动叙述
  pendingAutoNarrate: null,
  setPendingAutoNarrate: (action) => set({ pendingAutoNarrate: action }),

  // ── 按会话存储的消息/流式状态 ──
  sessionMessages: {},
  sessionStreaming: {},
  sessionSending: {},
  sessionNarrationCount: {},
  sessionAbortFns: {},

  setSessionMessages: (sessionId, updater) => set((state) => ({
    sessionMessages: {
      ...state.sessionMessages,
      [sessionId]: typeof updater === "function"
        ? (updater as (prev: ChatMessage[]) => ChatMessage[])(state.sessionMessages[sessionId] || [])
        : updater,
    },
  })),
  setSessionStreaming: (sessionId, streaming) => set((state) => ({
    sessionStreaming: { ...state.sessionStreaming, [sessionId]: streaming },
  })),
  setSessionSending: (sessionId, sending) => set((state) => ({
    sessionSending: { ...state.sessionSending, [sessionId]: sending },
  })),
  setSessionNarrationCount: (sessionId, count) => set((state) => ({
    sessionNarrationCount: { ...state.sessionNarrationCount, [sessionId]: count },
  })),
  setSessionAbortFn: (sessionId, fn) => set((state) => ({
    sessionAbortFns: { ...state.sessionAbortFns, [sessionId]: fn },
  })),
  clearSessionStream: (sessionId) => {
    get().sessionAbortFns[sessionId]?.();
    set(({ sessionMessages, sessionStreaming, sessionSending, sessionNarrationCount, sessionAbortFns }) => {
      const { [sessionId]: _, ...restMessages } = sessionMessages;
      const { [sessionId]: __, ...restStreaming } = sessionStreaming;
      const { [sessionId]: ___, ...restSending } = sessionSending;
      const { [sessionId]: ____, ...restNarration } = sessionNarrationCount;
      const { [sessionId]: _____, ...restAbort } = sessionAbortFns;
      return {
        sessionMessages: restMessages,
        sessionStreaming: restStreaming,
        sessionSending: restSending,
        sessionNarrationCount: restNarration,
        sessionAbortFns: restAbort,
      };
    });
  },
}));
