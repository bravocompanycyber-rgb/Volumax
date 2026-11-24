<#
  VOLUMAX — one script, every Windows build.

  Builds, tests and packages:
    * Modern  (Windows 10 1809+ / 11, 64-bit)
    * Legacy  (Windows 8 / 8.1 / 7 SP1, 64-bit and 32-bit)
  into  release\VOLUMAX-<version>\  as Setup .exe installers + portable .zip + SHA256SUMS.txt

  Usage (PowerShell or just double-click BUILD-ALL.cmd):
    .\BUILD-ALL.ps1                              everything
    .\BUILD-ALL.ps1 --targets modern-x64         one target
    .\BUILD-ALL.ps1 --no-installer               exe + portable zip only
    .\BUILD-ALL.ps1 --iscc "C:\path\ISCC.exe"    if Inno Setup is somewhere unusual
  All arguments are passed to tools\build_all.py  (run with --help to see them).
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$env:PYTHONUTF8 = '1'

function Test-Python([string[]]$Cmd) {
    # returns the python.exe path if this command is a usable Python 3.8+
    try {
        $exe = $Cmd[0]; $rest = @(); if ($Cmd.Length -gt 1) { $rest = $Cmd[1..($Cmd.Length - 1)] }
        $out = & $exe @rest -c "import sys; print(sys.executable); print(int(sys.version_info >= (3, 8)))" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out.Count -ge 2 -and $out[1] -eq '1') { return $out[0] }
    } catch { }
    return $null
}

function Find-Python {
    foreach ($cmd in @(@('py', '-3.12'), @('py', '-3'), @('python'), @('python3'))) {
        $p = Test-Python $cmd
        if ($p) { return $p }
    }
    $private = Join-Path $root 'build\toolchains\bootstrap\python.exe'
    if (Test-Path $private) { return $private }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host 'No Python found - installing a private Python 3.12 (no admin needed)...' -ForegroundColor Yellow
    $cache = Join-Path $root 'build\cache'
    New-Item -ItemType Directory -Force $cache | Out-Null
    $installer = Join-Path $cache 'python-3.12.10-amd64.exe'
    if (-not (Test-Path $installer)) {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $installer -UseBasicParsing
    }
    $sig = Get-AuthenticodeSignature $installer
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        throw "Downloaded Python installer failed its signature check ($($sig.Status))."
    }
    $target = Join-Path $root 'build\toolchains\bootstrap'
    & $installer /quiet InstallAllUsers=0 "TargetDir=$target" Include_launcher=0 Include_test=0 Include_doc=0 Shortcuts=0 AssociateFiles=0 PrependPath=0 | Out-Null
    $python = Join-Path $target 'python.exe'
    if (-not (Test-Path $python)) { throw 'Python installation failed.' }
}

Write-Host "Using Python: $python" -ForegroundColor Cyan
& $python (Join-Path $root 'tools\build_all.py') @args
$code = $LASTEXITCODE
if ($code -eq 0) { Write-Host "`nBuild finished. Open the 'release' folder." -ForegroundColor Green }
else { Write-Host "`nBuild finished with errors (exit $code). See build\build.log" -ForegroundColor Red }
exit $code
