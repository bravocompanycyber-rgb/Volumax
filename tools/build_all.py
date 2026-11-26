#!/usr/bin/env python3
"""VOLUMAX — one command builds every Windows executable, portable zip and installer.

    python tools\\build_all.py                    # all targets
    python tools\\build_all.py --targets modern-x64
    python tools\\build_all.py --no-installer     # just the executables + portable zips
    python tools\\build_all.py --dry-run          # print what would run, change nothing

Targets (each is built with the toolchain that actually runs on that Windows):
    modern-x64   Windows 10 (1809+) / 11          Python 3.12 + PySide6 (Qt 6)
    legacy-x64   Windows 8 / 8.1 (7 SP1) 64-bit   Python 3.8  + PySide2 (Qt 5.15)
    legacy-x86   Windows 8 / 8.1 (7 SP1) 32-bit   Python 3.8  + PySide2 (Qt 5.15)

Needs only: Windows 10/11 x64 build PC, internet (first run), and Inno Setup 6.3+/7.
This file itself uses only the Python standard library and runs on Python 3.8+.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
RELEASE = ROOT / "release"
IS_WINDOWS = os.name == "nt"

APP = "VOLUMAX"
PUBLISHER = "Bravo Projects"
# 7-Zip used by the Legacy builds (23.01 is the last release line this project has verified
# on old Windows; change here to move to a newer one). Modern uses the repo's engines/7zip.
LEGACY_7ZIP = "2301"
LEGACY_7ZIP_URL = "https://www.7-zip.org/a/7z{v}{arch}.exe"
PYTHON_URLS = {
    ("3.8.10", "x64"): "https://www.python.org/ftp/python/3.8.10/python-3.8.10-amd64.exe",
    ("3.8.10", "x86"): "https://www.python.org/ftp/python/3.8.10/python-3.8.10.exe",
    ("3.12.10", "x64"): "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe",
}


class BuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:
    key: str
    flavor: str          # modern | legacy
    arch: str            # x64 | x86
    label: str           # used in file names
    python_versions: Tuple[str, ...]   # acceptable "major.minor"
    install_python: str  # full version downloaded if none is installed
    requirements: str
    description: str


TARGETS: Dict[str, Target] = {
    t.key: t
    for t in (
        Target("modern-x64", "modern", "x64", "Modern-Win10-11-x64", ("3.12", "3.13", "3.11", "3.10"),
               "3.12.10", "requirements/modern.txt", "Windows 10 (1809+) and Windows 11, 64-bit"),
        Target("legacy-x64", "legacy", "x64", "Legacy-Win8-8.1-x64", ("3.8",),
               "3.8.10", "requirements/legacy.txt", "Windows 8 / 8.1 (and 7 SP1), 64-bit"),
        Target("legacy-x86", "legacy", "x86", "Legacy-Win8-8.1-x86", ("3.8",),
               "3.8.10", "requirements/legacy.txt", "Windows 8 / 8.1 (and 7 SP1), 32-bit"),
    )
}


# ------------------------------------------------------------------------------ logging
class Log:
    def __init__(self, path: Path, dry: bool) -> None:
        self.dry = dry
        self.path = path
        if not dry:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(path, "w", encoding="utf-8", errors="replace")
        else:
            self._fh = None

    def write(self, text: str = "", to_console: bool = True) -> None:
        if to_console:
            try:
                print(text, flush=True)
            except UnicodeEncodeError:
                print(text.encode("ascii", "replace").decode(), flush=True)
        if self._fh:
            self._fh.write(text + "\n")
            self._fh.flush()

    def step(self, text: str) -> None:
        self.write(f"\n=== {text}")

    def close(self) -> None:
        if self._fh:
            self._fh.close()


# --------------------------------------------------------------------------- process utils
def run(cmd: Sequence, log: Log, *, cwd: Optional[Path] = None, env: Optional[dict] = None,
        timeout: Optional[int] = None, check: bool = True, quiet: bool = False) -> Tuple[int, str]:
    """Run a command, streaming its output to console + build log. Returns (code, output)."""
    shown = " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd)
    log.write(f"$ {shown}")
    if log.dry:
        return 0, ""
    merged = os.environ.copy()
    merged.update(env or {})
    merged.setdefault("PYTHONUTF8", "1")
    merged.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd) if cwd else None, env=merged,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            universal_newlines=True, encoding="utf-8", errors="replace")
    out: List[str] = []
    start = time.monotonic()
    assert proc.stdout is not None
    for line in proc.stdout:
        out.append(line)
        log.write(line.rstrip("\n"), to_console=not quiet)
        if timeout and time.monotonic() - start > timeout:
            proc.kill()
            raise BuildError(f"timed out after {timeout}s: {shown}")
    code = proc.wait()
    if check and code != 0:
        raise BuildError(f"command failed (exit {code}): {shown}")
    return code, "".join(out)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{n} B"


# -------------------------------------------------------------------------------- version
def read_version(override: Optional[str]) -> str:
    if override:
        if not re.fullmatch(r"\d+\.\d+\.\d+", override):
            raise BuildError("--version must look like 1.2.3")
        return override
    text = (ROOT / "src" / "volumax" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"(\d+\.\d+\.\d+)"', text)
    if not m:
        raise BuildError("cannot find __version__ in src/volumax/__init__.py")
    return m.group(1)


def artifact_name(kind: str, version: str, t: Target) -> str:
    """VOLUMAX-1.2.1-Setup-Modern-Win10-11-x64[.exe] / ...-Portable-...zip"""
    base = f"{APP}-{version}-{kind}-{t.label}"
    return base + (".exe" if kind == "Setup" else ".zip")


def version_info_text(version: str, t: Target) -> str:
    a, b, c = (int(x) for x in version.split("."))
    arch = "64-bit" if t.arch == "x64" else "32-bit"
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers=({a}, {b}, {c}, 0), prodvers=({a}, {b}, {c}, 0), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{PUBLISHER}'),
      StringStruct('FileDescription', '{APP} archive manager ({arch}, {t.flavor})'),
      StringStruct('FileVersion', '{version}.0'),
      StringStruct('InternalName', '{APP}'),
      StringStruct('LegalCopyright', 'Copyright (C) {PUBLISHER}'),
      StringStruct('OriginalFilename', '{APP}.exe'),
      StringStruct('ProductName', '{APP}'),
      StringStruct('ProductVersion', '{version}.0')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ])
"""


# ----------------------------------------------------------------------- PE / engine checks
def pe_machine(path: Path) -> str:
    """'x64' | 'x86' | 'arm64' | 'unknown' from the PE header (no tools needed)."""
    with open(path, "rb") as f:
        head = f.read(4096)
    if head[:2] != b"MZ":
        return "unknown"
    off = struct.unpack_from("<I", head, 0x3C)[0]
    with open(path, "rb") as f:
        f.seek(off)
        sig = f.read(6)
    if sig[:4] != b"PE\0\0":
        return "unknown"
    machine = struct.unpack("<H", sig[4:6])[0]
    return {0x8664: "x64", 0x014C: "x86", 0xAA64: "arm64"}.get(machine, "unknown")


def download(url: str, dest: Path, log: Log, retries: int = 3) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        log.write(f"  cached: {dest.name}")
        return
    log.write(f"  downloading {url}")
    if log.dry:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    last: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"{APP}-build/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(str(dest) + ".part", "wb") as out:
                shutil.copyfileobj(resp, out)
            os.replace(str(dest) + ".part", dest)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            log.write(f"  attempt {attempt}/{retries} failed: {exc}")
            time.sleep(2 * attempt)
    raise BuildError(f"could not download {url}: {last}\n"
                     f"  Download it manually and put it at: {dest}")


def verify_signature(path: Path, must_contain: str, log: Log) -> None:
    """Authenticode check (Windows) — used for the Python installers we download."""
    if not IS_WINDOWS or log.dry:
        return
    ps = ("$s = Get-AuthenticodeSignature -LiteralPath '{p}'; "
          "if ($s.Status -ne 'Valid') {{ Write-Output ('BAD:' + $s.Status); exit 3 }}; "
          "Write-Output $s.SignerCertificate.Subject").format(p=str(path).replace("'", "''"))
    code, out = run(["powershell", "-NoProfile", "-Command", ps], log, check=False, quiet=True)
    if code != 0 or must_contain.lower() not in out.lower():
        raise BuildError(f"signature check FAILED for {path.name}: {out.strip()}")
    log.write(f"  signature OK: {out.strip().splitlines()[-1][:90]}")


# -------------------------------------------------------------------------------- Python
def _probe_python(cmd: List[str], log: Log) -> Optional[Tuple[str, int, str]]:
    code_src = "import sys,struct;print(sys.executable);print(sys.version_info[0],sys.version_info[1]);print(struct.calcsize('P')*8)"
    try:
        r = subprocess.run(cmd + ["-c", code_src], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           universal_newlines=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    lines = r.stdout.strip().splitlines()
    if len(lines) < 3:
        return None
    major, minor = lines[1].split()
    return lines[0], int(lines[2]), f"{major}.{minor}"


def find_python(t: Target, log: Log) -> Optional[Path]:
    want_bits = 64 if t.arch == "x64" else 32
    candidates: List[List[str]] = []
    local = BUILD / "toolchains" / f"py{t.python_versions[0].replace('.', '')}-{t.arch}" / "python.exe"
    if local.exists():
        candidates.append([str(local)])
    if IS_WINDOWS:
        for v in t.python_versions:
            candidates.append(["py", f"-{v}-{want_bits}"])
    if not IS_WINDOWS or os.environ.get("VOLUMAX_USE_CURRENT_PYTHON"):
        candidates.append([sys.executable])
    for cmd in candidates:
        probe = _probe_python(cmd, log)
        if probe and probe[1] == want_bits and probe[2] in t.python_versions:
            return Path(probe[0])
    return None


def ensure_python(t: Target, log: Log) -> Path:
    found = find_python(t, log)
    if found:
        log.write(f"  Python for {t.key}: {found}")
        return found
    if not IS_WINDOWS:
        if log.dry:
            return Path("python")
        raise BuildError(f"no suitable Python {t.python_versions} for {t.key}")
    key = (t.install_python, t.arch)
    if key not in PYTHON_URLS:
        raise BuildError(f"install Python {t.python_versions[0]} ({t.arch}) from python.org and re-run")
    log.write(f"  Python {t.python_versions[0]} ({t.arch}) not found — installing a private copy (no admin, "
              f"does not touch your system Python)")
    installer = BUILD / "cache" / PYTHON_URLS[key].rsplit("/", 1)[1]
    download(PYTHON_URLS[key], installer, log)
    verify_signature(installer, "Python Software Foundation", log)
    target_dir = BUILD / "toolchains" / f"py{t.python_versions[0].replace('.', '')}-{t.arch}"
    run([installer, "/quiet", "InstallAllUsers=0", f"TargetDir={target_dir}", "Include_launcher=0",
         "Include_test=0", "Include_doc=0", "Include_tcltk=0", "Shortcuts=0", "AssociateFiles=0",
         "PrependPath=0", "Include_pip=1"], log, timeout=900)
    found = find_python(t, log)
    if not found and not log.dry:
        raise BuildError(f"Python install finished but {target_dir}\\python.exe was not usable")
    return found or target_dir / "python.exe"


def make_venv(t: Target, base_python: Path, log: Log) -> Path:
    venv = BUILD / "venv" / t.key
    py = venv / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
    if not py.exists():
        run([base_python, "-m", "venv", venv], log)
    run([py, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"], log, quiet=True)
    run([py, "-m", "pip", "install", "--disable-pip-version-check", "-r", ROOT / t.requirements], log)
    return py


# -------------------------------------------------------------------------------- engine
def prepare_engine(t: Target, overrides: Dict[str, Path], log: Log) -> Path:
    """Folder with 7z.exe + 7z.dll matching the target's architecture and Windows range."""
    if t.key in overrides:
        folder = overrides[t.key]
    elif t.flavor == "modern":
        folder = ROOT / "engines" / "7zip"
    else:
        folder = _fetch_legacy_engine(t, log)
    exe = folder / "7z.exe"
    if not log.dry:
        if not exe.is_file() or not (folder / "7z.dll").is_file():
            raise BuildError(f"engine folder {folder} must contain 7z.exe and 7z.dll")
        got = pe_machine(exe)
        if got != t.arch:
            raise BuildError(f"7z.exe in {folder} is {got}, but target {t.key} needs {t.arch}")
        log.write(f"  engine OK: {exe} ({got}, sha256 {sha256(exe)[:16]}…)")
    return folder


def _fetch_legacy_engine(t: Target, log: Log) -> Path:
    arch_part = "-x64" if t.arch == "x64" else ""
    name = f"7z{LEGACY_7ZIP}{arch_part}.exe"
    installer = BUILD / "cache" / name
    out = BUILD / "engines" / f"legacy-{t.arch}-{LEGACY_7ZIP}"
    if (out / "7z.exe").is_file() and (out / "7z.dll").is_file():
        return out
    download(LEGACY_7ZIP_URL.format(v=LEGACY_7ZIP, arch=arch_part), installer, log)
    if not log.dry:
        _check_pinned_hash(name, installer, log)
    # The official installer is an NSIS archive that 7-Zip itself can unpack.
    unpacker = ROOT / "engines" / "7zip" / "7z.exe"
    stage = BUILD / "engines" / f"_stage-{t.arch}"
    if not log.dry and stage.exists():
        shutil.rmtree(stage)
    if IS_WINDOWS:
        run([unpacker, "x", "-y", f"-o{stage}", installer], log, quiet=True)
    elif shutil.which("7z"):
        run(["7z", "x", "-y", f"-o{stage}", installer], log, quiet=True)
    elif not log.dry:
        raise BuildError("need 7z to unpack the 7-Zip installer")
    if not log.dry:
        out.mkdir(parents=True, exist_ok=True)
        for fn in ("7z.exe", "7z.dll", "License.txt", "readme.txt"):
            if (stage / fn).is_file():
                shutil.copy2(stage / fn, out / fn)
        shutil.rmtree(stage, ignore_errors=True)
    return out


def _check_pinned_hash(name: str, path: Path, log: Log) -> None:
    """Trust-on-first-use pin: the first download's SHA-256 is recorded in
    tools/engine-hashes.json; any later difference aborts the build. Commit that file."""
    pin_file = ROOT / "tools" / "engine-hashes.json"
    pins = json.loads(pin_file.read_text(encoding="utf-8")) if pin_file.exists() else {}
    digest = sha256(path)
    if name in pins and pins[name] != digest:
        raise BuildError(f"{name}: SHA-256 {digest} != pinned {pins[name]} (tools/engine-hashes.json). "
                         f"The download changed — delete the pin only if you trust the new file.")
    if name not in pins:
        pins[name] = digest
        pin_file.write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8")
        log.write(f"  pinned {name} = {digest}  (commit tools/engine-hashes.json)")


# --------------------------------------------------------------------------------- stages
def run_tests(t: Target, py: Path, engine: Path, log: Log) -> None:
    env = {"QT_QPA_PLATFORM": "offscreen", "VOLUMAX_7Z": str(engine / "7z.exe"),
           "PYTHONPATH": str(ROOT / "src")}
    run([py, "-m", "pytest", "tests", "-q", "-x", "-p", "no:cacheprovider"], log, cwd=ROOT, env=env, timeout=1800)


def build_exe(t: Target, py: Path, engine: Path, version: str, log: Log) -> Path:
    dist = BUILD / "dist" / t.key
    work = BUILD / "work" / t.key
    vfile = BUILD / f"version-{t.key}.txt"
    if not log.dry:
        for d in (dist, work):
            if d.exists():
                shutil.rmtree(d)
        vfile.parent.mkdir(parents=True, exist_ok=True)
        vfile.write_text(version_info_text(version, t), encoding="utf-8")
    env = {"VX_FLAVOR": t.flavor, "VX_ENGINE_DIR": str(engine), "VX_NAME": APP,
           "VX_VERSION_FILE": str(vfile), "PYTHONPATH": str(ROOT / "src")}
    run([py, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", dist, "--workpath", work,
         ROOT / "packaging" / "volumax.spec"], log, cwd=ROOT, env=env, timeout=3600)
    folder = dist / APP
    exe = folder / (APP + (".exe" if IS_WINDOWS else ""))
    if not log.dry and not exe.is_file():
        raise BuildError(f"PyInstaller finished but {exe} is missing")
    if not log.dry and IS_WINDOWS and pe_machine(exe) != t.arch:
        raise BuildError(f"{exe.name} is {pe_machine(exe)} but target needs {t.arch} (wrong Python?)")
    return folder


def smoke_test(t: Target, folder: Path, log: Log) -> None:
    """Run the BUILT program's self-test: Qt DLLs/plugins, bundled 7-Zip, archive round trip, UI."""
    exe = folder / (APP + (".exe" if IS_WINDOWS else ""))
    report = BUILD / f"selftest-{t.key}.json"
    if report.exists() and not log.dry:
        report.unlink()
    env = {"QT_QPA_PLATFORM": "offscreen"}
    code, _ = run([exe, "--selftest", report], log, env=env, timeout=300, check=False)
    if log.dry:
        return
    if not report.exists():
        raise BuildError(f"self-test produced no report (exit {code}) — the executable does not start")
    data = json.loads(report.read_text(encoding="utf-8"))
    for name, result in data.get("checks", {}).items():
        if not name.endswith(".trace"):
            log.write(f"    {name:18s} {result}")
    if not data.get("ok"):
        raise BuildError(f"self-test FAILED for {t.key} (see {report})")
    want = "PySide6" if t.flavor == "modern" else "PySide2"
    if data.get("binding") != want:
        raise BuildError(f"built with {data.get('binding')} but {t.flavor} must use {want}")
    log.write(f"  self-test passed ({data.get('binding')}, Python {data.get('python')})")


def make_portable(t: Target, folder: Path, version: str, out_dir: Path, log: Log) -> Path:
    name = artifact_name("Portable", version, t)
    dest = out_dir / name
    root_in_zip = name[:-4]
    log.write(f"  portable zip: {name}")
    if log.dry:
        return dest
    out_dir.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p, f"{root_in_zip}/{p.relative_to(folder).as_posix()}")
        z.writestr(f"{root_in_zip}/portable.flag",
                   "While this file sits next to VOLUMAX.exe, settings and logs are kept in .\\data\n")
        z.writestr(f"{root_in_zip}/README-PORTABLE.txt",
                   f"{APP} {version} — portable ({t.description})\n"
                   "Unzip anywhere (USB stick is fine) and run VOLUMAX.exe. Nothing is installed and\n"
                   "nothing is written outside this folder (settings live in .\\data).\n")
    return dest


def locate_iscc(explicit: Optional[str]) -> Optional[Path]:
    cands: List[Path] = []
    if explicit:
        cands.append(Path(explicit))
    if os.environ.get("ISCC"):
        cands.append(Path(os.environ["ISCC"]))
    local = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    for ver in ("7", "6"):
        for base in (local and Path(local) / "Programs", Path(pf86), Path(pf)):
            if base:
                cands.append(Path(base) / f"Inno Setup {ver}" / "ISCC.exe")
    cands.append(Path(r"C:\Users\bntcl\AppData\Local\Programs\Inno Setup 7\ISCC.exe"))
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        cands.append(Path(found))
    for c in cands:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def make_installer(iscc: Path, t: Target, folder: Path, version: str, out_dir: Path, log: Log) -> Path:
    name = artifact_name("Setup", version, t)
    out_dir.mkdir(parents=True, exist_ok=True) if not log.dry else None
    cmd = [iscc, "/Qp", f"/DAppVersion={version}", f"/DFlavor={t.flavor}", f"/DArch={t.arch}",
           f"/DSourceDir={folder}", f"/DOutputDir={out_dir}", f"/DOutputName={name[:-4]}",
           f"/DRepoRoot={ROOT}", ROOT / "installer" / "volumax.iss"]
    run(cmd, log, cwd=ROOT, timeout=1800)
    dest = out_dir / name
    if not log.dry and not dest.is_file():
        raise BuildError(f"ISCC finished but {dest} is missing")
    return dest


def sign(files: Sequence[Path], args: argparse.Namespace, log: Log) -> None:
    if not args.sign_pfx:
        return
    tool = shutil.which("signtool")
    if not tool:
        sdk = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
        found = sorted(sdk.glob("*/x64/signtool.exe")) if sdk.exists() else []
        tool = str(found[-1]) if found else None
    if not tool:
        raise BuildError("--sign-pfx given but signtool.exe was not found (install the Windows SDK)")
    pw = os.environ.get(args.sign_pass_env, "")
    for f in files:
        run([tool, "sign", "/fd", "SHA256", "/f", args.sign_pfx, "/p", pw, "/tr", args.timestamp_url,
             "/td", "SHA256", "/d", APP, f], log)


# ---------------------------------------------------------------------------------- main
@dataclass
class Result:
    target: Target
    ok: bool = False
    error: str = ""
    setup: Optional[Path] = None
    portable: Optional[Path] = None
    seconds: float = 0.0


def build_target(t: Target, args: argparse.Namespace, version: str, iscc: Optional[Path],
                 overrides: Dict[str, Path], log: Log) -> Result:
    res = Result(t)
    started = time.monotonic()
    try:
        log.step(f"[{t.key}] {t.description}")
        log.write("-- toolchain")
        base = ensure_python(t, log)
        py = make_venv(t, base, log)
        log.write("-- engine")
        engine = prepare_engine(t, overrides, log)
        if not args.skip_tests:
            log.write("-- tests")
            run_tests(t, py, engine, log)
        log.write("-- executable")
        folder = build_exe(t, py, engine, version, log)
        if IS_WINDOWS:
            sign([folder / f"{APP}.exe"], args, log)
        log.write("-- self-test of the built program")
        smoke_test(t, folder, log)
        log.write("-- packages")
        out = RELEASE / f"{APP}-{version}"
        res.portable = make_portable(t, folder, version, out, log)
        if iscc and not args.no_installer:
            res.setup = make_installer(iscc, t, folder, version, out, log)
            if IS_WINDOWS:
                sign([res.setup], args, log)
        res.ok = True
    except BuildError as exc:
        res.error = str(exc)
        log.write(f"\n!! {t.key} FAILED: {exc}")
    except Exception as exc:  # noqa: BLE001
        res.error = f"{exc.__class__.__name__}: {exc}"
        log.write(f"\n!! {t.key} crashed: {res.error}")
    res.seconds = time.monotonic() - started
    return res


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--targets", default="all", help="comma list of: " + ", ".join(TARGETS) + " (default: all)")
    p.add_argument("--version", help="override version (default: from src/volumax/__init__.py)")
    p.add_argument("--iscc", help="path to ISCC.exe (Inno Setup compiler); auto-detected otherwise")
    p.add_argument("--no-installer", action="store_true", help="skip Inno Setup (exe + portable zip only)")
    p.add_argument("--skip-tests", action="store_true", help="skip the unit test suite")
    p.add_argument("--clean", action="store_true", help="delete build/ first (fresh venvs and toolchains)")
    p.add_argument("--engine", action="append", default=[], metavar="TARGET=DIR",
                   help="use this folder (7z.exe + 7z.dll) instead of downloading, e.g. legacy-x86=C:\\7z32")
    p.add_argument("--sign-pfx", help="code-signing certificate (.pfx); signs exes and installers")
    p.add_argument("--sign-pass-env", default="VOLUMAX_SIGN_PASSWORD", help="env var holding the pfx password")
    p.add_argument("--timestamp-url", default="http://timestamp.digicert.com")
    p.add_argument("--dry-run", action="store_true", help="show the plan and commands, change nothing")
    p.add_argument("--list", action="store_true", help="list targets and exit")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.list:
        for t in TARGETS.values():
            print(f"{t.key:12s} {t.description}")
        return 0
    try:
        keys = list(TARGETS) if args.targets == "all" else [k.strip() for k in args.targets.split(",") if k.strip()]
        unknown = [k for k in keys if k not in TARGETS]
        if unknown:
            raise BuildError(f"unknown target(s): {', '.join(unknown)} (have: {', '.join(TARGETS)})")
        overrides: Dict[str, Path] = {}
        for item in args.engine:
            k, _, d = item.partition("=")
            if k not in TARGETS or not d:
                raise BuildError(f"--engine expects TARGET=DIR, got {item!r}")
            overrides[k] = Path(d)
        version = read_version(args.version)
    except BuildError as exc:
        print(f"error: {exc}")
        return 2

    if args.clean and not args.dry_run and BUILD.exists():
        shutil.rmtree(BUILD, ignore_errors=True)
    log = Log(BUILD / "build.log", args.dry_run)
    log.write(f"{APP} {version} — build on {platform.system()} {platform.release()} "
              f"({platform.machine()}), Python {platform.python_version()}")
    if not IS_WINDOWS and not args.dry_run and not os.environ.get("VOLUMAX_USE_CURRENT_PYTHON"):
        log.write("This builds Windows programs and must run on Windows 10/11 (use --dry-run to preview).")
        log.close()
        return 2

    iscc = None if args.no_installer else locate_iscc(args.iscc)
    if not args.no_installer:
        if iscc:
            log.write(f"Inno Setup compiler: {iscc}")
        elif IS_WINDOWS and not args.dry_run:
            log.write("Inno Setup (ISCC.exe) not found. Install Inno Setup, or pass --iscc PATH, "
                      "or use --no-installer.")
            log.close()
            return 2
        else:
            log.write("(dry run) Inno Setup would be located here")
    log.write("Targets: " + ", ".join(keys))

    results = [build_target(TARGETS[k], args, version, iscc, overrides, log) for k in keys]

    # ---- summary + checksums
    log.step("SUMMARY")
    out = RELEASE / f"{APP}-{version}"
    lines: List[str] = []
    for r in results:
        status = "OK   " if r.ok else "FAIL "
        log.write(f"{status}{r.target.key:12s} {r.seconds / 60:5.1f} min  {r.error[:110]}")
    if not args.dry_run:
        files = sorted(p for p in out.glob("*") if p.suffix in (".exe", ".zip")) if out.exists() else []
        for f in files:
            lines.append(f"{sha256(f)}  {f.name}")
            log.write(f"  {human(f.stat().st_size):>10s}  {f.name}")
        if lines:
            (out / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            log.write(f"\nOutput folder: {out}")
    log.close()
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
