param(
    [string]$PythonExe = "python",
    [string]$EntryScript = ".\qt.py",
    [string]$AppName = "AliyunQtHost",
    [string]$DistDir = ".\dist",
    [string]$WorkDir = ".\build\pyinstaller",
    [switch]$OneFile,
    [switch]$NoDepsInstall,
    [string]$IconPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }

function Resolve-AbsPath([string]$path, [string]$baseDir) {
    if ([string]::IsNullOrWhiteSpace($path)) { return "" }
    if ([System.IO.Path]::IsPathRooted($path)) { return [System.IO.Path]::GetFullPath($path) }
    return [System.IO.Path]::GetFullPath((Join-Path $baseDir $path))
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$entryAbs = Resolve-AbsPath -path $EntryScript -baseDir $scriptDir
$distAbs = Resolve-AbsPath -path $DistDir -baseDir $scriptDir
$workAbs = Resolve-AbsPath -path $WorkDir -baseDir $scriptDir
$specAbs = $scriptDir
$requirements = Join-Path $scriptDir "requirements.txt"
$envExample = Join-Path $scriptDir ".env.example"

if (-not (Test-Path $entryAbs)) {
    throw "Entry script not found: $entryAbs"
}

$pythonCmd = Get-Command $PythonExe -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    throw "Python executable not found: $PythonExe"
}

Write-Info "Python: $($pythonCmd.Source)"
& $pythonCmd.Source -c "import sys; print(sys.executable); print(sys.version)"

if (-not $NoDepsInstall) {
    if (Test-Path $requirements) {
        Write-Info "Installing runtime dependencies from requirements.txt"
        & $pythonCmd.Source -m pip install -r $requirements
    } else {
        Write-Warn "requirements.txt not found, skipping dependency install"
    }
}

Write-Info "Ensuring pyinstaller is installed"
& $pythonCmd.Source -m pip install pyinstaller

if (Test-Path $distAbs) {
    Write-Info "Cleaning dist dir: $distAbs"
    Remove-Item -Recurse -Force $distAbs
}
if (Test-Path $workAbs) {
    Write-Info "Cleaning work dir: $workAbs"
    Remove-Item -Recurse -Force $workAbs
}

New-Item -ItemType Directory -Path $distAbs -Force | Out-Null
New-Item -ItemType Directory -Path $workAbs -Force | Out-Null

$pyiArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", $AppName,
    "--distpath", $distAbs,
    "--workpath", $workAbs,
    "--specpath", $specAbs,
    "--hidden-import", "PyQt5.sip"
)

if ($OneFile) {
    $pyiArgs += "--onefile"
} else {
    $pyiArgs += "--onedir"
}

if (-not [string]::IsNullOrWhiteSpace($IconPath)) {
    $iconAbs = Resolve-AbsPath -path $IconPath -baseDir $scriptDir
    if (Test-Path $iconAbs) {
        $pyiArgs += @("--icon", $iconAbs)
    } else {
        Write-Warn "Icon not found, ignore: $iconAbs"
    }
}

# Avoid mixed Qt bindings conflict in environments that also have PySide/PyQt6.
$pyiArgs += @(
    "--exclude-module", "PySide6",
    "--exclude-module", "PySide2",
    "--exclude-module", "PyQt6",
    "--exclude-module", "shiboken6",
    "--exclude-module", "shiboken2"
)

# Keep an editable .env template next to exe output.
if (Test-Path $envExample) {
    $dataArg = "$envExample;."
    $pyiArgs += @("--add-data", $dataArg)
}

$pyiArgs += $entryAbs

Write-Info "Running PyInstaller..."
& $pythonCmd.Source @pyiArgs

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if ($OneFile) {
    $exePath = Join-Path $distAbs "$AppName.exe"
} else {
    $exePath = Join-Path (Join-Path $distAbs $AppName) "$AppName.exe"
}

if (-not (Test-Path $exePath)) {
    throw "Build finished but exe not found: $exePath"
}

Write-Ok "Build succeeded"
Write-Host "EXE: $exePath"
Write-Host ""
Write-Host "Run command:"
Write-Host "  `"$exePath`""
