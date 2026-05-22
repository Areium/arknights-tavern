@echo off
chcp 65001 >nul
echo ============================================
echo   Arknights Txt — 重启前后端
echo ============================================

cd /d "%~dp0\.."

echo.
echo [1/3] 正在停止旧进程...

:: 杀掉占用 5000 端口 (Flask) 的进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000.*LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
    echo   已停止 PID %%a (Flask :5000)
)

:: 杀掉占用 5173 端口 (Vite) 的进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173.*LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
    echo   已停止 PID %%a (Vite :5173)
)

:: 额外清理所有 Python 前端相关进程
taskkill /F /IM python.exe >nul 2>&1

echo   旧进程已清理

echo.
echo [2/3] 启动 Flask 后端...
start "Flask Backend" cmd /c "cd /d "%cd%" && python src/app.py"
echo   Flask 已在新窗口启动 (http://127.0.0.1:5000)

echo.
echo [3/3] 启动 Vite 前端...
start "Vite Frontend" cmd /c "cd /d "%cd%\frontend" && npm run dev"
echo   Vite 已在新窗口启动 (http://localhost:5173)

echo.
echo ============================================
echo   启动完成！等待窗口加载后访问：
echo     http://localhost:5173
echo ============================================
echo.
echo 按任意键关闭此窗口...
pause >nul
