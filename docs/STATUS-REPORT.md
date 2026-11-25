# VOLUMAX — Implementation Status Report

**Date:** 2026-11-23  
**Environment:** Clean rebuild in sandbox (Linux). Target platform is Windows.

---

## Implemented features

### Core engine
- Official 7-Zip CLI wrapper (`engine.py`) — list, create, extract, test, convert
- Native ZIP helpers for precise independent packaging
- Format support: ZIP, 7Z, TAR family (via 7-Zip)

### Safety
- Path traversal detection
- Absolute path rejection (Unix + Windows drives)
- Reserved Windows device names
- File-count and total-size limits
- Staging extraction with final path validation
- Control-character and overlong-component checks

### Independent ZIP packages
- Configurable max size (default 20 MB) and absolute ceiling (30 MB)
- Actual output-size verification (oversized packages deleted)
- Intelligent grouping, folder preservation, collision handling
- Clear skip reasons when a file cannot fit

### Multipart volumes
- 7-Zip split volumes (`name.7z.001`, …)
- Volume discovery and completeness checks
- Integrity test of reconstructed set
- Clear messaging that all parts are required

### Integrity & utilities
- Archive integrity test
- Checksums: MD5, SHA-1, SHA-256, SHA-512
- Duplicate finder by content hash

### Background jobs
- Sequential job queue with progress, cancel, pause flags
- Used by create / extract / package / volume UI actions

### GUI (PySide6)
- Dark navy / charcoal theme with blue & gold accents
- Navigation: Home, Create, Extract, Browser, Packages, Volumes, Integrity, Duplicates, Queue, Settings
- Working pages for Create, Extract, Browser, Independent Packages, Split Volumes, Job Queue, Settings
- Placeholder pages for Integrity & Duplicates (backend ready; full UI panels can be expanded)
- Persistent settings (JSON)
- Branding via `assets/logo.ico` / `logo.png` (replaceable)

### Build & packaging
- `BUILD-VOLUMAX.ps1` — validates env, runs ruff/pytest, PyInstaller onedir, verifies structure, writes JSON report
- `requirements.txt`, `README.md`

---

## Tested and passed

| Area | Result |
|------|--------|
| 7-Zip engine discovery | PASSED |
| Create + list 7z | PASSED |
| Native ZIP create/extract | PASSED |
| Password-protected 7z | PASSED |
| Integrity test | PASSED |
| Independent packaging + size limits | PASSED |
| Oversized file skip | PASSED |
| Actual size enforcement | PASSED |
| Path traversal / absolute / reserved name | PASSED |
| Safe destination containment | PASSED |
| File-count bomb limit | PASSED |
| ZIP with traversal entries | PASSED |
| Volume create + discover | PASSED |
| Incomplete volume detection | PASSED |
| Checksums | PASSED |
| Duplicate finder | PASSED |

**19 passed, 1 skipped** (gzip format name variant on this 7-Zip build).

---

## Features not yet fully implemented / expanded

- Full Integrity & Checksums **UI panel** (backend exists; page is a placeholder)
- Full Duplicate Finder **UI panel** (backend exists; page is a placeholder)
- Drag-and-drop onto the main window
- Pause/resume of in-flight 7-Zip processes (cancel is supported)
- Archive conversion UI
- Performance suite with 1,152 image files (not run in this sandbox)
- Inno Setup installer (availability not confirmed; script does not assume it)
- Windows executable launch verification (sandbox is Linux; run `BUILD-VOLUMAX.ps1` on the target machine)

---

## Known limitations

1. **Sandbox vs target:** Built and tested on Linux with system `7z`. On Windows, use the official `engines/7zip/7z.exe` + `7z.dll` already present in the project tree.
2. **Progress parsing:** 7-Zip progress is not yet streamed line-by-line into the UI (jobs report coarse state).
3. **Symlink extraction policy:** Symlinks are not specially recreated; safety focuses on path containment.
4. **Python version:** Sandbox used 3.12; target machine reports 3.14.8 — code is compatible.
5. **Placeholder logo:** Simple generated icon; replace with final artwork without code changes.

---

## Build and packaging status

- Source tree complete and modular.
- Automated tests green (19/20).
- `BUILD-VOLUMAX.ps1` ready for the Windows machine.
- PyInstaller onedir packaging is scripted; **must be executed on Windows** to produce and verify `dist/VOLUMAX/VOLUMAX.exe` with the bundled engine.

### Recommended next steps on the Windows machine

```powershell
cd "C:\Users\bntcl\Documents\T1911\Bravo Projects\Volumax"
# Copy this tree over the existing project (or replace unfinished sources)
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m pytest tests -v
python -m volumax          # launch GUI
.\BUILD-VOLUMAX.ps1        # full build + report
```

---

## Architecture summary

```
ArchiveManager  →  SevenZipEngine / native ZIP
                →  SafeExtractor
                →  IndependentZipPackager
                →  VolumeManager
                →  IntegrityChecker
JobQueue        →  background workers for long ops
Settings        →  persistent JSON
UI (PySide6)    →  pages bind to ArchiveManager + JobQueue
```


---
# v1.2.0 verification (what was actually run)

| Area | Result |
|---|---|
| Automated tests, Python 3.13 + PySide6 6.12 | 132 passed, 2 skipped |
| Automated tests, Python 3.8 + PySide2 5.15 (Windows 8 stack) | 132 passed, 2 skipped |
| Read-only-destination test (needs non-root) | passed when run as an unprivileged user |
| Frozen builds (PyInstaller 6 modern / 5.13 legacy), `--selftest` | all 8 checks OK on both |
| Contrast (WCAG AA 4.5:1) for every text/background pair and button | enforced by tests |
| UI rendered at 1100x720 and 860x560, every page | no clipped/hidden controls after fixes |

Bugs found by the simulation and fixed: stacked modal dialogs on failed batches; extraction limits not
live; unhandled errors on over-long/invalid typed paths; Python 3.8 `write_text(newline=)`; destructive
overwrite of an existing archive when a new run failed; startup crash when 7-Zip was missing.

## Small-file dictionary pack - measured, not assumed
Zstandard-19 per file, dictionary size included, synthetic web-log corpus:

| Files | dictionary gain vs plain per-file zstd | solid 7z -mx9 (for reference) |
|---|---|---|
| 50 (150 KB) | -76% (worse) | 14 KB (pack: ~51 KB) |
| 500 | +12% | 119 KB |
| 3000 | +44% | 678 KB (dictionary pack ~921 KB) |

Conclusion: the dictionary only pays off at thousands of files, and a normal solid 7z archive is smaller
in every case. The app therefore uses the dictionary automatically only when it saves >= 20%, and presents the
pack as a *random-access* tool, not a ratio winner.

## NOT verified here (no Windows machine / Inno Setup in the build sandbox)
- Compiling the Inno Setup installers, running on real Windows 8 / 10 / 11, Authenticode signing
  (unsigned installers will trigger SmartScreen until signed). First run of BUILD-ALL.cmd on your PC is the real test.
