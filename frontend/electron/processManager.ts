/**
 * Python 后端子进程管理器
 *
 * 职责:
 * - 启动 Python Flask 后端作为子进程
 * - 定期健康检查 (GET /api/status)
 * - 崩溃后自动重启（最多 3 次）
 * - 优雅关闭 (SIGTERM → SIGKILL)
 */

import { spawn, ChildProcess } from "child_process";
import path from "path";
import http from "http";
import net from "net";

export interface ProcessManagerOptions {
  projectRoot: string; // Python 项目根目录
  port: number; // 后端端口
  onReady?: () => void;
  onCrash?: () => void;
  onHealthChange?: (healthy: boolean) => void;
  pythonPath?: string; // 自定义 Python 路径，默认使用项目 .venv
}

/**
 * 检测端口是否已被占用。
 */
function isPortInUse(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(true));
    server.once("listening", () => {
      server.close();
      resolve(false);
    });
    server.listen(port, "127.0.0.1");
  });
}

export class PythonProcessManager {
  private process: ChildProcess | null = null;
  private healthTimer: ReturnType<typeof setInterval> | null = null;
  private options: ProcessManagerOptions;
  private healthy = false;
  private crashCount = 0;
  private maxRestarts = 3;

  constructor(options: ProcessManagerOptions) {
    this.options = options;
  }

  async start(): Promise<void> {
    // 先检测端口是否已被占用（如手动启动的 Flask）
    const inUse = await isPortInUse(this.options.port);
    if (inUse) {
      console.log(
        `[Backend] Port ${this.options.port} already in use — monitoring existing backend`
      );
    } else {
      this.spawnProcess();
    }
    this.startHealthCheck();
  }

  stop(): void {
    this.stopHealthCheck();
    this.killProcess();
  }

  async restart(): Promise<void> {
    this.stopHealthCheck();
    this.killProcess();
    this.crashCount = 0;
    // 等待端口释放
    await new Promise((r) => setTimeout(r, 1000));

    const inUse = await isPortInUse(this.options.port);
    if (inUse) {
      console.log(
        `[Backend] Port ${this.options.port} still in use — monitoring existing backend`
      );
    } else {
      this.spawnProcess();
    }
    this.startHealthCheck();
  }

  isHealthy(): boolean {
    return this.healthy;
  }

  // ── 进程管理 ──

  private spawnProcess(): void {
    const { projectRoot } = this.options;

    // 优先使用项目虚拟环境的 Python。
    // Windows 与 Unix 的 venv 布局不同；Windows 没有 `python3` 命令，
    // 回退到 PATH 中的 `python`（Store 占位符 python3 不可用）。
    const fs = require("fs") as typeof import("fs");
    const isWindows = process.platform === "win32";
    const venvPython = isWindows
      ? path.join(projectRoot, ".venv", "Scripts", "python.exe")
      : path.join(projectRoot, ".venv", "bin", "python3");
    const fallback = isWindows ? "python" : "python3";
    const pythonPath =
      this.options.pythonPath ||
      (fs.existsSync(venvPython) ? venvPython : fallback);

    const appPath = path.join(projectRoot, "src", "app.py");
    const env = {
      ...process.env,
      FLASK_DEBUG: "false",
      API_HOST: "127.0.0.1",
      API_PORT: String(this.options.port),
    };

    console.log(`[Backend] Starting: ${pythonPath} ${appPath}`);
    this.process = spawn(pythonPath, [appPath], {
      cwd: path.join(projectRoot, "src"),
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    this.process.stdout?.on("data", (data: Buffer) => {
      const text = data.toString().trim();
      console.log(`[Backend:out] ${text}`);
    });

    this.process.stderr?.on("data", (data: Buffer) => {
      const text = data.toString().trim();
      // Flask 的启动日志在 stderr
      console.log(`[Backend:err] ${text}`);
    });

    this.process.on("exit", (code, signal) => {
      console.log(`[Backend] Exited (code=${code}, signal=${signal})`);
      this.healthy = false;
      this.options.onHealthChange?.(false);

      if (code !== 0 && signal !== "SIGTERM") {
        // 非正常退出 → 自动重启
        this.crashCount++;
        if (this.crashCount <= this.maxRestarts) {
          console.log(
            `[Backend] Auto-restart (${this.crashCount}/${this.maxRestarts})...`
          );
          this.options.onCrash?.();
          setTimeout(() => this.spawnProcess(), 2000);
        } else {
          console.error(
            `[Backend] Max restarts (${this.maxRestarts}) reached. Giving up.`
          );
        }
      }
    });

    this.process.on("error", (err) => {
      console.error(`[Backend] Process error:`, err.message);
    });
  }

  private killProcess(): void {
    if (!this.process) return;

    try {
      // 先发 SIGTERM 优雅关闭
      this.process.kill("SIGTERM");
      // 3 秒后如果还没退出则 SIGKILL
      const killTimer = setTimeout(() => {
        try {
          this.process?.kill("SIGKILL");
        } catch {}
      }, 3000);
      this.process.on("exit", () => clearTimeout(killTimer));
    } catch {
      // 进程可能已经死了
    }

    this.process = null;
  }

  // ── 健康检查 ──

  private startHealthCheck(): void {
    // 首次延迟 3 秒等待启动
    setTimeout(() => this.checkHealth(), 3000);

    this.healthTimer = setInterval(() => this.checkHealth(), 5000);
  }

  private stopHealthCheck(): void {
    if (this.healthTimer) {
      clearInterval(this.healthTimer);
      this.healthTimer = null;
    }
  }

  private checkHealth(): void {
    const req = http.get(
      `http://127.0.0.1:${this.options.port}/api/status`,
      { timeout: 3000 },
      (res) => {
        let body = "";
        res.on("data", (chunk) => (body += chunk));
        res.on("end", () => {
          if (res.statusCode === 200) {
            const wasHealthy = this.healthy;
            this.healthy = true;
            if (!wasHealthy) {
              console.log("[Backend] Health check passed");
              this.options.onReady?.();
              this.options.onHealthChange?.(true);
            }
          } else {
            this.setUnhealthy();
          }
        });
      }
    );

    req.on("error", () => {
      this.setUnhealthy();
    });

    req.on("timeout", () => {
      req.destroy();
      this.setUnhealthy();
    });
  }

  private setUnhealthy(): void {
    if (this.healthy) {
      this.healthy = false;
      console.log("[Backend] Health check failed");
      this.options.onHealthChange?.(false);
    }

    // 没有托管子进程但后端不可用 → 尝试启动
    if (!this.process && this.crashCount < this.maxRestarts) {
      console.log("[Backend] No managed process — attempting to start backend");
      this.spawnProcess();
    }
  }
}
