/**
 * Preload 脚本 — 桥接主进程和渲染进程
 */

import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("electronAPI", {
  getBackendUrl: (): Promise<string> => ipcRenderer.invoke("get-backend-url"),
  openDirectory: (dirPath: string): Promise<{ success: boolean; error: string }> =>
    ipcRenderer.invoke("open-directory", dirPath),
});
