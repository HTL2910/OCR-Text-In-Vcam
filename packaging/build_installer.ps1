$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PyInstaller = Join-Path $ProjectRoot ".venv\Scripts\pyinstaller.exe"

if (-not (Test-Path $PyInstaller)) {
    throw "PyInstaller not found at $PyInstaller. Run: .venv\Scripts\pip install pyinstaller"
}

Push-Location $ProjectRoot
try {
    Write-Host "[1/3] Generating app icon..." -ForegroundColor Cyan
    & $Py "packaging\generate_icon.py"

    Write-Host "[2/3] Building bundled executables with PyInstaller..." -ForegroundColor Cyan
    & $PyInstaller --clean --noconfirm "packaging\ocr_vcam.spec"

    $Iscc = (Get-Command iscc -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
    if (-not $Iscc) {
        $Candidates = @(
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
            "$env:USERPROFILE\scoop\apps\innosetup\current\ISCC.exe",
            "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            "C:\Program Files\Inno Setup 6\ISCC.exe"
        )
        $Iscc = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if (-not $Iscc) {
        throw "Inno Setup (ISCC.exe) not found. Install via: scoop install extras/innosetup"
    }

    Write-Host "[3/3] Compiling Windows Setup installer with Inno Setup..." -ForegroundColor Cyan
    & $Iscc "packaging\installer.iss"

    Write-Host "`nBuild complete:" -ForegroundColor Green
    Get-ChildItem (Join-Path $ProjectRoot "release") -Filter "*.exe" | Format-Table Name, @{N="Size(MB)";E={[math]::Round($_.Length/1MB, 2)}}, LastWriteTime -AutoSize
} finally {
    Pop-Location
}
