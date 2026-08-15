param(
    [switch]$SkipArchive,
    [switch]$Unlimited,
    [string]$PackageName = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistRoot = Join-Path $ProjectRoot "dist"
if ([string]::IsNullOrWhiteSpace($PackageName)) {
    $PackageName = if ($Unlimited) { "EditorVoice-Gift-Unlimited" } else { "EditorVoice-Windows" }
}
$PackageRoot = Join-Path $DistRoot $PackageName
$RuntimeRoot = Join-Path $PackageRoot "runtime"
$AppRoot = Join-Path $PackageRoot "app"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$VenvSitePackages = Join-Path $ProjectRoot ".venv\Lib\site-packages"
$Csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$IconPath = Join-Path $ProjectRoot "packaging\windows\EditorVoice.ico"

function Assert-SafePackagePath([string]$Path) {
    $project = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $expectedParent = [IO.Path]::GetFullPath((Join-Path $project "dist")).TrimEnd('\') + '\'
    $target = [IO.Path]::GetFullPath($Path)
    if (-not $target.StartsWith($expectedParent, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate outside the dist directory: $target"
    }
}

function Invoke-Robocopy([string]$Source, [string]$Destination, [string[]]$Extra = @()) {
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $arguments = @($Source, $Destination, "/E", "/COPY:DAT", "/DCOPY:DAT", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP") + $Extra
    & robocopy.exe @arguments | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "Cannot copy $Source (robocopy code $LASTEXITCODE)."
    }
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "Missing .venv. Run start_quick_studio.bat once before packaging."
}
if (-not (Test-Path -LiteralPath $Csc)) {
    throw "Windows .NET Framework compiler was not found."
}

Assert-SafePackagePath $PackageRoot
if (Test-Path -LiteralPath $PackageRoot) {
    Remove-Item -LiteralPath $PackageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $RuntimeRoot, $AppRoot -Force | Out-Null

Write-Host "[1/6] Preparing portable Python..." -ForegroundColor Cyan
$BasePython = (& $VenvPython -c "import sys; print(sys.base_prefix)").Trim()
if (-not (Test-Path -LiteralPath (Join-Path $BasePython "pythonw.exe"))) {
    throw "Base Python was not found at $BasePython"
}
Get-ChildItem -LiteralPath $BasePython -File | Copy-Item -Destination $RuntimeRoot -Force
Invoke-Robocopy (Join-Path $BasePython "DLLs") (Join-Path $RuntimeRoot "DLLs")
Invoke-Robocopy (Join-Path $BasePython "Lib") (Join-Path $RuntimeRoot "Lib") @("/XD", (Join-Path $BasePython "Lib\site-packages"))

Write-Host "[2/6] Copying AI libraries..." -ForegroundColor Cyan
$PortableSitePackages = Join-Path $RuntimeRoot "Lib\site-packages"
Invoke-Robocopy $VenvSitePackages $PortableSitePackages @("/XD", "__pycache__", ".cache")
Get-ChildItem -LiteralPath $PortableSitePackages -Filter "__editable__.vieneu-*.pth" -ErrorAction SilentlyContinue | Remove-Item -Force
Get-ChildItem -LiteralPath $PortableSitePackages -Filter "__editable___vieneu_*_finder.py" -ErrorAction SilentlyContinue | Remove-Item -Force

Write-Host "[3/6] Copying UI and application source..." -ForegroundColor Cyan
Invoke-Robocopy (Join-Path $ProjectRoot "apps") (Join-Path $AppRoot "apps") @("/XD", "__pycache__")
Invoke-Robocopy (Join-Path $ProjectRoot "client") (Join-Path $AppRoot "client")
Invoke-Robocopy (Join-Path $ProjectRoot "src\vieneu") (Join-Path $AppRoot "src\vieneu") @("/XD", "__pycache__")
Invoke-Robocopy (Join-Path $ProjectRoot "src\vieneu_utils") (Join-Path $AppRoot "src\vieneu_utils") @("/XD", "__pycache__")
Copy-Item -LiteralPath (Join-Path $ProjectRoot "LICENSE") -Destination (Join-Path $PackageRoot "LICENSE.txt") -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "packaging\windows\README.vi.txt") -Destination (Join-Path $PackageRoot "DOC-TRUOC.txt") -Force
if ($Unlimited) {
    @(
        "EDITORVOICE - PHIEN BAN QUA TANG KHONG GIOI HAN THOI GIAN",
        "",
        "Ban nay khong kiem tra ngay het han.",
        "Du lieu giong clone va lich su van chi duoc luu cuc bo tren may."
    ) | Set-Content -LiteralPath (Join-Path $PackageRoot "PHIEN-BAN-QUA-TANG.txt") -Encoding UTF8
}

Write-Host "[4/6] Compiling the Windows launcher..." -ForegroundColor Cyan
$IconBuilder = Join-Path $ProjectRoot "packaging\windows\New-EditorVoiceIcon.ps1"
& $IconBuilder -OutputPath $IconPath
$LauncherSource = Join-Path $ProjectRoot "packaging\windows\EditorVoiceLauncher.cs"
$LauncherExe = Join-Path $PackageRoot "EditorVoice.exe"
$compilerArguments = @(
    "/nologo",
    "/codepage:65001",
    "/target:winexe",
    "/platform:x64",
    "/optimize+",
    "/reference:System.dll",
    "/reference:System.Drawing.dll",
    "/reference:System.Windows.Forms.dll",
    "/win32icon:$IconPath",
    "/out:$LauncherExe"
)
if ($Unlimited) { $compilerArguments += "/define:EDITORVOICE_UNLIMITED" }
& $Csc @compilerArguments $LauncherSource
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $LauncherExe)) {
    throw "Cannot create EditorVoice.exe"
}

Write-Host "[5/6] Verifying the portable runtime..." -ForegroundColor Cyan
$oldPythonPath = $env:PYTHONPATH
$oldNoUserSite = $env:PYTHONNOUSERSITE
try {
    $env:PYTHONPATH = [string]::Join(
        [IO.Path]::PathSeparator,
        @($AppRoot, (Join-Path $AppRoot "src"), $PortableSitePackages)
    )
    $env:PYTHONNOUSERSITE = "1"
    $checkCode = 'import fastapi, uvicorn, numpy, soundfile, soxr, onnxruntime, tokenizers, huggingface_hub, sea_g2p; from apps import quick_studio; print(1)'
    & (Join-Path $RuntimeRoot "python.exe") -c $checkCode
    if ($LASTEXITCODE -ne 0) { throw "Portable runtime import verification failed." }
}
finally {
    $env:PYTHONPATH = $oldPythonPath
    $env:PYTHONNOUSERSITE = $oldNoUserSite
}

Write-Host "[6/6] Windows package completed." -ForegroundColor Green
if (-not $SkipArchive) {
    $ArchivePath = Join-Path $DistRoot ($PackageName + ".zip")
    Assert-SafePackagePath $ArchivePath
    if (Test-Path -LiteralPath $ArchivePath) { Remove-Item -LiteralPath $ArchivePath -Force }
    Write-Host "Creating ZIP archive (this may take a few minutes)..." -ForegroundColor DarkGray
    Compress-Archive -LiteralPath $PackageRoot -DestinationPath $ArchivePath -CompressionLevel Optimal
    Write-Host "ZIP: $ArchivePath" -ForegroundColor Green
}
Write-Host "APP: $LauncherExe" -ForegroundColor Green
