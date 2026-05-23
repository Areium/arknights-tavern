import { useEffect, useRef, useCallback } from "react";

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

interface Props {
  width: number;
  height: number;
  emitters: { id: string; config: EmitterConfig }[];
  onEmitterDone?: (id: string) => void;
}

export default function CombatParticles({ width, height, emitters, onEmitterDone }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const particlesRef = useRef<Particle[]>([]);
  const animRef = useRef<number>(0);

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
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.scale(dpr, dpr);

    let running = true;

    function tick() {
      if (!running || !ctx) return;
      ctx.clearRect(0, 0, width, height);

      const particles = particlesRef.current;
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.x += p.vx;
        p.y += p.vy;

        // Heal and victory particles float upward
        p.life--;
        p.alpha = Math.max(0, p.life / p.maxLife);

        // Draw particle
        ctx.globalAlpha = p.alpha;
        ctx.fillStyle = p.color;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size * p.alpha, 0, Math.PI * 2);
        ctx.fill();

        // Remove dead particles
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
  }, [width, height]);

  // Spawn new emitters
  const prevEmittersRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const prevIds = prevEmittersRef.current;
    const currentIds = new Set(emitters.map((e) => e.id));

    for (const emitter of emitters) {
      if (!prevIds.has(emitter.id)) {
        spawnParticles(emitter.config);
        // Notify done after a short delay
        if (onEmitterDone) {
          setTimeout(() => onEmitterDone(emitter.id), EMITTER_DEFAULTS[emitter.config.type].life * 35);
        }
      }
    }

    prevEmittersRef.current = currentIds;
  }, [emitters, spawnParticles, onEmitterDone]);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 pointer-events-none z-20"
    />
  );
}
