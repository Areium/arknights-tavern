@echo off
chcp 65001 >nul
rem ============================================================
rem  Arknights Tavern — Windows 一键重启（单窗口）
rem
rem  这里只做「同窗口启动 PowerShell」这一件事：
rem    · 不再用 start + cmd /k 为 Flask / Vite 各开一个窗口
rem    · PowerShell 脚本在前台等待前端进程，游戏窗口关闭 / Ctrl-C /
rem      异常退出时都会清理子进程并让本窗口自动关闭
rem
rem  可传参给 restart-win.ps1，例如：
rem      restart-win.bat -BackendPort 5001
rem ============================================================
setlocal
set "PS1=%~dp0restart-win.ps1"

if not exist "%PS1%" (
    echo [错误] 找不到 "%PS1%"
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
