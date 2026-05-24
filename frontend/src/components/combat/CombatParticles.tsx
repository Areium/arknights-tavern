import { useEffect, useRef, useCallback, useState } from "react";

/*
 * Lightweight Canvas-based particle effects for combat.
 * No WebGL dependency — pure 2D Canvas.
 *
 * Particle types:
 *   "spark"   — attack hit sparks (small, fast, bright)
 *   "heal"    — healing glow particles (slow, upward float, green)
 *   "death"   — unit death dissolve (many particles, fading out)
 *   "victory" — celebration burst (golden, floating up)
 */

interface Particle {
  x: number; y: number;
  vx: number; vy: number;
  life: number; maxLife: number;
  size: number;
  color: string;
  alpha: number;
}

interface EmitterConfig {
  type: "spark" | "heal" | "death" | "victory";
  x: number; y: number;
  count?: number;
}

const EMITTER_DEFAULTS: Record<string, { count: number; speed: number; size: number; life: number; colors: string[] }> = {
  spark:   { count: 12, speed: 3, size: 3, life: 25, colors: ["#ff6b4a", "#ffa040", "#ffd700", "#fff"] },
  heal:    { count: 8,  speed: 1, size: 4, life: 40, colors: ["#4aff8b", "#a0ffc0", "#fff"] },
  death:   { count: 20, speed: 2, size: 3, life: 35, colors: ["#888", "#aaa", "#666", "#444"] },
  victory: { count: 30, speed: 2, size: 4, life: 60, colors: ["#ffd700", "#f0c060", "#ffa040", "#fff"] },
};

const PAD = 1.35; // extra canvas size multiplier for isometric overflow

interface Props {
  width?: number;
  height?: number;
  emitters: { id: string; config: EmitterConfig }[];
  onEmitterDone?: (id: string) => void;
}

export default function CombatParticles({ width: propWidth, height: propHeight, emitters, onEmitterDone }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const particlesRef = useRef<Particle[]>([]);
  const animRef = useRef<number>(0);
  const [containerSize, setContainerSize] = useState<{ w: number; h: number } | null>(null);

  // ResizeObserver to track parent container dimensions
  useEffect(() => {
    const el = containerRef.current?.parentElement;
    if (!el || propWidth) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          setContainerSize((prev) => {
            if (prev && prev.w === width && prev.h === height) return prev;
            return { w: width, h: height };
          });
        }
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [propWidth]);

  // Effective dimensions with generous padding for isometric diagonal overflow
  const effW = propWidth ?? (containerSize ? Math.round(containerSize.w * PAD) : 600);
  const effH = propHeight ?? (containerSize ? Math.round(containerSize.h * PAD) : 600);
  // Particles use parent-relative coords; canvas is larger and centered via negative margins
  const padX = propWidth ? 0 : containerSize ? Math.round((effW - containerSize.w) / 2) : 0;
  const padY = propHeight ? 0 : containerSize ? Math.round((effH - containerSize.h) / 2) : 0;

  const spawnParticles = useCallback((config: EmitterConfig) => {
    const def = EMITTER_DEFAULTS[config.type];
    const count = config.count || def.count;
    const newParticles: Particle[] = [];

    for (let i = 0; i < count; i++) {
      const angle = Math.random() * Math.PI * 2;
      const speed = def.speed * (0.5 + Math.random());
      newParticles.push({
        x: config.x,
        y: config.y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - (config.type === "victory" || config.type === "heal" ? 1.5 : 0),
        life: def.life * (0.5 + Math.random() * 0.5),
        maxLife: def.life,
        size: def.size * (0.5 + Math.random()),
        color: def.colors[Math.floor(Math.random() * def.colors.length)],
        alpha: 1,
      });
    }

    particlesRef.current.push(...newParticles);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = effW * dpr;
    canvas.height = effH * dpr;
    canvas.style.width = `${effW}px`;
    canvas.style.height = `${effH}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    let running = true;

    function tick() {
      if (!running || !ctx) return;
      ctx.clearRect(0, 0, effW, effH);

      const particles = particlesRef.current;
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.x += p.vx;
        p.y += p.vy;

        p.life--;
        p.alpha = Math.max(0, p.life / p.maxLife);

        ctx.globalAlpha = p.alpha;
        ctx.fillStyle = p.color;
        ctx.beginPath();
        ctx.arc(p.x + padX, p.y + padY, p.size * p.alpha, 0, Math.PI * 2);
        ctx.fill();

        if (p.life <= 0) {
          particles.splice(i, 1);
        }
      }

      ctx.globalAlpha = 1;
      animRef.current = requestAnimationFrame(tick);
    }

    animRef.current = requestAnimationFrame(tick);

    return () => {
      running = false;
      cancelAnimationFrame(animRef.current);
    };
  }, [effW, effH, padX, padY]);

  // Spawn new emitters
  const prevEmittersRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const prevIds = prevEmittersRef.current;
    const currentIds = new Set(emitters.map((e) => e.id));

    for (const emitter of emitters) {
      if (!prevIds.has(emitter.id)) {
        spawnParticles(emitter.config);
        if (onEmitterDone) {
          setTimeout(() => onEmitterDone(emitter.id), EMITTER_DEFAULTS[emitter.config.type].life * 35);
        }
      }
    }

    prevEmittersRef.current = currentIds;
  }, [emitters, spawnParticles, onEmitterDone]);

  return (
    <div ref={containerRef} className="absolute inset-0 pointer-events-none z-20" style={{ overflow: "visible" }}>
      <canvas
        ref={canvasRef}
        style={{
          position: "absolute",
          left: padX ? `-${padX}px` : 0,
          top: padY ? `-${padY}px` : 0,
          pointerEvents: "none",
        }}
      />
    </div>
  );
}
