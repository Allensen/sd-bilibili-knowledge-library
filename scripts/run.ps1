param(
    [ValidateSet('run','publish','evidence','doctor','setup')][string]$Action = 'run',
    [string]$InputUrl,
    [string]$Output,
    [string]$Entry,
    [string]$Times,
    [string]$CookieFile,
    [string]$RuntimeRoot,
    [switch]$Isolated,
    [switch]$AllParts
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
    throw '此启动器当前支持 Windows x64。其他平台尚未验收。'
}
if (-not $RuntimeRoot) {
    $RuntimeRoot = Join-Path $env:LOCALAPPDATA 'sd-bilibili-knowledge-library'
    $locationFile = Join-Path $RuntimeRoot 'runtime-location.txt'
    if (Test-Path -LiteralPath $locationFile) {
        $savedRoot = [IO.File]::ReadAllText($locationFile).Trim()
        if ([IO.Path]::IsPathRooted($savedRoot) -and (Test-Path -LiteralPath (Join-Path $savedRoot 'venv\Scripts\python.exe'))) {
            $RuntimeRoot = $savedRoot
        }
    }
}
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
if ($Action -eq 'doctor' -and -not (Test-Path -LiteralPath (Join-Path $RuntimeRoot 'venv\Scripts\python.exe'))) {
    [pscustomobject]@{phase='环境状态';runtime=$RuntimeRoot;initialized=$false;message='首次正常运行时自动初始化。'} | ConvertTo-Json
    return
}
New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
$launchLock = $null
try {
    try { $launchLock = [IO.File]::Open((Join-Path $RuntimeRoot 'launcher.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { throw '另一个初始化进程正在运行，请稍后重试。' }
    $uvVersion = '0.11.24'
    $uvExe = Join-Path $RuntimeRoot 'tools\uv.exe'
    if (-not (Test-Path -LiteralPath $uvExe)) {
        $existingUv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue
        $existingUvCompatible = $false
        if ($existingUv -and -not $Isolated) {
            $existingVersion = & $existingUv.Source --version
            $existingUvCompatible = ($LASTEXITCODE -eq 0 -and $existingVersion -match '^uv 0\.11\.24(?:\s|$)')
        }
        if ($existingUvCompatible) {
            $uvExe = $existingUv.Source
        } else {
            Write-Output '正在准备运行工具（首次约 23 MiB，不修改系统 PATH）...'
            $toolsDir = Join-Path $RuntimeRoot 'tools'
            New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
            $uvZip = Join-Path $toolsDir 'uv.zip.partial'
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -UseBasicParsing -TimeoutSec 180 -Uri "https://github.com/astral-sh/uv/releases/download/$uvVersion/uv-x86_64-pc-windows-msvc.zip" -OutFile $uvZip
            $actualHash = (Get-FileHash -LiteralPath $uvZip -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actualHash -ne 'af9573a2e36f7020b18ec5fdde20117aae74bbad3f4acb3dc3fc03319f1aa083') { throw 'uv 安装包 SHA256 校验失败。' }
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            $zip = [IO.Compression.ZipFile]::OpenRead($uvZip)
            try {
                $binary = @($zip.Entries | Where-Object { $_.FullName -eq 'uv.exe' })
                if ($binary.Count -ne 1) { throw 'uv 安装包结构不符合预期。' }
                [IO.Compression.ZipFileExtensions]::ExtractToFile($binary[0], ($uvExe + '.partial'), $true)
            } finally { $zip.Dispose() }
            Move-Item -LiteralPath ($uvExe + '.partial') -Destination $uvExe -ErrorAction Stop
            Remove-Item -LiteralPath $uvZip -ErrorAction Stop
        }
    }
    $pythonExe = Join-Path $RuntimeRoot 'venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        Write-Output '正在准备独立 Python 环境；缺少 Python 时自动下载...'
        $oldPythonDir = $env:UV_PYTHON_INSTALL_DIR
        $oldCacheDir = $env:UV_CACHE_DIR
        try {
            $env:UV_PYTHON_INSTALL_DIR = Join-Path $RuntimeRoot 'python'
            $env:UV_CACHE_DIR = Join-Path $RuntimeRoot 'install-cache'
            $venvArgs = @('--no-config','--no-cache','venv','--python','3.11','--no-project')
            if ($Isolated) { $venvArgs += '--managed-python' }
            $venvArgs += (Join-Path $RuntimeRoot 'venv')
            & $uvExe @venvArgs
            if ($LASTEXITCODE -ne 0) { throw 'Python 初始化失败，请检查网络权限后重试。' }
        } finally {
            $env:UV_PYTHON_INSTALL_DIR = $oldPythonDir
            $env:UV_CACHE_DIR = $oldCacheDir
        }
    }
} finally { if ($launchLock) { $launchLock.Dispose() } }
$pipeline = Join-Path $PSScriptRoot 'library.py'
$pipelineArgs = @('-X','utf8',$pipeline,$Action,'--runtime',$RuntimeRoot,'--uv',$uvExe)
if ($InputUrl) { $pipelineArgs += @('--input',$InputUrl) }
if ($Output) { $pipelineArgs += @('--output',[IO.Path]::GetFullPath($Output)) }
if ($Entry) { $pipelineArgs += @('--entry',$Entry) }
if ($Times) { $pipelineArgs += @('--times',$Times) }
if ($AllParts) { $pipelineArgs += '--all-parts' }
if ($CookieFile) { $pipelineArgs += @('--cookie-file',[IO.Path]::GetFullPath($CookieFile)) }
& $pythonExe @pipelineArgs
if ($LASTEXITCODE -ne 0) { throw "知识库处理未完成，退出码 $LASTEXITCODE。已完成内容保留，可重试同一命令。" }
