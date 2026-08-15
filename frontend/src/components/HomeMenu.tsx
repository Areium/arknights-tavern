/**
 * 游戏主页主菜单 — 居中栏目 + 背景 + BGM。
 *
 * 首次进入显示「点击进入」闸门（满足浏览器音频自动播放策略），
 * 点击后启动菜单 BGM 并展开菜单。菜单项进入各管理页面；
 * 「会话大厅」是进入故事与战斗的入口。
 */
import { useMemo, useState } from "react";
import { useAppStore } from "../stores/appStore";
import { audioManager } from "../audio/audioManager";

const asset = (p: string) => import.meta.env.BASE_URL + p;

type MenuView = "sessions" | "content" | "docs" | "settings";

interface MenuItem {
  id: MenuView;
  label: string;
  icon: string;
  desc: string;
  primary?: boolean;
}

const MENU_ITEMS: MenuItem[] = [
  { id: "sessions", label: "会话大厅", icon: "🏛️", desc: "进入故事与战斗", primary: true },
  { id: "content", label: "内容中心", icon: "🗂️", desc: "文档 · 世界书 · 索引 · 资产 · 卡牌" },
  { id: "docs", label: "文档", icon: "📘", desc: "帮助与设定文档" },
  { id: "settings", label: "设置", icon: "⚙️", desc: "LLM · 主题 · 叙述选项" },
];

export default function HomeMenu() {
  const { setCurrentView, sessions, backend, llmStatus } = useAppStore();
  // 本次运行内已点过「进入」则不再显示闸门（sessionStorage 记忆）
  const [entered, setEntered] = useState(() => {
    try { return sessionStorage.getItem("ark_menu_entered") === "1"; } catch { return false; }
  });
  const [muted, setMuted] = useState(audioManager.getSettings().muted);
  const [bgmVol, setBgmVol] = useState(audioManager.getSettings().bgmVolume);

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
