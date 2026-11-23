# VOLUMAX

**Professional Windows archive manager** — create, extract, package, and secure archives with a modern desktop UI.

[![Platform](https://img.shields.io/badge/platform-Windows-blue)](https://github.com/bravocompanycyber-rgb/Volumax)
[![Python](https://img.shields.io/badge/python-3.12%2B-yellow)](https://www.python.org/)

VOLUMAX competes with tools like **7-Zip**, **WinRAR**, and **WinZip** while adding intelligent packaging, strong encryption defaults, safe extraction, and a polished job queue.

## Features

### Core archive management
- **ZIP** — create & extract (AES-256 when passworded)
- **7Z** — create & extract (AES-256 + optional encrypted filenames)
- **TAR / TAR.GZ / TAR.BZ2 / TAR.XZ** — create & extract
- **RAR** — extract via 7-Zip (create requires external WinRAR/`rar`)
- Browse without full extract, selective extract, convert formats, integrity test
- Unicode & long path support; preserve timestamps & folder structure

### Intelligent packaging
- **Independent ZIP packages** — each ZIP fully extractable alone
- **You choose the size limit** — no forced 20/30 MB cap
- Actual output size verification
- **Multipart volumes** (`Backup.7z.001`, `.002`, …) with sequence checks

### Security
- **AES-256** encryption (7Z and ZIP via 7-Zip)
- Encrypted filenames/headers (7Z)
- Password strength assessment & secure generator
- Path-traversal & archive-bomb protection

### Tools
- Integrity Centre (SHA-256 / SHA-512 / MD5 / SHA-1)
- Duplicate finder
- Background job queue with cancel

### Professional UI
Dark navy high-contrast interface: Dashboard · Create · Extract · Browser · Packages · Volumes · Integrity · Duplicates · Job Queue · Settings

## Requirements

- Windows 10/11
- Python 3.12+
- PySide6, psutil, pytest, ruff, pyinstaller
- Official 7-Zip engine in `engines/7zip/` (`7z.exe` + `7z.dll`)

## Quick start

```powershell
cd Volumax
\.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m volumax
```

## Tests

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests -v
```

## Build

```powershell
.\BUILD-VOLUMAX.ps1
```

## Repository

**https://github.com/bravocompanycyber-rgb/Volumax**

Bravo Company Cyber / Bravo Projects
