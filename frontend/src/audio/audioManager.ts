/**
 * 战斗音频管理单例 — SFX（文件优先 + WebAudio 合成兜底）+ BGM（intro→loop）。
 *
 * 设计：
 * - SFX：优先 fetch `/api/assets/audio/sfx/<name>.wav` 用 AudioContext 播；
 *   404/解码失败记入 missingSfx，之后直接合成不再请求。
 *   AudioBuffer 缓存避免 AOE 多目标命中重复网络请求；同 name 80ms 节流防叠爆。
 * - BGM：`<audio>` 先播 intro，ended 后切 loop 循环；文件缺失静默。
 * - 设置（音量/静音）持久化到 localStorage["ark_audio_settings"]。
 */
import { getBaseUrl } from "../utils/baseUrl";

export type SfxName =
  | "hit" | "hit_physical" | "hit_arts" | "hit_mixed" | "hit_ranged"
  | "crit" | "miss" | "heal" | "shield"
  | "death" | "enemy_death" | "card" | "ui" | "victory" | "defeat";

interface AudioSettings {
  sfxVolume: number;
  bgmVolume: number;
  muted: boolean;
  /** 窗口失焦时静音 BGM（默认开启） */
  bgmMuteOnBlur: boolean;
}

const STORAGE_KEY = "ark_audio_settings";
const THROTTLE_MS = 80;

class AudioManager {
  private ctx: AudioContext | null = null;
  private bufferCache = new Map<string, AudioBuffer>();
  private missingSfx = new Set<string>();
  private lastPlayed = new Map<string, number>();
  private bgmIntro: HTMLAudioElement | null = null;
  private bgmLoop: HTMLAudioElement | null = null;
  /** BGM 播放阶段：idle=未播 / intro=序曲 / loop=循环 */
  private bgmPhase: "idle" | "intro" | "loop" = "idle";
  /** 当前 BGM 轨道：combat=战斗 / menu=主菜单（避免同轨道重复启动） */
  private bgmTrack: "combat" | "menu" | null = null;
  private settings: AudioSettings;

  constructor() {
    this.settings = this.loadSettings();
    this.initBlurHandling();
  }

  /** 窗口失焦时暂停 BGM、聚焦恢复（受 bgmMuteOnBlur 开关控制） */
  private initBlurHandling() {
    if (typeof window === "undefined") return;
    window.addEventListener("blur", () => {
      if (this.settings.bgmMuteOnBlur) this.pauseBgm();
    });
    window.addEventListener("focus", () => {
      if (this.settings.bgmMuteOnBlur) this.resumeBgm();
    });
  }

  // ── 设置持久化 ──

  private loadSettings(): AudioSettings {
    const defaults: AudioSettings = { sfxVolume: 0.8, bgmVolume: 0.5, muted: false, bgmMuteOnBlur: true };
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) return { ...defaults, ...JSON.parse(raw) };
    } catch { /* ignore */ }
    return defaults;
  }

  private saveSettings() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(this.settings)); } catch { /* ignore */ }
  }

  getSettings(): AudioSettings { return { ...this.settings }; }

  setSfxVolume(v: number) { this.settings.sfxVolume = Math.max(0, Math.min(1, v)); this.saveSettings(); }
  setBgmVolume(v: number) {
    this.settings.bgmVolume = Math.max(0, Math.min(1, v));
    this.saveSettings();
    if (this.bgmIntro) this.bgmIntro.volume = v;
    if (this.bgmLoop) this.bgmLoop.volume = v;
  }
  setMuted(m: boolean) {
    this.settings.muted = m;
    this.saveSettings();
    if (m) {
      this.stopBgm();
      if (this.ctx && this.ctx.state === "running") this.ctx.suspend();
    } else {
      this.ensureCtx();
    }
  }
  setBgmMuteOnBlur(v: boolean) {
    this.settings.bgmMuteOnBlur = v;
    this.saveSettings();
  }

  // ── AudioContext ──

  /** 首次用户手势创建/恢复 AudioContext（自动播放策略要求） */
  ensureCtx(): AudioContext | null {
    if (this.settings.muted) return null;
    if (!this.ctx) {
      const AC = window.AudioContext || (window as any).webkitAudioContext;
      if (!AC) return null;
      this.ctx = new AC();
    }
    if (this.ctx.state === "suspended") void this.ctx.resume();
    return this.ctx;
  }

  // ── SFX ──

  playSfx(name: SfxName, vol = 1) {
    if (this.settings.muted) return;
    const now = performance.now();
    const last = this.lastPlayed.get(name) ?? 0;
    if (now - last < THROTTLE_MS) return;
    this.lastPlayed.set(name, now);

    const ctx = this.ensureCtx();
    if (!ctx) return;
    void this.loadBuffer(name).then((buf) => {
      if (buf) {
        const src = ctx.createBufferSource();
        src.buffer = buf;
        const g = ctx.createGain();
        g.gain.value = this.settings.sfxVolume * vol;
        src.connect(g).connect(ctx.destination);
        src.start();
      } else {
        this.synthSfx(name, ctx, vol);
      }
    });
  }

  private async loadBuffer(name: string): Promise<AudioBuffer | null> {
    if (this.bufferCache.has(name)) return this.bufferCache.get(name)!;
    if (this.missingSfx.has(name)) return null;
    // 命中/暴击/治疗为 mp3（player/ 战斗音效），其余为 wav
    const ext = /^(hit|hit_|crit|heal)/.test(name) ? "mp3" : "wav";
    try {
      const base = await getBaseUrl();
      const res = await fetch(`${base}/api/assets/audio/sfx/${name}.${ext}`);
      if (!res.ok) { this.missingSfx.add(name); return null; }
      const arr = await res.arrayBuffer();
      const buf = await this.ctx!.decodeAudioData(arr);
      this.bufferCache.set(name, buf);
      return buf;
    } catch {
      this.missingSfx.add(name);
      return null;
    }
  }

  // ── WebAudio 合成兜底（无文件时） ──

  private synthSfx(name: SfxName, ctx: AudioContext, vol: number) {
    const t = ctx.currentTime;
    const v = this.settings.sfxVolume * vol;
    // 细分命中音效（hit_physical/arts/mixed/ranged）合成兜底时归一到 hit
    if (name.startsWith("hit_")) name = "hit";

    const noise = (dur: number) => {
      const buf = ctx.createBuffer(1, Math.floor(ctx.sampleRate * dur), ctx.sampleRate);
      const d = buf.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
      const s = ctx.createBufferSource();
      s.buffer = buf;
      return s;
    };
    const osc = (type: OscillatorType, f0: number, f1: number, dur: number) => {
      const o = ctx.createOscillator();
      o.type = type;
      o.frequency.setValueAtTime(f0, t);
      o.frequency.exponentialRampToValueAtTime(Math.max(1, f1), t + dur);
      return o;
    };
    const out = ctx.createGain();
    out.gain.setValueAtTime(0, t);
    out.gain.linearRampToValueAtTime(v, t + 0.005);
    out.gain.exponentialRampToValueAtTime(0.0001, t + 0.5);
    out.connect(ctx.destination);

    switch (name) {
      case "hit": {
        const s = noise(0.15), lp = ctx.createBiquadFilter();
        lp.type = "lowpass";
        lp.frequency.setValueAtTime(4000, t);
        lp.frequency.exponentialRampToValueAtTime(500, t + 0.12);
        s.connect(lp).connect(out); s.start(t); s.stop(t + 0.16);
        break;
      }
      case "crit": {
        const s = noise(0.2), lp = ctx.createBiquadFilter();
        lp.type = "lowpass";
        lp.frequency.setValueAtTime(6000, t);
        lp.frequency.exponentialRampToValueAtTime(800, t + 0.15);
        const o = osc("square", 1200, 300, 0.15);
        s.connect(lp).connect(out); o.connect(out);
        s.start(t); s.stop(t + 0.22); o.start(t); o.stop(t + 0.15);
        break;
      }
      case "miss": {
        const s = noise(0.2), hp = ctx.createBiquadFilter();
        hp.type = "highpass"; hp.frequency.value = 1000;
        out.gain.linearRampToValueAtTime(v * 0.4, t + 0.01);
        s.connect(hp).connect(out); s.start(t); s.stop(t + 0.22);
        break;
      }
      case "heal": {
        const o1 = osc("sine", 400, 900, 0.3), o2 = osc("sine", 600, 1200, 0.3);
        out.gain.linearRampToValueAtTime(v * 0.5, t + 0.01);
        o1.connect(out); o2.connect(out);
        o1.start(t); o2.start(t); o1.stop(t + 0.3); o2.stop(t + 0.3);
        break;
      }
      case "death": {
        const s = noise(0.4), lp = ctx.createBiquadFilter();
        lp.type = "lowpass";
        lp.frequency.setValueAtTime(1500, t);
        lp.frequency.exponentialRampToValueAtTime(200, t + 0.4);
        const o = osc("sawtooth", 300, 60, 0.4);
        out.gain.linearRampToValueAtTime(v * 0.6, t + 0.01);
        s.connect(lp).connect(out); o.connect(out);
        s.start(t); s.stop(t + 0.42); o.start(t); o.stop(t + 0.4);
        break;
      }
      case "shield": {
        const o = osc("sine", 200, 90, 0.2);
        out.gain.linearRampToValueAtTime(v * 0.6, t + 0.01);
        o.connect(out); o.start(t); o.stop(t + 0.2);
        break;
      }
      case "card":
      case "ui": {
        const o = osc("square", 800, 600, 0.08);
        out.gain.linearRampToValueAtTime(v * 0.5, t + 0.005);
        o.connect(out); o.start(t); o.stop(t + 0.1);
        break;
      }
      case "victory": {
        [523, 659, 784, 1047].forEach((f, i) => this.arpeggioNote(ctx, f, i, v));
        break;
      }
      case "defeat": {
        [392, 330, 262, 196].forEach((f, i) => this.arpeggioNote(ctx, f, i, v, 0.5));
        break;
      }
      case "enemy_death": {
        // 与 death 同型但更短促
        const s = noise(0.3), lp = ctx.createBiquadFilter();
        lp.type = "lowpass";
        lp.frequency.setValueAtTime(1000, t);
        lp.frequency.exponentialRampToValueAtTime(150, t + 0.3);
        s.connect(lp).connect(out); s.start(t); s.stop(t + 0.32);
        break;
      }
    }
  }

  private arpeggioNote(ctx: AudioContext, freq: number, i: number, vol: number, factor = 1) {
    const t = ctx.currentTime + i * 0.12;
    const o = ctx.createOscillator();
    o.type = "triangle";
    o.frequency.value = freq;
    const g = ctx.createGain();
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(vol * 0.5 * factor, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.25);
    o.connect(g).connect(ctx.destination);
    o.start(t); o.stop(t + 0.3);
  }

  // ── BGM ──

  startBgm() {
    if (this.settings.muted) return;
    if (this.bgmTrack === "combat" && this.bgmPhase !== "idle") return; // 战斗 BGM 已在播
    this.stopBgm();
    this.bgmTrack = "combat";
    void getBaseUrl().then((base) => {
      const intro = new Audio();
      const loop = new Audio();
      intro.volume = this.settings.bgmVolume;
      loop.volume = this.settings.bgmVolume;
      intro.src = `${base}/api/assets/audio/bgm/combat_intro.wav`;
      loop.src = `${base}/api/assets/audio/bgm/combat_loop.wav`;
      loop.loop = true;
      intro.onended = () => { this.bgmPhase = "loop"; loop.play().catch(() => { /* 缺失静音 */ }); };
      this.bgmIntro = intro;
      this.bgmLoop = loop;
      this.bgmPhase = "intro";
      intro.play().catch(() => { /* 文件缺失/自动播放被拒 → 静音 */ });
    });
  }

  stopBgm() {
    this.bgmPhase = "idle";
    this.bgmTrack = null;
    if (this.bgmIntro) { this.bgmIntro.pause(); this.bgmIntro.src = ""; this.bgmIntro = null; }
    if (this.bgmLoop) { this.bgmLoop.pause(); this.bgmLoop.src = ""; this.bgmLoop = null; }
  }

  /** 当前 BGM 轨道（null = 未播放） */
  getBgmTrack(): "combat" | "menu" | null { return this.bgmTrack; }

  /** 主菜单 / 大厅 BGM 曲目列表（顺序轮播，播完循环回第一首） */
  private menuTracks: string[] = ["menu_1.mp3", "menu_2.mp3"];

  /** 主菜单 / 大厅 BGM：两首曲目顺序轮播（文件缺失时静默）。已在播放时不重启。 */
  startMenuBgm() {
    if (this.settings.muted) return;
    if (this.bgmTrack === "menu" && this.bgmPhase !== "idle") return; // 菜单 BGM 已在播
    this.stopBgm();
    this.bgmTrack = "menu";
    void getBaseUrl().then((base) => {
      // stopBgm 可能在此期间被再次调用（例如快速切换进战斗）→ 放弃
      if (this.bgmTrack !== "menu") return;
      this.playMenuTrack(base, 0);
    });
  }

  /** 播放菜单第 index 首；ended 后自动切下一首，播完循环。 */
  private playMenuTrack(base: string, index: number) {
    const name = this.menuTracks[index % this.menuTracks.length];
    if (!name) { this.bgmPhase = "idle"; this.bgmTrack = null; return; }
    const audio = new Audio();
    // 背景音乐音量：略低于用户设定（人声/完整编曲的响度高于旧合成乐）
    audio.volume = this.settings.bgmVolume * 0.6;
    audio.src = base + "/api/assets/audio/bgm/" + name;
    const next = () => this.playMenuTrack(base, index + 1);
    audio.addEventListener("ended", next);
    this.bgmLoop = audio;
    this.bgmIntro = null;
    this.bgmPhase = "loop";
    audio.play().catch(() => {
      // 文件缺失/自动播放被拒 → 静音；复位轨道标记以便下次手势后重试
      if (this.bgmLoop === audio) { this.bgmLoop = null; }
      this.bgmPhase = "idle";
      this.bgmTrack = null;
    });
  }

  /** 暂停 BGM（窗口失焦） */
  pauseBgm() {
    if (this.bgmPhase === "loop" && this.bgmLoop && !this.bgmLoop.paused) this.bgmLoop.pause();
    else if (this.bgmPhase === "intro" && this.bgmIntro && !this.bgmIntro.paused) this.bgmIntro.pause();
  }

  /** 恢复 BGM（窗口聚焦） */
  resumeBgm() {
    if (this.settings.muted || this.bgmPhase === "idle") return;
    if (this.bgmPhase === "loop" && this.bgmLoop && this.bgmLoop.paused) this.bgmLoop.play().catch(() => {});
    else if (this.bgmPhase === "intro" && this.bgmIntro && this.bgmIntro.paused) this.bgmIntro.play().catch(() => {});
  }
}

export const audioManager = new AudioManager();
