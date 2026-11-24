# Building VOLUMAX installers

**One command, on a Windows 10/11 PC:**

```
BUILD-ALL.cmd            (double-click)   or   .\BUILD-ALL.ps1
```

Everything lands in `release\VOLUMAX-<version>\`:

| File | For |
|---|---|
| `VOLUMAX-<v>-Setup-Modern-Win10-11-x64.exe` | Windows 10 (1809+) and 11, 64-bit |
| `VOLUMAX-<v>-Setup-Legacy-Win8-8.1-x64.exe` | Windows 8 / 8.1 (and 7 SP1), 64-bit |
| `VOLUMAX-<v>-Setup-Legacy-Win8-8.1-x86.exe` | Windows 8 / 8.1 (and 7 SP1), 32-bit |
| `VOLUMAX-<v>-Portable-<same labels>.zip` | no install; settings stay in `.\data` |
| `SHA256SUMS.txt` | checksums to publish next to the downloads |

## Why two kinds of build
Qt 6 (PySide6) and Python 3.9+ do not run on Windows 8/8.1. So the **Legacy** build uses
Python 3.8 + Qt 5.15 (PySide2) — the newest stack that still runs there — while the **Modern**
build uses current Python + Qt 6. The source code is the same; `src/volumax/qtcompat.py` and
`compat.py` absorb the differences. Windows 10/11 users can run either, Modern is recommended.
(Windows 8.0 itself reached end of support in 2016; install the free 8.1 update.)

## What the script does, per target
1. Finds the right Python (3.12 for Modern, **3.8 x64 / 3.8 x86** for Legacy). If missing it installs a
   *private* copy under `build\toolchains` (no admin, signature-checked, your system is untouched).
2. Creates an isolated venv and installs pinned packages (`requirements\modern.txt` / `legacy.txt`).
3. Prepares the matching 7-Zip engine: Modern uses `engines\7zip`; Legacy downloads 7-Zip 23.01
   (x64 / x86), verifies it is really that architecture, and pins its SHA-256 in
   `tools\engine-hashes.json` (commit that file).
4. Runs the test suite against that engine.
5. Builds the program with PyInstaller (`packaging\volumax.spec`, version info + Windows manifest).
6. **Runs the built program's own self-test** (`VOLUMAX.exe --selftest`): Qt loads, bundled 7-Zip is
   used, create/list/test/extract round trip works for 7z and zip with Unicode names, all UI pages open.
   A package that fails this is not released.
7. Makes the portable zip and compiles the installer with Inno Setup (`installer\volumax.iss`).
8. Writes `SHA256SUMS.txt` and `build\build.log`.

## Requirements on the build PC
* Windows 10/11 x64, internet on first run (Python, 7-Zip, pip packages are cached in `build\`).
* **Inno Setup 6.3 or 7.** Found automatically (`%LOCALAPPDATA%\Programs\Inno Setup 7`, Program Files, PATH).
  Elsewhere: `.\BUILD-ALL.ps1 --iscc "D:\tools\Inno\ISCC.exe"`.

## Useful options
```
--targets modern-x64            only some targets (modern-x64, legacy-x64, legacy-x86)
--no-installer                  executables + portable zips only
--skip-tests                    faster rebuilds
--clean                         wipe build\ first
--engine legacy-x86=C:\7z32     use your own 7z.exe/7z.dll (offline builds)
--sign-pfx cert.pfx             Authenticode-sign programs and installers
                                (password in env var VOLUMAX_SIGN_PASSWORD)
--dry-run                       print the plan, change nothing
```

## What the installer does
* Installs **per user by default (no admin prompt)**; the wizard offers "all users".
* Optional tasks: desktop shortcut, file associations (`.7z .tar .gz .tgz .bz2 .xz .cab .wim .iso`;
  `.zip/.rar` unchecked by default), Explorer right-click menu (*Extract here*, *Extract to folder*,
  *Add to archive…*, *Add to .7z*, *Add to .zip*). Selecting many files and choosing *Add to .7z* makes
  **one** archive (single-instance merge). Windows 11 shows these under "Show more options".
* Uninstall removes everything it added and asks whether to delete settings/logs.

## Honest limits
* **Not signed** unless you pass `--sign-pfx`: Windows SmartScreen will say "unknown publisher" until the
  files are signed (or have built reputation). Buy a code-signing certificate for public distribution.
* The Windows-only steps (Inno compile, Windows toolchain install, running the .exe on Windows 8) could not
  be executed where this was written (Linux). Everything else — both Qt stacks, the PyInstaller spec, the
  frozen-program self-test, the CLI verbs, the build tool's logic — was run and passes. The first build on your
  PC is therefore the real acceptance test; send `build\build.log` if any step fails.
* Windows 7 SP1 is allowed by the Legacy installer but is not a promised target. Windows 7/8 need the
  SHA-2 code-signing update (KB4474419) installed to trust SHA-256-signed files.
