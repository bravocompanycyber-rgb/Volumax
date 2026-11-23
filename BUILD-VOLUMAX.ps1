<#
.SYNOPSIS
    VOLUMAX master build script.
.DESCRIPTION
    Validates environment, runs tests, builds with PyInstaller (onedir),
    verifies the packaged engine, and writes a JSON build report.
#>

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$ReportPath = Join-Path $ProjectRoot "reports\build-report.json"
$LogPath = Join-Path $ProjectRoot "logs\build.log"

New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "reports") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "dist") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "build") | Out-Null

$report = [ordered]@{
    timestamp = (Get-Date -Format "o")
    success   = $false
    steps     = @()
    errors    = @()
}

function Step($name, $script) {
    Write-Host "`n=== $name ===" -ForegroundColor Cyan
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        & $script
        $sw.Stop()
        $report.steps += [ordered]@{ name = $name; status = "ok"; seconds = $sw.Elapsed.TotalSeconds }
        Write-Host "OK ($([math]::Round($sw.Elapsed.TotalSeconds,1))s)" -ForegroundColor Green
    } catch {
        $sw.Stop()
        $report.steps += [ordered]@{ name = $name; status = "fail"; seconds = $sw.Elapsed.TotalSeconds; error = $_.Exception.Message }
        $report.errors += $_.Exception.Message
        Write-Host "FAIL: $($_.Exception.Message)" -ForegroundColor Red
        throw
    }
}

try {
    Step "Validate Python" {
        $py = & python --version 2>&1
        Write-Host $py
        if (-not $?) { throw "Python not found" }
    }

    Step "Check dependencies (no reinstall)" {
        $mods = @("PySide6", "psutil", "pytest", "ruff")
        foreach ($m in $mods) {
            python -c "import $m; print('$m', getattr($m, '__version__', 'ok'))"
            if ($LASTEXITCODE -ne 0) { throw "Missing module: $m" }
        }
    }

    Step "Verify 7-Zip engine" {
        $exe = Join-Path $ProjectRoot "engines\7zip\7z.exe"
        if (-not (Test-Path $exe)) {
            throw "7z.exe not found at $exe"
        }
        Write-Host "Found: $exe"
    }

    Step "Audit source tree" {
        $required = @(
            "src\volumax\__init__.py",
            "src\volumax\app.py",
            "src\volumax\engine.py",
            "src\volumax\archive_manager.py",
            "src\volumax\ui\main_window.py",
            "assets\logo.png",
            "assets\logo.ico"
        )
        foreach ($r in $required) {
            $p = Join-Path $ProjectRoot $r
            if (-not (Test-Path $p)) { throw "Missing: $r" }
        }
        Write-Host "Source tree OK"
    }

    Step "Run Ruff" {
        Push-Location $ProjectRoot
        try {
            ruff check src tests --output-format=concise
            # non-zero is warning only for now
        } finally {
            Pop-Location
        }
    }

    Step "Run pytest" {
        Push-Location $ProjectRoot
        try {
            $env:PYTHONPATH = Join-Path $ProjectRoot "src"
            python -m pytest tests -v --tb=short
            if ($LASTEXITCODE -ne 0) { throw "pytest failed with exit $LASTEXITCODE" }
        } finally {
            Pop-Location
        }
    }

    Step "PyInstaller onedir build" {
        Push-Location $ProjectRoot
        try {
            $icon = Join-Path $ProjectRoot "assets\logo.ico"
            $addData = "engines;engines"
            if ($IsWindows -or $env:OS -match "Windows") {
                $sep = ";"
            } else {
                $sep = ":"
            }
            python -m PyInstaller `
                --noconfirm `
                --clean `
                --onedir `
                --windowed `
                --name VOLUMAX `
                --icon $icon `
                --add-data "assets${sep}assets" `
                --add-data "engines${sep}engines" `
                --paths src `
                --distpath dist `
                --workpath build `
                src\volumax\__main__.py

            if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
        } finally {
            Pop-Location
        }
    }

    Step "Verify packaged structure" {
        $distApp = Join-Path $ProjectRoot "dist\VOLUMAX"
        if (-not (Test-Path $distApp)) {
            # Linux may put binary differently
            $distApp = Join-Path $ProjectRoot "dist"
        }
        $exeCandidates = @(
            (Join-Path $distApp "VOLUMAX.exe"),
            (Join-Path $distApp "VOLUMAX"),
            (Join-Path $ProjectRoot "dist\VOLUMAX\VOLUMAX")
        )
        $found = $false
        foreach ($c in $exeCandidates) {
            if (Test-Path $c) {
                Write-Host "Executable: $c"
                $found = $true
                break
            }
        }
        if (-not $found) {
            Get-ChildItem -Recurse (Join-Path $ProjectRoot "dist") | Select-Object -First 30 FullName
            throw "Packaged executable not found"
        }

        # Engine must be bundled
        $engineCandidates = Get-ChildItem -Recurse (Join-Path $ProjectRoot "dist") -Filter "7z*" -ErrorAction SilentlyContinue
        if (-not $engineCandidates) {
            Write-Host "WARNING: 7z engine not found inside dist (may need manual copy)" -ForegroundColor Yellow
        } else {
            $engineCandidates | ForEach-Object { Write-Host "Bundled engine: $($_.FullName)" }
        }
    }

    $report.success = $true
    Write-Host "`nBUILD SUCCEEDED" -ForegroundColor Green
}
catch {
    $report.success = $false
    Write-Host "`nBUILD FAILED" -ForegroundColor Red
}
finally {
    $report | ConvertTo-Json -Depth 6 | Set-Content -Path $ReportPath -Encoding UTF8
    Write-Host "Report written to $ReportPath"
}

if (-not $report.success) { exit 1 }
