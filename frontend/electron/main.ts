/**
 * Electron 主进程
 *
 * 职责:
 * - 窗口管理
 * - Python 后端子进程生命周期管理
 * - IPC 通信桥接
 */

import { app, BrowserWindow, ipcMain, shell } from "electron";
import { PythonProcessManager } from "./processManager";
import path from "path";

let mainWindow: BrowserWindow | null = null;
let processManager: PythonProcessManager | null = null;

const isDev = process.env.NODE_ENV === "development" || !app.isPackaged;
const BACKEND_PORT = 5000;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 600,
    title: "Arknights Tavern - 明日方舟文字角色扮演",
    backgroundColor: "#0f1117",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  });

  // 窗口准备好后再显示（避免白屏闪烁）
  mainWindow.once("ready-to-show", () => {
    mainWindow?.show();
  });

  if (isDev) {
    mainWindow.loadURL("http://localhost:5173");
  } else {
    mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

// ── Python 后端管理 ──

function getPythonProjectRoot(): string {
  // Electron app 在 frontend/ 下，Python 项目在上级目录
  return path.resolve(app.getAppPath(), "..");
}

function startBackend() {
  const projectRoot = getPythonProjectRoot();
  processManager = new PythonProcessManager({
    projectRoot,
    port: BACKEND_PORT,
    onReady: () => {
      mainWindow?.webContents.send("backend-status", {
        status: "connected",
        url: BACKEND_URL,
      });
    },
    onCrash: () => {
      mainWindow?.webContents.send("backend-status", {
        status: "disconnected",
        url: "",
      });
    },
    onHealthChange: (healthy: boolean) => {
      mainWindow?.webContents.send("backend-status", {
        status: healthy ? "connected" : "disconnected",
        url: healthy ? BACKEND_URL : "",
      });
    },
  });

  processManager.start();
}

// ── IPC 处理 ──

ipcMain.handle("get-backend-url", () => {
  // 开发模式使用 Vite 代理（同源请求），生产模式直连 Flask
  return isDev ? "" : BACKEND_URL;
});

ipcMain.handle("get-backend-status", () => {
  if (!processManager) return { status: "stopped", url: "" };
  return {
    status: processManager.isHealthy() ? "connected" : "disconnected",
    url: BACKEND_URL,
  };
});

ipcMain.handle("restart-backend", async () => {
  await processManager?.restart();
  return { status: "restarting" };
});

ipcMain.handle("open-directory", async (_event, dirPath: string) => {
  const result = await shell.openPath(dirPath);
  return { success: !result, error: result || "" };
});

// ── 应用生命周期 ──

app.whenReady().then(() => {
  createWindow();
  startBackend();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("will-quit", () => {
  processManager?.stop();
});
