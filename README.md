# VOLUMAX

**Professional Windows archive manager** — create, extract, package, and secure archives with a modern desktop UI.

[![Platform](https://img.shields.io/badge/platform-Windows-blue)](https://github.com/bravocompanycyber-rgb/Volumax)
[![Python](https://img.shields.io/badge/python-3.12%2B-yellow)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Proprietary-lightgrey)](LICENSE)

VOLUMAX competes with tools like **7-Zip**, **WinRAR**, and **WinZip** while adding intelligent packaging, strong encryption defaults, safe extraction, and a polished job queue.

---

## Features

### Core archive management
| Format | Open / Extract | Create |
|--------|----------------|--------|
| ZIP | ✅ | ✅ (AES-256 when passworded) |
| 7Z | ✅ | ✅ (AES-256 + optional encrypted filenames) |
| TAR / TAR.GZ / TAR.BZ2 / TAR.XZ | ✅ | ✅ |
| RAR | ✅ (via 7-Zip) | ❌ (requires WinRAR/`rar` — extract only) |
| CAB / ISO / WIM | ✅ (backend-dependent) | Limited |

- Browse without full extract  
- Selective extract  
- Convert between formats  
- Integrity test  
- Unicode & long path support  
- Preserve timestamps & folder structure  

### Intelligent packaging
- **Independent ZIP packages** — each ZIP is fully extractable on its own  
- **You choose the size limit** — no forced 20/30 MB cap (set 1 MB to 100+ GB as needed)  
- Actual output size verification  
- Smart file grouping & collision handling  
- **Multipart volumes** (`Backup.7z.001`, `.002`, …) with sequence checks  

### Security
- **AES-256** encryption (7Z and ZIP via 7-Zip)  
- Encrypted filenames / headers (7Z)  
- Password strength assessment  
- Secure password generator  
- Path-traversal & archive-bomb protection  
- Staging extraction  

### Tools
- Integrity Centre (CRC / SHA-1 / SHA-256 / SHA-512)  
- Duplicate finder (content hash)  
- Background job queue (progress + cancel)  
- Checksums for any file  

### Professional UI
Dark navy interface, high contrast, dashboard navigation:

Dashboard · Create · Extract · Browser · Packages · Volumes · Integrity · Duplicates · Job Queue · Settings

---

## Requirements

- Windows 10/11 (primary target)  
- Python 3.12+ (3.14 supported)  
- Dependencies: `PySide6`, `psutil`, `pytest`, `ruff`, `pyinstaller`  
- Official **7-Zip** engine: place `7z.exe` + `7z.dll` in `engines/7zip/`  

```text
engines/
└── 7zip/
    ├── 7z.exe
    └── 7z.dll
```

---

## Quick start

```powershell
cd Volumax
.\.venv\Scripts\Activate.ps1   # or create venv and pip install -r requirements.txt
$env:PYTHONPATH = "src"
python -m volumax
```

### Tests

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests -v
```

### Build Windows executable

```powershell
.\BUILD-VOLUMAX.ps1
```

---

## Architecture

```
src/volumax/
├── backends/          # Extensible engine adapters (7-Zip primary)
├── engine.py          # Facade + native ZIP helpers
├── extraction.py      # Safe extraction
├── packaging.py       # Independent packages (user-defined sizes)
├── volume_manager.py  # Multipart volumes
├── security.py        # Password strength + AES guidance
├── integrity.py / checksums.py / duplicate_finder.py
├── jobs.py            # Background queue
└── ui/                # PySide6 professional desktop UI
```

Designed so new backends, formats, and plugins can be added without rewriting the UI.

---

## Compared to other tools

| Capability | VOLUMAX | 7-Zip | WinRAR | WinZip |
|------------|---------|-------|-------|--------|
| 7Z create/extract | ✅ | ✅ | ✅ | Limited |
| ZIP AES-256 | ✅ | ✅ | ✅ | ✅ |
| Independent size-limited packages | ✅ | — | — | — |
| Multipart volumes | ✅ | ✅ | ✅ | ✅ |
| RAR extract | ✅ | ✅ | ✅ | ✅ |
| RAR create | External | — | ✅ | — |
| Safe extraction policies | ✅ | Partial | Partial | Partial |
| Job queue UI | ✅ | — | Limited | Limited |
| Duplicate finder | ✅ | — | — | — |

---

## Roadmap (modular upgrades)

- Watch folders & automation rules  
- Plugin API for extra formats  
- Context-menu shell integration  
- Installer (Inno Setup)  
- Optional RAR create when `rar.exe` is present  

---

## Project

- **Repository:** [bravocompanycyber-rgb/Volumax](https://github.com/bravocompanycyber-rgb/Volumax)  
- **Organization:** Bravo Company Cyber  

Replace `assets/logo.ico` and `assets/logo.png` with your final branding — no code changes required.

---

## License

Proprietary — Bravo Projects / Bravo Company Cyber. All rights reserved.


## Build installers (Windows 8 → 11)

Double-click `BUILD-ALL.cmd` (or run `.\BUILD-ALL.ps1`). It produces Setup installers and portable zips for
Windows 10/11 (Modern) and Windows 8/8.1 64/32-bit (Legacy) in `release\`. Details: [docs/BUILD.md](docs/BUILD.md).
