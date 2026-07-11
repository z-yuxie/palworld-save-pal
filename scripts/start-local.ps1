<#
.SYNOPSIS
    以源码桌面开发模式启动 Palworld Save Pal（Windows）。
.DESCRIPTION
    本脚本自动检出并启动 Vite 前端开发服务器与 Python 后端，
    关闭桌面窗口或 Ctrl+C 后清理 Vite 子进程树。
    支持 -CheckOnly 预检模式，仅验证环境而不启动任何服务。
.PARAMETER CheckOnly
    仅执行环境预检并输出解析到的路径，不启动端口或 GUI。
.EXAMPLE
    .\start-local.ps1
.EXAMPLE
    .\start-local.ps1 -CheckOnly
#>

[CmdletBinding()]
param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

# ── 路径推导 ────────────────────────────────────────────────
$ScriptDir  = $PSScriptRoot
$RepoRoot   = Resolve-Path (Join-Path $ScriptDir "..")
$UiDir      = Join-Path $RepoRoot "ui"

# ── 定位 Python（优先 .venv，其次 PATH） ───────────────────
$venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython -PathType Leaf) {
    $PythonPath = $venvPython
    Write-Host "[信息] 使用虚拟环境 Python: $PythonPath"
} else {
    try {
        $PythonPath = (Get-Command python -ErrorAction Stop).Source
        Write-Host "[信息] 使用系统 PATH 中 Python: $PythonPath"
    } catch {
        Write-Error "未找到 Python。请创建 .venv 或将 python 加入 PATH。"
        exit 1
    }
}

# ── 定位 Bun ────────────────────────────────────────────────
try {
    $bunCommand = Get-Command bun.exe -ErrorAction SilentlyContinue
    if (-not $bunCommand) {
        $bunCommand = Get-Command bun -ErrorAction Stop
    }
    $BunPath = $bunCommand.Source
    Write-Host "[信息] 使用 Bun: $BunPath"
} catch {
    Write-Error "未找到 bun，请先安装 Bun (https://bun.sh)。"
    exit 1
}

# ── Python 预检导入（临时脚本，用完即删） ─────────────────
Write-Host "[预检] 测试 Python 导入 ..."
$importScript = Join-Path ([System.IO.Path]::GetTempPath()) (
    "psp_preflight_{0}.py" -f ([Guid]::NewGuid().ToString("N"))
)

@"
import sys
sys.path.insert(0, r"${RepoRoot}")
errors = []
for mod in ("webview", "palworld_save_tools", "palworld_save_pal"):
    try:
        __import__(mod)
        print(f"  [OK] {mod}")
    except ImportError as e:
        errors.append(mod)
        print(f"  [FAIL] {mod}: {e}")
if errors:
    sys.exit(1)
"@ | Set-Content -Path $importScript -Encoding UTF8
Push-Location $RepoRoot
try {
    & $PythonPath $importScript
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Python 预检导入失败，请确认依赖已安装（pip install -r requirements.txt 或 uv sync）。"
        exit 1
    }
} finally {
    Pop-Location
    Remove-Item $importScript -Force -ErrorAction SilentlyContinue
}

# ── 前端依赖 ────────────────────────────────────────────────
if (-not (Test-Path (Join-Path $UiDir "node_modules"))) {
    Write-Host "[安装] 前端依赖 (bun install --frozen-lockfile) ..."
    Push-Location $UiDir
    try {
        & $BunPath install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) {
            Write-Error "bun install 失败，请检查 ui/ 下的依赖配置。"
            exit 1
        }
    } finally {
        Pop-Location
    }
}

# ── CheckOnly 模式结束 ──────────────────────────────────────
if ($CheckOnly) {
    Write-Host ""
    Write-Host "=== 环境检查通过 ==="
    Write-Host "仓库根目录 : $RepoRoot"
    Write-Host "UI 目录    : $UiDir"
    Write-Host "Python     : $PythonPath"
    Write-Host "Bun        : $BunPath"
    exit 0
}

# ── 正常启动模式 ────────────────────────────────────────────
$originalCwd = Get-Location
$viteProcess = $null
$pythonExitCode = 1

try {
    # 启动 Vite 开发服务器（后台，输出保留到当前终端）
    Write-Host "[启动] Vite 开发服务器 (127.0.0.1:5173) ..."
    $viteArguments = @(
        "run", "dev:vite", "--", "--host", "127.0.0.1",
        "--port", "5173", "--strictPort"
    )
    $viteLauncher = $BunPath
    if ([System.IO.Path]::GetExtension($BunPath) -eq ".ps1") {
        $viteLauncher = (Get-Process -Id $PID).Path
        $viteArguments = @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", "`"$BunPath`""
        ) + $viteArguments
    }
    $viteProcess = Start-Process -FilePath $viteLauncher `
        -ArgumentList $viteArguments `
        -WorkingDirectory $UiDir `
        -NoNewWindow `
        -PassThru

    Write-Host "[等待] Vite 首次编译完成 ..."
    $viteReady = $false
    $viteDeadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $viteDeadline) {
        if ($viteProcess.HasExited) {
            throw "Vite 开发服务器启动失败（退出码: $($viteProcess.ExitCode)）。"
        }
        try {
            $response = Invoke-WebRequest `
                -Uri "http://127.0.0.1:5173" `
                -UseBasicParsing `
                -TimeoutSec 1
            if ($response.StatusCode -eq 200) {
                $viteReady = $true
                break
            }
        } catch [System.Management.Automation.PipelineStoppedException] {
            throw
        } catch {
            # 服务尚未就绪，继续等待。
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $viteReady) {
        throw "Vite 在 120 秒内未就绪，请检查上方编译输出。"
    }
    Write-Host "[信息] Vite 已就绪 (PID: $($viteProcess.Id))"

    # 在仓库根目录前台运行 Python 后端
    Set-Location $RepoRoot
    Write-Host "[启动] Python 桌面后端 (127.0.0.1:5174) ..."
    & $PythonPath desktop.py --dev --web-host 127.0.0.1 --web-port 5173
    $pythonExitCode = $LASTEXITCODE

} finally {
    try {
        # 清理整个 Vite 进程树
        if ($viteProcess -and -not $viteProcess.HasExited) {
            Write-Host "[清理] 终止 Vite 进程树 (PID: $($viteProcess.Id)) ..."
            taskkill.exe /PID $viteProcess.Id /T /F 2>$null
        }
    } finally {
        # 即使清理命令失败，也恢复调用者原始工作目录。
        Set-Location $originalCwd -ErrorAction SilentlyContinue
    }
}

exit $pythonExitCode
