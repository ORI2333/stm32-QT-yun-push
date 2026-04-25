param(
    [string]$PythonExe = "python",
    [string]$QtName = "AliyunQtHost",
    [string]$WebName = "WebDashboard",
    [string]$LauncherName = "StartAll",
    [string]$ReleaseDir = ".\dist\release",
    [switch]$NoDepsInstall,
    [switch]$NoCopyDotEnv
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }

function Resolve-AbsPath([string]$path, [string]$baseDir) {
    if ([System.IO.Path]::IsPathRooted($path)) {
        return [System.IO.Path]::GetFullPath($path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $baseDir $path))
}

function Write-TextFile(
    [string]$path,
    [string]$content,
    [string]$encodingName = "utf8"
) {
    $enc = [System.Text.Encoding]::UTF8
    if ($encodingName -eq "ascii") {
        $enc = [System.Text.Encoding]::ASCII
    }
    [System.IO.File]::WriteAllText($path, $content, $enc)
}

function Build-OnefileExe(
    [string]$pythonPath,
    [string]$entryPath,
    [string]$appName,
    [string]$distPath,
    [string]$workPath,
    [string]$specPath,
    [bool]$windowed,
    [string[]]$extraArgs = @()
) {
    $args = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", $appName,
        "--distpath", $distPath,
        "--workpath", $workPath,
        "--specpath", $specPath
    )

    if ($windowed) { $args += "--windowed" } else { $args += "--console" }
    if ($extraArgs.Count -gt 0) { $args += $extraArgs }
    $args += $entryPath

    Write-Info "PyInstaller => $appName"
    & $pythonPath @args
    if ($LASTEXITCODE -ne 0) {
        throw "Build failed for $appName, exit code=$LASTEXITCODE"
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonCmd = Get-Command $PythonExe -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    throw "Python executable not found: $PythonExe"
}
$pythonPath = $pythonCmd.Source

$qtEntry = Join-Path $scriptDir "qt.py"
$webEntry = Join-Path $scriptDir "web_dashboard.py"
$launcherEntry = Join-Path $scriptDir "run_all.py"

foreach ($f in @($qtEntry, $webEntry, $launcherEntry)) {
    if (-not (Test-Path $f)) { throw "Missing file: $f" }
}

$releaseAbs = Resolve-AbsPath -path $ReleaseDir -baseDir $scriptDir
$tmpRoot = Join-Path $scriptDir "build\release_pack"
$tmpDist = Join-Path $tmpRoot "dist"
$tmpWork = Join-Path $tmpRoot "work"
$tmpSpec = Join-Path $tmpRoot "spec"

Write-Info "Python: $pythonPath"
& $pythonPath -c "import sys; print(sys.executable); print(sys.version)"

if (-not $NoDepsInstall) {
    $req1 = Join-Path $scriptDir "requirements.txt"
    $req2 = Join-Path $scriptDir "requirements_web.txt"

    if (Test-Path $req1) {
        Write-Info "Installing requirements.txt"
        & $pythonPath -m pip install -r $req1
    }
    if (Test-Path $req2) {
        Write-Info "Installing requirements_web.txt"
        & $pythonPath -m pip install -r $req2
    }
}

Write-Info "Ensuring pyinstaller"
& $pythonPath -m pip install pyinstaller

foreach ($d in @($tmpRoot, $releaseAbs)) {
    if (Test-Path $d) {
        Write-Info "Cleaning: $d"
        Remove-Item -Recurse -Force $d
    }
}

New-Item -ItemType Directory -Path $tmpDist -Force | Out-Null
New-Item -ItemType Directory -Path $tmpWork -Force | Out-Null
New-Item -ItemType Directory -Path $tmpSpec -Force | Out-Null
New-Item -ItemType Directory -Path $releaseAbs -Force | Out-Null

$excludeQtSide = @(
    "--exclude-module", "PySide6",
    "--exclude-module", "PySide2",
    "--exclude-module", "PyQt6",
    "--exclude-module", "shiboken6",
    "--exclude-module", "shiboken2"
)
$excludeAllQt = @(
    "--exclude-module", "PySide6",
    "--exclude-module", "PySide2",
    "--exclude-module", "PyQt6",
    "--exclude-module", "PyQt5",
    "--exclude-module", "shiboken6",
    "--exclude-module", "shiboken2"
)

Build-OnefileExe `
    -pythonPath $pythonPath `
    -entryPath $qtEntry `
    -appName $QtName `
    -distPath $tmpDist `
    -workPath $tmpWork `
    -specPath $tmpSpec `
    -windowed $true `
    -extraArgs (@("--hidden-import", "PyQt5.sip") + $excludeQtSide)

Build-OnefileExe `
    -pythonPath $pythonPath `
    -entryPath $webEntry `
    -appName $WebName `
    -distPath $tmpDist `
    -workPath $tmpWork `
    -specPath $tmpSpec `
    -windowed $false `
    -extraArgs $excludeAllQt

Build-OnefileExe `
    -pythonPath $pythonPath `
    -entryPath $launcherEntry `
    -appName $LauncherName `
    -distPath $tmpDist `
    -workPath $tmpWork `
    -specPath $tmpSpec `
    -windowed $false `
    -extraArgs $excludeAllQt

$qtExe = Join-Path $tmpDist "$QtName.exe"
$webExe = Join-Path $tmpDist "$WebName.exe"
$launcherExe = Join-Path $tmpDist "$LauncherName.exe"
foreach ($f in @($qtExe, $webExe, $launcherExe)) {
    if (-not (Test-Path $f)) { throw "Expected exe not found: $f" }
}

Copy-Item $qtExe -Destination (Join-Path $releaseAbs "$QtName.exe") -Force
Copy-Item $webExe -Destination (Join-Path $releaseAbs "$WebName.exe") -Force
Copy-Item $launcherExe -Destination (Join-Path $releaseAbs "$LauncherName.exe") -Force

$envExample = Join-Path $scriptDir ".env.example"
if (Test-Path $envExample) {
    Copy-Item $envExample -Destination (Join-Path $releaseAbs ".env.example") -Force
}

$envActual = Join-Path $scriptDir ".env"
if (-not $NoCopyDotEnv -and (Test-Path $envActual)) {
    Copy-Item $envActual -Destination (Join-Path $releaseAbs ".env") -Force
    Write-Warn "Copied .env into release package (contains secrets)."
} elseif ((Test-Path $envExample) -and (-not (Test-Path (Join-Path $releaseAbs ".env")))) {
    Copy-Item $envExample -Destination (Join-Path $releaseAbs ".env") -Force
    Write-Info "No source .env copied; created .env from .env.example in release."
}

if (-not (Test-Path (Join-Path $releaseAbs ".dashboard_access"))) {
    Write-TextFile -path (Join-Path $releaseAbs ".dashboard_access") -content "1`r`n" -encodingName "utf8"
}

$readmeSource = Join-Path $scriptDir "README_EXE_使用说明.md"
if (Test-Path $readmeSource) {
    Copy-Item $readmeSource -Destination (Join-Path $releaseAbs "README_使用说明.md") -Force
}

$batStartAll = @"
@echo off
cd /d "%~dp0"
start "" "$LauncherName.exe" --qt-exe "$QtName.exe" --web-exe "$WebName.exe"
"@
Write-TextFile -path (Join-Path $releaseAbs "start_all.bat") -content $batStartAll -encodingName "ascii"

$batQt = @"
@echo off
cd /d "%~dp0"
start "" "$QtName.exe"
"@
Write-TextFile -path (Join-Path $releaseAbs "start_qt.bat") -content $batQt -encodingName "ascii"

$batWeb = @"
@echo off
cd /d "%~dp0"
start "" "$WebName.exe"
"@
Write-TextFile -path (Join-Path $releaseAbs "start_web.bat") -content $batWeb -encodingName "ascii"

Write-Ok "Release build completed"
Write-Host "Release dir: $releaseAbs"
Write-Host ""
Write-Host "Output files:"
Get-ChildItem -Path $releaseAbs -Force | Select-Object Name, Length, LastWriteTime
