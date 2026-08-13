/**
 * 后端 API 基地址。
 *
 * dev（浏览器 + Vite 代理）返回 "" → 同源，/api 经 Vite 代理到 Flask :5000。
 * Electron 生产环境通过 preload 拿后端 URL（file:// origin 下跨源访问）。
 * 供 useApi 与 audioManager 共用。
 */
export async function getBaseUrl(): Promise<string> {
  if (typeof window !== "undefined" && window.electronAPI) {
    try {
      return await window.electronAPI.getBackendUrl();
    } catch {
      return "";
    }
  }
  return "";
}
