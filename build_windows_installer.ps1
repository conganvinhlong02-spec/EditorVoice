param(
    [string]$PackageName = "EditorVoice-Windows"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistRoot = Join-Path $ProjectRoot "dist"
$PackageRoot = Join-Path $DistRoot $PackageName
$Payload = Join-Path $DistRoot "EditorVoice-Installer-Payload.zip"
$Installer = Join-Path $DistRoot "EditorVoice-Setup.exe"
$InstallerSource = Join-Path $ProjectRoot "packaging\windows\EditorVoiceInstaller.cs"
$Csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$IconPath = Join-Path $ProjectRoot "packaging\windows\EditorVoice.ico"
$IconBuilder = Join-Path $ProjectRoot "packaging\windows\New-EditorVoiceIcon.ps1"

if (-not (Test-Path -LiteralPath $PackageRoot)) { throw "Missing portable package. Run build_windows_portable.ps1 first." }
if (-not (Test-Path -LiteralPath $Csc)) { throw "Windows .NET Framework compiler was not found." }
& $IconBuilder -OutputPath $IconPath

if (Test-Path -LiteralPath $Payload) { Remove-Item -LiteralPath $Payload -Force }
if (Test-Path -LiteralPath $Installer) { Remove-Item -LiteralPath $Installer -Force }

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($PackageRoot, $Payload, [System.IO.Compression.CompressionLevel]::Optimal, $false)

& $Csc /nologo /codepage:65001 /target:winexe /platform:x64 /optimize+ /reference:System.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll /reference:System.Core.dll /win32icon:$IconPath /resource:$Payload,EditorVoice.Package.zip /out:$Installer $InstallerSource
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Installer)) { throw "Cannot create the Windows installer." }

Remove-Item -LiteralPath $Payload -Force
Write-Host "SETUP: $Installer" -ForegroundColor Green
