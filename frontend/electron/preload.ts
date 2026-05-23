/**
 * Preload 脚本 — 桥接主进程和渲染进程
 */

import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("electronAPI", {
  getBackendUrl: (): Promise<string> => ipcRenderer.invoke("get-backend-url"),
  getBackendStatus: (): Promise<{ status: string; url: string }> =>
    ipcRenderer.invoke("get-backend-status"),
  restartBackend: (): Promise<{ status: string }> =>
    ipcRenderer.invoke("restart-backend"),
  openDirectory: (dirPath: string): Promise<{ success: boolean; error: string }> =>
    ipcRenderer.invoke("open-directory", dirPath),

  // 后端状态变更监听（主进程推送）
  onBackendStatus: (callback: (status: { status: string; url: string }) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, status: any) => callback(status);
    ipcRenderer.on("backend-status", handler);
    return () => ipcRenderer.removeListener("backend-status", handler);
  },
});
