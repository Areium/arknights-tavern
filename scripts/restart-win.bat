@echo off
rem Keep the console at UTF-8 so the PowerShell banner and the CJK output of
rem child processes render correctly. This is safe ONLY because this file is
rem pure ASCII: cmd.exe mis-parses batch files when `chcp 65001` is combined
rem with multi-byte characters in the same file (comment fragments get
rem executed as commands).
chcp 65001 >nul
rem ============================================================
rem  Arknights Tavern - one-window restart launcher
rem
rem  KEEP THIS FILE ASCII-ONLY (English comments and messages).
rem
rem  Why: a batch file that mixes `chcp 65001` with multi-byte
rem  (CJK) text makes cmd.exe re-seek the script at a wrong byte
rem  offset after the codepage change; it then executes fragments
rem  of comment lines as commands, e.g.
rem      '...' is not recognized as an internal or external command
rem  All logic and all CJK output live in restart-win.ps1.
rem
rem  Arguments are forwarded to restart-win.ps1, e.g.
rem      restart-win.bat -BackendPort 5001
rem ============================================================
setlocal
set "PS1=%~dp0restart-win.ps1"

if not exist "%PS1%" (
    echo [ERROR] restart-win.ps1 not found: "%PS1%"
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
