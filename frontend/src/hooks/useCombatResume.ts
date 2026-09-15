/**
 * 「继续战斗」—— 恢复被挂起的战斗并进入战场。
 *
 * 战斗页的「临时返回」把完整战斗态落盘后释放内存（见 `src/combat_resume.py`），
 * 恢复必须走 `POST .../combat/resume` 重建引擎，不能只切视图——否则战场是空的。
 * 主页 / 会话大厅 / 对话页顶栏三处入口共用本 hook，避免各自重写
 * 「选中会话 → 设上下文 → 切视图」的顺序（顺序错了会出现空战场）。
 */
import { useCallback, useState } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "./useApi";

export interface CombatResumeApi {
  /** 恢复会话战并进入战场；成功返回 true */
  resumeSession: (sessionId: string) => Promise<boolean>;
  /** 恢复战斗测试（无会话）并进入战场；成功返回 true */
  resumeTest: (testId: string) => Promise<boolean>;
  /** 正在恢复的目标键（`session:<id>` / `test:<id>`），用于按钮 loading 态 */
  busyKey: string | null;
}

export function useCombatResume(): CombatResumeApi {
  const {
    sessions,
    setSessions,
    setActiveSession,
    setChatMode,
    setCombatContext,
    setCurrentView,
  } = useAppStore();
  const api = useApi();
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const resumeSession = useCallback(
    async (sessionId: string) => {
      setBusyKey(`session:${sessionId}`);
      try {
        const resp = await api.combatResume(sessionId);
        const s = sessions.find((x) => x.id === sessionId);
        setActiveSession(sessionId);
        if (s) setChatMode(s.mode);
        setCombatContext({
          sessionId,
          testId: null,
          state: resp.state ?? null,
          uiMode: "VIEWING",
          selectedCardIndex: null,
          selectedUnitId: null,
        });
        // 恢复后战斗回到内存：立刻把列表徽标切回「战斗中」，不必等 15s 轮询
        setSessions(
          sessions.map((x) =>
            x.id === sessionId
              ? { ...x, in_combat: true, combat_resumable: true, combat_resume: null }
              : x,
          ),
        );
        setCurrentView("combat");
        return true;
      } catch (e: any) {
        alert("继续战斗失败：" + (e?.message || "未知错误"));
        return false;
      } finally {
        setBusyKey(null);
      }
    },
    [api, sessions, setSessions, setActiveSession, setChatMode, setCombatContext, setCurrentView],
  );

  const resumeTest = useCallback(
    async (testId: string) => {
      setBusyKey(`test:${testId}`);
      try {
        const resp = await api.combatTestResume(testId);
        setCombatContext({
          sessionId: null,
          testId,
          state: resp.state ?? null,
          uiMode: "VIEWING",
          selectedCardIndex: null,
          selectedUnitId: null,
        });
        setCurrentView("combat");
        return true;
      } catch (e: any) {
        alert("继续战斗失败：" + (e?.message || "未知错误"));
        return false;
      } finally {
        setBusyKey(null);
      }
    },
    [api, setCombatContext, setCurrentView],
  );

  return { resumeSession, resumeTest, busyKey };
}
