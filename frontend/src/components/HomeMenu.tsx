/**
 * 游戏主页主菜单 — 居中栏目 + 背景 + BGM。
 *
 * 首次进入显示「点击进入」闸门（满足浏览器音频自动播放策略），
 * 点击后启动菜单 BGM 并展开菜单。菜单项进入各管理页面；
 * 「会话大厅」是进入故事与战斗的入口。
 *
 * 若存在被「临时返回」挂起的战斗，菜单最上方额外给出「继续战斗」入口
 * （战斗页离开时会落盘完整战斗态，这里一键恢复并回到战场）。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAppStore } from "../stores/appStore";
import { useApi } from "../hooks/useApi";
import { useCombatResume } from "../hooks/useCombatResume";
import { audioManager } from "../audio/audioManager";
import type { CombatResumesDTO } from "../types";

const asset = (p: string) => import.meta.env.BASE_URL + p;

type MenuView = "sessions" | "characters" | "worldbook" | "content" | "docs" | "settings";

interface MenuItem {
  id: MenuView;
  label: string;
  icon: string;
  desc: string;
  primary?: boolean;
}

const MENU_ITEMS: MenuItem[] = [
  { id: "sessions", label: "会话大厅", icon: "🏛️", desc: "进入故事与战斗", primary: true },
  { id: "characters", label: "角色管理", icon: "🎭", desc: "角色库 · 玩家身份 · 卡牌" },
  { id: "worldbook", label: "世界书", icon: "📖", desc: "关键词触发式设定注入" },
  { id: "content", label: "内容中心", icon: "🗂️", desc: "文档 · 索引 · 资产 · 卡牌" },
  { id: "docs", label: "文档", icon: "📘", desc: "帮助与设定文档" },
  { id: "settings", label: "设置", icon: "⚙️", desc: "LLM · 主题 · 叙述选项" },
];

/** 主页「继续战斗」入口的展示数据 */
interface ResumeEntry {
  /** `session:<id>` / `test:<id>`，与 hook 的 busyKey 对齐 */
  key: string;
  kind: "session" | "test";
  id: string;
  badge: string;
  desc: string;
  hint: string;
  /** 排序键：进行中的战斗（无挂起时间）排最前 */
  at: number;
}

export default function HomeMenu() {
  const { setCurrentView, sessions, backend, llmStatus } = useAppStore();
  const api = useApi();
  const { resumeSession, resumeTest, busyKey } = useCombatResume();
  // 本次运行内已点过「进入」则不再显示闸门（sessionStorage 记忆）
  const [entered, setEntered] = useState(() => {
    try { return sessionStorage.getItem("ark_menu_entered") === "1"; } catch { return false; }
  });
  const [muted, setMuted] = useState(audioManager.getSettings().muted);
  const [bgmVol, setBgmVol] = useState(audioManager.getSettings().bgmVolume);
  // 可恢复的战斗（挂起存档 + 仍在内存中的战斗）：后端是唯一真相
  const [resumes, setResumes] = useState<CombatResumesDTO | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.listCombatResumes()
      .then((res) => { if (!cancelled) setResumes(res); })
      .catch(() => { if (!cancelled) setResumes(null); });
    return () => { cancelled = true; };
  }, [api]);

  const resumeEntry = useMemo<ResumeEntry | null>(() => {
    if (!resumes) return null;
    const entries: ResumeEntry[] = [];
    for (const s of resumes.sessions || []) {
      const r = s.combat;
      const name = s.name || "未命名会话";
      entries.push({
        key: `session:${s.session_id}`,
        kind: "session",
        id: s.session_id,
        badge: r ? `第 ${r.round_num} 回合` : "进行中",
        desc: r
          ? `${name} · 存活 ${r.player_alive} · 手牌 ${r.hand_size}` +
            (r.pending_waves > 0 ? ` · 余 ${r.pending_waves} 波` : "")
          : `${name} · 战斗仍在进行（未挂起）`,
        hint: r
          ? `继续战斗：${r.encounter_id || "未知节点"} · 第 ${r.round_num} 回合（状态已保存）`
          : `回到 ${name} 的战场`,
        at: r?.suspended_at ?? Number.MAX_SAFE_INTEGER,
      });
    }
    for (const t of resumes.tests || []) {
      entries.push({
        key: `test:${t.test_id}`,
        kind: "test",
        id: t.test_id,
        badge: `第 ${t.round_num} 回合`,
        desc: `战斗演练（无会话） · ${t.encounter_id || "未知节点"} · 存活 ${t.player_alive}` +
          (t.pending_waves > 0 ? ` · 余 ${t.pending_waves} 波` : ""),
        hint: `继续战斗演练：${t.encounter_id || "未知节点"} · 第 ${t.round_num} 回合（状态已保存）`,
        at: t.suspended_at ?? 0,
      });
    }
    if (entries.length === 0) return null;
    entries.sort((a, b) => b.at - a.at);
    const top = entries[0];
    if (entries.length > 1) top.desc += ` · 另有 ${entries.length - 1} 场可继续（见会话大厅）`;
    return top;
  }, [resumes]);

  const handleResume = useCallback(() => {
    if (!resumeEntry) return;
    if (resumeEntry.kind === "test") void resumeTest(resumeEntry.id);
    else void resumeSession(resumeEntry.id);
  }, [resumeEntry, resumeSession, resumeTest]);

  const combatCount = useMemo(() => sessions.filter((s) => s.in_combat).length, [sessions]);

  const enter = () => {
    // 用户手势内启动音频（自动播放策略）
    try { sessionStorage.setItem("ark_menu_entered", "1"); } catch { /* ignore */ }
    audioManager.ensureCtx();
    audioManager.startMenuBgm();
    setEntered(true);
  };

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
    <div
      className="home-menu-root"
      style={{ backgroundImage: "url(" + asset("menu_bg.jpg") + ")" }}
    >
      {/* 氛围遮罩：暗角 + 顶部/底部压暗 */}
      <div className="home-menu-vignette" />

      {/* ═══ 点击进入闸门 ═══ */}
      {!entered && (
        <div className="home-splash" onClick={enter} role="button" aria-label="点击进入">
          <img src={asset("logo.png")} alt="logo" className="home-splash-logo" draggable={false} />
          <div className="home-splash-title font-display">ARKNIGHTS&nbsp;TAVERN</div>
          <div className="home-splash-press">— 点 击 进 入 —</div>
        </div>
      )}

      {/* ═══ 主菜单栏目 ═══ */}
      <div className={"home-menu-stage" + (entered ? " entered" : "") }>
        <div className="home-menu-column">
          {/* 标题 */}
          <div className="home-menu-head">
            <img src={asset("logo.png")} alt="logo" className="home-menu-logo" draggable={false} />
            <h1 className="home-menu-title font-display">ARKNIGHTS TAVERN</h1>
            <p className="home-menu-sub">明 日 方 舟 · 文 字 酒 馆</p>
            <div className="home-menu-divider"><span /></div>
          </div>

          {/* 菜单项 */}
          <nav className="home-menu-nav">
            {/* 挂起的战斗：置于最上方，一键续打（战斗态已落盘，恢复即重建战场） */}
            {resumeEntry && (
              <button
                onClick={handleResume}
                disabled={!!busyKey}
                className="home-menu-item"
                title={resumeEntry.hint}
              >
                <span className="home-menu-item-icon">⏸</span>
                <span className="home-menu-item-text">
                  <span className="home-menu-item-label">
                    {busyKey ? "正在恢复战斗…" : "继续战斗"}
                    <span className="home-menu-item-badge">{resumeEntry.badge}</span>
                  </span>
                  <span className="home-menu-item-desc">{resumeEntry.desc}</span>
                </span>
                <span className="home-menu-item-arrow">▶</span>
              </button>
            )}
            {MENU_ITEMS.map((item) => (
              <button
                key={item.id}
                onClick={() => setCurrentView(item.id)}
                className={"home-menu-item" + (item.primary ? " primary" : "")}
              >
                <span className="home-menu-item-icon">{item.icon}</span>
                <span className="home-menu-item-text">
                  <span className="home-menu-item-label">
                    {item.label}
                    {item.id === "sessions" && sessions.length > 0 && (
                      <span className="home-menu-item-badge">
                        {sessions.length} 个会话{combatCount > 0 ? " · ⚔" + combatCount + " 战斗中" : ""}
                      </span>
                    )}
                  </span>
                  <span className="home-menu-item-desc">{item.desc}</span>
                </span>
                <span className="home-menu-item-arrow">▶</span>
              </button>
            ))}
          </nav>
        </div>
      </div>

      {/* ═══ 底部状态条 ═══ */}
      <footer className="home-menu-footer">
        <span className="home-status">
          <i className={"dot " + (backend.status === "connected" ? "ok" : "bad")} />
          {backend.status === "connected" ? "后端已连接" : "后端未连接"}
        </span>
        <span className="home-status">
          <i className={"dot " + (llmStatus?.available ? "ok" : "bad")} />
          {llmStatus?.primary?.name ?? "LLM 未配置"}
        </span>
        <span className="home-menu-version">v0.1.0</span>
        <div className="home-audio-group">
          <button className="home-audio-btn" onClick={toggleMute} title={muted ? "取消静音（继续播放）" : "静音（暂停，再次点击继续）"}>
            {muted ? "🔇" : "🔊"}
          </button>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={bgmVol}
            onChange={(e) => changeBgmVol(parseFloat(e.target.value))}
            className="home-vol-slider"
            title={"BGM 音量 " + Math.round(bgmVol * 100) + "%"}
          />
        </div>
      </footer>
    </div>
  );
}
