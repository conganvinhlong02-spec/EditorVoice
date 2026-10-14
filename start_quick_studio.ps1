$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Find-Python {
    $CodexPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path -LiteralPath $CodexPython) { return $CodexPython }

    $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($PythonCommand) { return $PythonCommand.Source }

    $PyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($PyLauncher) { return $PyLauncher.Source }

    return $null
}

Write-Host ""
Write-Host "  EditorVoice" -ForegroundColor Green
Write-Host "  -----------"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    $BasePython = Find-Python
    if (-not $BasePython) {
        Write-Host ""
        Write-Host "Chua tim thay Python 3.10 tro len." -ForegroundColor Yellow
        Write-Host "Hay cai Python tu https://www.python.org/downloads/ roi chay lai file nay."
        exit 1
    }

    Write-Host "[1/3] Tao moi truong rieng cho ung dung..."
    if ([IO.Path]::GetFileName($BasePython) -ieq "py.exe") {
        & $BasePython -3.12 -m venv (Join-Path $ProjectRoot ".venv")
    } else {
        & $BasePython -m venv (Join-Path $ProjectRoot ".venv")
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot ".venv\.quick-studio-ready"))) {
    Write-Host "[2/3] Cai EditorVoice va engine VieNeu-TTS..."
    & $VenvPython -m pip install --disable-pip-version-check --upgrade pip
    & $VenvPython -m pip install --disable-pip-version-check -e $ProjectRoot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    New-Item -ItemType File -Path (Join-Path $ProjectRoot ".venv\.quick-studio-ready") -Force | Out-Null
}

Write-Host "[3/3] Dang mo http://127.0.0.1:7860"
Write-Host "Lan dau model se duoc tai ve. Giu cua so nay mo trong khi test." -ForegroundColor DarkGray
Write-Host ""
& $VenvPython -m apps.quick_studio
