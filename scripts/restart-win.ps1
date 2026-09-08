#Requires -Version 5.1
<#
  Arknights Tavern — Windows 一键重启（单窗口版）

  与旧版 scripts/restart-win.bat 的唯一差异在「启动/清理逻辑」，启动参数、端口、
  工作目录、环境变量、日志去处全部保持一致：

      Flask : python src/app.py      （工作目录 = 项目根目录，日志输出到本窗口）
      Vite  : npm run dev            （工作目录 = frontend/，日志输出到本窗口）

  设计要点：
    1. 不再用 start + cmd /k 为前后端各开一个终端窗口 —— Flask 与 npm run dev 都作为
       本脚本的子进程运行（继承当前控制台，不新建窗口），只保留调用脚本的这一个窗口。
    2. 脚本在前台等待前端进程，三条退出路径都统一收尾（finally + 控制台事件处理器）：
         · 关闭游戏窗口 → vite-plugin-electron 调 process.exit → npm/cmd 退出 → 本脚本清理 → 窗口关闭
         · Ctrl-C        → 子进程各自响应控制台事件而退出；本脚本靠注册的「真控制台事件
                           处理器」存活下来（PowerShell 5.1 默认会被直接终止且不跑 finally），
                           继续清理并关闭窗口
         · 脚本异常退出  → finally 兜底清理
    3. 启动前端前先等待后端 /api/status 就绪，避免 Electron 的 PythonProcessManager
       因 5000 端口还没监听而再拉起一个 Flask（旧版会残留两个 python 同时占用 5000）。
    4. 收尾时若父进程正是运行 restart-win.bat 的 cmd，会主动结束它 —— 否则 Ctrl-C 后
       cmd 会停在 "Terminate batch job (Y/N)?"，窗口不会关闭。
#>
[CmdletBinding()]
param(
    # 后端端口，默认 5000（与 src/app.py 中 API_PORT 的默认值一致）
    [int]$BackendPort = 5000,
    # 前端端口，默认 5173（与 frontend/vite.config.ts 的 server.port 一致）
    [int]$FrontendPort = 5173,
    # 等待后端就绪的秒数
    [int]$BackendTimeout = 60
)

$ErrorActionPreference = 'Stop'

# ── 让「本脚本」不因 Ctrl-C 而终止，但完全不影响子进程 ──
# 实测（Windows PowerShell 5.1）：收到 Ctrl-C 时 PowerShell 会直接终止进程，
# 连 finally 都不执行 —— 那样既没有收尾清理，窗口也不会自动关闭。
# 这里注册一个真正的控制台事件处理器：
#   · 只对 CTRL_C_EVENT(0) / CTRL_BREAK_EVENT(1) 返回 true（本脚本继续往下走，
#     于是 finally 的清理照常执行，最后窗口正常关闭）
#   · 关闭窗口 CTRL_CLOSE(2) 等不拦截，保持系统默认行为
#   · 刻意不使用 SetConsoleCtrlHandler(NULL, TRUE)：那个「忽略 Ctrl-C」属性会被
#     子进程继承，python / node / electron 也会一起忽略 Ctrl-C，反而杀不掉它们
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class ArktvConsole
{
    private delegate bool HandlerRoutine(uint ctrlType);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetConsoleCtrlHandler(HandlerRoutine handler, bool add);

    private static HandlerRoutine _keepAlive;   // 防止委托被 GC 回收

    // 是否收到过 Ctrl-C / Ctrl-Break（供 PowerShell 侧轮询）
    public static volatile bool Interrupted = false;

    public static bool Install()
    {
        _keepAlive = new HandlerRoutine(delegate(uint t)
        {
            if (t == 0 || t == 1) { Interrupted = true; return true; }
            return false;
        });
        return SetConsoleCtrlHandler(_keepAlive, true);
    }
}
'@ -ErrorAction SilentlyContinue
$script:CtrlCInstalled = $false
try { [ArktvConsole]::Install() | Out-Null; $script:CtrlCInstalled = $true } catch { }

# 是否收到 Ctrl-C（Add-Type 失败时恒为 $false）
function Test-CtrlC {
    if (-not $script:CtrlCInstalled) { return $false }
    return [ArktvConsole]::Interrupted
}

# ── 路径（本脚本位于 <项目根>\scripts\ 下）──
$Root     = Split-Path -Parent $PSScriptRoot
$Frontend = Join-Path $Root 'frontend'
$CmdExe   = if ($env:ComSpec) { $env:ComSpec } else { Join-Path $env:SystemRoot 'System32\cmd.exe' }

# Ctrl-C 结束时子进程的退出码（STATUS_CONTROL_C_EXIT），用它区分「正常关窗口」和「被中断」
$ControlCExitCode = -1073741510

# 进程句柄 / 状态
$Flask      = $null
$Front      = $null
$Abort      = $null   # 启动阶段失败原因（非空表示不启动前端）
$ExitCode   = 0
$Completed  = $false  # 前端进程是否自然结束（而非被 Ctrl-C / 异常打断）

# ── 输出助手 ──
function Write-Head($Text) { Write-Host $Text -ForegroundColor Cyan }
function Write-Step($Text) { Write-Host "  ● $Text" -ForegroundColor Yellow }
function Write-Ok  ($Text) { Write-Host "  ✓ $Text" -ForegroundColor Green }
function Write-Warn($Text) { Write-Host "  ⚠ $Text" -ForegroundColor Yellow }
function Write-Fail($Text) { Write-Host "  ✗ $Text" -ForegroundColor Red }

# ── 端口 → 监听进程 PID ──
function Get-ListeningProcessId {
    param([int]$Port)
    $ids = @()
    try {
        $ids = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
                 Select-Object -ExpandProperty OwningProcess -Unique)
    }
    catch {
        # 回退：netstat -ano（与旧版脚本同一套解析方式）
        foreach ($line in @(netstat -ano | Select-String -Pattern ":$Port\s+\S+\s+LISTENING")) {
            $cols = @($line.Line -split '\s+' | Where-Object { $_ })
            if ($cols.Count -ge 5) { $ids += [int]$cols[-1] }
        }
        $ids = @($ids | Select-Object -Unique)
    }
    # 前置逗号：保证「空结果」也返回数组而不是 $null
    return ,@($ids | Where-Object { $_ -and $_ -gt 0 })
}

# ── 结束进程树（/T 连带子进程，避免 Flask reloader / node→electron 残留）──
function Stop-Tree {
    param([int]$ProcessId, [string]$Label)
    if (-not $ProcessId -or $ProcessId -le 0) { return }
    if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { return }
    & taskkill.exe /PID $ProcessId /T /F 2>&1 | Out-Null
    Write-Ok "已停止 $Label (PID $ProcessId)"
}

# ── 在本控制台内启动子进程（等价 Start-Process -NoNewWindow，但不新开窗口）──
# 注意：PowerShell 5.1 的 Start-Process -PassThru 返回的进程对象读不到 ExitCode
# （恒为 $null），因此这里改用 ProcessStartInfo + Process.Start，才能拿到真实退出码。
function Start-Child {
    param([string]$FilePath, [string]$Arguments, [string]$WorkingDirectory)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = $Arguments
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false   # 不走 ShellExecute：子进程继承当前控制台，不产生新窗口
    $psi.CreateNoWindow = $false
    return [System.Diagnostics.Process]::Start($psi)
}

# ── 结束「拉起本脚本的 cmd」──
# Ctrl-C 会让 cmd 停在 "Terminate batch job (Y/N)?" 上，窗口因此不会关闭；
# 这里在清理完成后主动结束那个 cmd（只在父进程确实是运行 restart-win.bat 的 cmd 时才动它，
# 避免误杀用户自己终端里的 shell）。
function Close-LauncherCmd {
    try {
        $self = Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction SilentlyContinue
        if (-not $self) { return }
        $parentId = [int]$self.ParentProcessId
        if ($parentId -le 0) { return }
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$parentId" -ErrorAction SilentlyContinue
        if ($parent -and $parent.Name -eq 'cmd.exe' -and ([string]$parent.CommandLine -like '*restart-win.bat*')) {
            & taskkill.exe /PID $parentId /F 2>&1 | Out-Null
        }
    }
    catch { }
}

# ── 本项目遗留进程清扫（只匹配本项目路径，不误杀其他项目的 python/node）──
function Stop-ProjectLeftovers {
    $killed = @()

    # a) 仍占用端口的进程
    foreach ($port in @($BackendPort, $FrontendPort)) {
        foreach ($id in (Get-ListeningProcessId -Port $port)) {
            $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
            if ($proc) {
                & taskkill.exe /PID $id /T /F 2>&1 | Out-Null
                $killed += "PID $id ($($proc.ProcessName), :$port)"
            }
        }
    }

    # b) 命令行/可执行路径落在本项目内的 python / node / electron
    $specs = @(
        @{ Name = 'python.exe';   Pattern = "*$Root*src*app.py*" },
        @{ Name = 'node.exe';     Pattern = "*$Root*frontend*" },
        @{ Name = 'electron.exe'; Pattern = "*$Root*frontend*electron*" }
    )
    foreach ($spec in $specs) {
        $procs = @(Get-CimInstance Win32_Process -Filter "Name='$($spec.Name)'" -ErrorAction SilentlyContinue)
        foreach ($proc in $procs) {
            $cmdLine = [string]$proc.CommandLine
            $exePath = [string]$proc.ExecutablePath
            if ((($cmdLine -and $cmdLine -like $spec.Pattern) -or ($exePath -and $exePath -like $spec.Pattern)) `
                    -and (Get-Process -Id $proc.ProcessId -ErrorAction SilentlyContinue)) {
                & taskkill.exe /PID $proc.ProcessId /T /F 2>&1 | Out-Null
                $killed += "PID $($proc.ProcessId) ($($spec.Name))"
            }
        }
    }
    return $killed
}

# ══════════════════════════════════════════════════════════
Write-Host ''
Write-Head '  ═══════════════════════════════════════'
Write-Head '    Arknights Tavern — 重启前后端'
Write-Head '  ═══════════════════════════════════════'
Write-Host ''

# ── 0. 前置检查 ──
Write-Step '检查运行环境...'

$pythonExe = (Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if (-not $pythonExe) {
    Write-Fail 'python 未找到，请确认已安装 Python 并加入 PATH'
    exit 1
}
$appPy = Join-Path $Root 'src\app.py'
if (-not (Test-Path $appPy)) {
    Write-Fail "找不到后端入口：$appPy"
    exit 1
}
if (-not (Test-Path (Join-Path $Frontend 'package.json'))) {
    Write-Fail "找不到前端工程：$Frontend"
    exit 1
}
if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) {
    Write-Fail "缺少 frontend\node_modules，请先执行: cd frontend && npm install"
    exit 1
}
Write-Ok "Python : $pythonExe"
Write-Ok "前端   : $Frontend"
Write-Host ''

# ── 1. 停止旧进程 ──
Write-Step '停止旧进程...'

# 旧版脚本用 start + cmd /k 留下的两个窗口：这里一并关掉（窗口命令行特征精确匹配，
# 不会匹配到当前正在运行本脚本的窗口）
$legacyWindows = @(Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
        $cl = [string]$_.CommandLine
        $cl -like "*$Root*" -and ($cl -like '*python src/app.py*' -or $cl -like '*npm run dev*')
    })
foreach ($win in $legacyWindows) {
    & taskkill.exe /PID $win.ProcessId /T /F 2>&1 | Out-Null
    Write-Ok "已关闭旧脚本遗留的窗口 (PID $($win.ProcessId))"
}

$leftovers = Stop-ProjectLeftovers
foreach ($item in $leftovers) { Write-Ok "已停止 $item" }
Write-Ok "端口 $BackendPort/$FrontendPort 已释放"
Write-Host ''

# ── 2. 启动 Flask（本窗口内运行，不新开窗口）──
try {
    Write-Step "启动 Flask 后端 (python src/app.py, :$BackendPort)..."
    $Flask = Start-Child -FilePath $pythonExe -Arguments 'src/app.py' -WorkingDirectory $Root
    if (-not $Flask) { $Abort = 'Flask 进程启动失败' }

    # ── 2.1 等待后端就绪（关键：让 Electron 的端口探测看到 5000 已被占用）──
    if (-not $Abort) {
        $ready = $false
        $deadline = (Get-Date).AddSeconds($BackendTimeout)
        while ((Get-Date) -lt $deadline) {
            if ($Flask.HasExited) {
                $Abort = "Flask 进程已退出 (ExitCode=$($Flask.ExitCode))，请看上方输出"
                break
            }
            try {
                $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/api/status" `
                                          -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
                if ($resp.StatusCode -eq 200) { $ready = $true; break }
            }
            catch {
                Start-Sleep -Milliseconds 500
            }
        }
        if ($ready) {
            Write-Ok "Flask 已就绪 (PID $($Flask.Id), http://127.0.0.1:$BackendPort)"
        }
        elseif (-not $Abort) {
            Write-Warn "等待后端就绪超时 (${BackendTimeout}s)，仍继续启动前端"
        }
    }
    Write-Host ''

    # ── 3. 启动前端（Vite + Electron 游戏窗口），并在本脚本内等待它 ──
    if (-not $Abort) {
        Write-Step '启动前端 (npm run dev → Vite + Electron 游戏窗口)...'
        $Front = Start-Child -FilePath $CmdExe -Arguments '/c npm run dev' -WorkingDirectory $Frontend

        Write-Host ''
        Write-Head '  ═══════════════════════════════════════'
        Write-Host '   启动完成！'
        Write-Host "     Flask : http://127.0.0.1:$BackendPort"
        Write-Host "     游戏  : http://localhost:$FrontendPort （Electron 窗口）"
        Write-Host '     关闭游戏窗口或按 Ctrl-C 即自动清理并关闭本窗口'
        Write-Head '  ═══════════════════════════════════════'
        Write-Host ''

        # 等待前端退出。Ctrl-C 时：子进程会各自响应控制台事件而退出，但 cmd 包装层
        # （npm.cmd 是批处理）可能停在 "Terminate batch job (Y/N)?" 上不退出，
        # 因此这里轮询中断标志，收到 Ctrl-C 就主动结束整棵前端进程树，继续收尾。
        while (-not $Front.HasExited) {
            if (Test-CtrlC) {
                Write-Host ''
                Write-Step '收到 Ctrl-C，正在结束游戏进程...'
                Stop-Tree -ProcessId $Front.Id -Label '前端 (Vite/Electron)'
                break
            }
            Start-Sleep -Milliseconds 300
        }
        if (-not (Test-CtrlC)) {
            $ExitCode  = $Front.ExitCode
            $Completed = $true
        }
    }
}
finally {
    # ── 4. 收尾清理：正常关窗口 / Ctrl-C / 脚本异常，三条路径都经过这里 ──
    Write-Host ''
    Write-Step '正在清理...'

    if ($Front -and -not $Front.HasExited) { Stop-Tree -ProcessId $Front.Id -Label '前端 (Vite/Electron)' }
    if ($Flask -and -not $Flask.HasExited) { Stop-Tree -ProcessId $Flask.Id -Label '后端 (Flask)' }

    foreach ($item in (Stop-ProjectLeftovers)) { Write-Ok "已停止残留 $item" }

    # 端口释放有短暂延迟（taskkill 返回 ≠ socket 立即关闭），最多重试 3 秒
    # 注意：不能写成 @(Get-ListeningProcessId ...)：函数本身已返回数组，
    # 再套一层 @() 会把它包成「1 个元素的数组」，导致 .Count 恒为 1（误报占用）
    $busy = @()
    for ($attempt = 1; $attempt -le 8; $attempt++) {
        $busy = @()
        foreach ($port in @($BackendPort, $FrontendPort)) {
            if ((Get-ListeningProcessId -Port $port).Count -gt 0) { $busy += $port }
        }
        if ($busy.Count -eq 0) { break }
        Start-Sleep -Milliseconds 400
    }
    if ($busy.Count -gt 0) {
        Write-Warn "端口仍被占用: $($busy -join ', ')"
        foreach ($port in $busy) {
            foreach ($id in (Get-ListeningProcessId -Port $port)) {
                $holder = Get-Process -Id $id -ErrorAction SilentlyContinue
                Write-Warn "  :$port ← PID $id $($holder.ProcessName)"
            }
        }
    }
    else { Write-Ok "端口 $BackendPort/$FrontendPort 已释放，无残留进程" }

    # 启动失败（前端没跑起来）才留窗口给用户看原因；
    # 游戏窗口正常关闭 / Ctrl-C 一律直接退出，不阻塞窗口关闭
    if ($Abort) {
        Write-Host ''
        Write-Fail $Abort
        try { Read-Host '按 Enter 关闭窗口' | Out-Null } catch { }
    }
    elseif ($Completed -and $ExitCode -ne 0 -and $ExitCode -ne $ControlCExitCode) {
        Write-Host ''
        Write-Warn "前端进程退出码 $ExitCode（正常关闭游戏窗口时应为 0）"
    }

    Close-LauncherCmd
}

if ($Completed -and $ExitCode -ne 0 -and $ExitCode -ne $ControlCExitCode) { exit $ExitCode }
if ($Abort) { exit 1 }
exit 0
