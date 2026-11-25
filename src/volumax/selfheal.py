"""Self-healing: health checks, one-click repair, crash reports, plain-language errors.

Nothing here touches the registry, starts services or scans the user's drives; it only
looks at VOLUMAX's own folders and the temp directory (files prefixed ``volumax_``).
"""

from __future__ import annotations

import faulthandler
import logging
import os
import platform
import shutil
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import QT_BINDING, __version__
from .config import LOGS_DIR, USER_DIR

logger = logging.getLogger("volumax.selfheal")

_MB = 1024 * 1024
STALE_AGE_SECONDS = 24 * 3600
_fault_file = None  # kept open for faulthandler's lifetime


# --------------------------------------------------------------------------- errors

_FRIENDLY: list[tuple[tuple[str, ...], str]] = [
    (("wrong password", "cannot open encrypted archive", "can not open encrypted archive"),
     "The password is wrong, or this archive needs one. Re-type it carefully (case matters)."),
    (("no space left", "there is not enough space", "disk full", "error code: 112"),
     "The destination drive is full. Free some space or pick another destination."),
    (("access is denied", "permission denied", "error code: 5"),
     "Windows/the system refused access. Pick a folder you own (e.g. Documents), or close the program using the file."),
    (("being used by another process", "sharing violation", "error code: 32"),
     "Another program is using that file. Close it (or wait) and try again."),
    (("can not open file as archive", "cannot open file as archive", "is not supported archive"),
     "This does not look like a valid archive — it may be damaged, incomplete or not an archive at all. Try 'Salvage' in Tools."),
    (("unexpected end of archive", "unexpected end of data", "headers error"),
     "The archive is cut off (incomplete download or copy). Re-download it, or try 'Salvage' in Tools to recover what is readable."),
    (("data error", "crc failed", "checksum error"),
     "Some data is damaged. Try 'Salvage' in Tools to recover the intact files."),
    (("engine was not found", "7-zip engine not found"),
     "The 7-Zip engine is missing. Open Diagnostics → Repair (or Locate 7z.exe)."),
    (("path too long", "filename too long", "error code: 206"),
     "A path is too long. Extract closer to the drive root (e.g. C:\\Temp)."),
]


def explain(message: str) -> str:
    """Return a one-sentence plain-language hint for a raw engine error ('' if none)."""
    low = (message or "").lower()
    for needles, hint in _FRIENDLY:
        if any(n in low for n in needles):
            return hint
    return ""


# --------------------------------------------------------------------------- checks

@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""          # human text for the fix button / advice
    warn: bool = False     # not fatal, but worth showing

    @property
    def status(self) -> str:
        return "OK" if self.ok else ("WARN" if self.warn else "FAIL")


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".vx_probe_{os.getpid()}"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _stale_temp_items(now: float | None = None) -> list[Path]:
    import tempfile

    now = now or time.time()
    out: list[Path] = []
    try:
        for p in Path(tempfile.gettempdir()).glob("volumax_*"):
            try:
                if now - p.stat().st_mtime > STALE_AGE_SECONDS:
                    out.append(p)
            except OSError:
                continue
    except OSError:
        pass
    return out


def run_checks(manager=None) -> list[Check]:
    checks: list[Check] = []

    # engine
    eng_ok, eng_detail = False, "not found"
    try:
        engine = manager.engine if manager is not None else None
        if engine is None:
            from .engine import SevenZipEngine

            engine = SevenZipEngine()
        if engine.available:
            ver = engine.version()
            eng_ok = ver != "unknown"
            eng_detail = f"{ver}  ({engine.exe})" if eng_ok else f"found at {engine.exe} but it does not run"
    except Exception as exc:  # never let a check crash the page
        eng_detail = f"error: {exc}"
    checks.append(Check("7-Zip engine", eng_ok, eng_detail,
                        "Repair re-detects it; or use 'Locate 7z.exe' to point at one."))

    # settings
    from .settings import get_settings

    s = get_settings()
    recovered = getattr(s, "recovered_from", "")
    checks.append(Check("Settings file", True, f"{s.path}" + (f"  (a damaged copy was kept: {recovered})" if recovered else "")))

    # folders
    for label, folder in (("Settings folder writable", USER_DIR), ("Log folder writable", LOGS_DIR)):
        checks.append(Check(label, _writable(folder), str(folder), "Choose a folder you can write to (set VOLUMAX_HOME)."))

    # disk space
    try:
        free = shutil.disk_usage(USER_DIR if USER_DIR.exists() else Path.home()).free
        checks.append(Check("Free disk space (settings drive)", free > 200 * _MB,
                            f"{free // _MB:,} MB free", "Free up some space.", warn=True))
    except OSError as exc:
        checks.append(Check("Free disk space", False, str(exc), warn=True))

    # stale temp
    stale = _stale_temp_items()
    checks.append(Check("Leftover temporary files", not stale,
                        f"{len(stale)} old item(s) in the temp folder" if stale else "none",
                        "Repair removes them.", warn=True))

    # optional extras
    try:
        import psutil  # noqa: F401
        checks.append(Check("psutil (memory-aware tuning)", True, "installed"))
    except Exception:
        checks.append(Check("psutil (memory-aware tuning)", False,
                            "not installed — using safe defaults", "pip install psutil", warn=True))
    try:
        import zstandard

        checks.append(Check("zstandard (small-file packs)", True, f"installed {zstandard.__version__}"))
    except Exception:
        checks.append(Check("zstandard (small-file packs)", False,
                            "not installed — Small-file Pack is disabled", "pip install zstandard", warn=True))
    return checks


def repair(manager=None) -> list[str]:
    """Fix what can be fixed automatically. Returns human-readable actions taken."""
    actions: list[str] = []
    # 1) engine
    try:
        if manager is not None and not manager.engine.available:
            actions.append("Engine still missing — use 'Locate 7z.exe'.")
        elif manager is not None:
            actions.append("Engine re-detected.")
    except Exception as exc:
        actions.append(f"Engine check failed: {exc}")
    # 2) settings readable?
    from .settings import get_settings

    s = get_settings()
    s.load()
    if getattr(s, "recovered_from", ""):
        actions.append(f"Damaged settings were replaced with defaults (copy kept: {s.recovered_from}).")
    # 3) folders
    for folder in (USER_DIR, LOGS_DIR):
        if not folder.exists() and _writable(folder):
            actions.append(f"Recreated {folder}")
    # 4) stale temp
    removed = 0
    for item in _stale_temp_items():
        try:
            shutil.rmtree(item) if item.is_dir() else item.unlink()
            removed += 1
        except OSError:
            continue
    if removed:
        actions.append(f"Removed {removed} leftover temporary item(s).")
    if not actions:
        actions.append("Nothing needed repairing.")
    return actions


def locate_engine(manager, path: Path) -> tuple[bool, str]:
    """Adopt a user-chosen 7z binary after proving it runs; persist it in settings."""
    import subprocess

    path = Path(path)
    if not path.is_file():
        return False, "That file does not exist."
    try:
        out = subprocess.run([str(path)], capture_output=True, text=True, timeout=15,
                             stdin=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"That file could not be run: {exc}"
    if "7-Zip" not in out and "7z" not in out.lower():
        return False, "That file does not look like 7-Zip (7z.exe / 7zz)."
    from .settings import get_settings

    s = get_settings()
    s.set("sevenzip_path", str(path))
    s.save()
    manager.engine.set_exe(path)
    return True, f"Using {path}"


# --------------------------------------------------------------------------- reports

def system_summary() -> str:
    return "\n".join([
        f"VOLUMAX {__version__} ({QT_BINDING})",
        f"Python {sys.version.split()[0]} on {platform.platform()}",
        f"Frozen build: {bool(getattr(sys, 'frozen', False))}",
        f"User folder: {USER_DIR}",
    ])


def export_report(dest: Path, manager=None) -> Path:
    lines = [system_summary(), "", "Health checks:"]
    for c in run_checks(manager):
        lines.append(f"  [{c.status}] {c.name}: {c.detail}")
    log = LOGS_DIR / "volumax.log"
    if log.is_file():
        try:
            tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
            lines += ["", "Last log lines:", *tail]
        except OSError:
            pass
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def write_crash_report(exc_type, exc, tb) -> Path | None:
    """Save a crash report next to the logs; never raises."""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        path = LOGS_DIR / f"crash-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        path.write_text(f"{system_summary()}\n\n{text}", encoding="utf-8")
        _prune(LOGS_DIR, "crash-*.txt", keep=20)
        return path
    except Exception:
        return None


def _prune(folder: Path, pattern: str, keep: int) -> None:
    try:
        files = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[keep:]:
            old.unlink()
    except OSError:
        pass


def install_crash_handlers(show: Callable[[str, str], None] | None = None) -> None:
    """faulthandler (native crashes) + excepthooks for main and worker threads."""
    global _fault_file
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        _fault_file = open(LOGS_DIR / "native-crash.log", "a", encoding="utf-8")
        faulthandler.enable(file=_fault_file, all_threads=True)
    except Exception:
        pass

    def hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        path = write_crash_report(exc_type, exc, tb)
        logger.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
        if show is not None:
            try:
                where = f"\n\nA report was saved to:\n{path}" if path else ""
                show("VOLUMAX hit a problem but is still running",
                     f"{exc_type.__name__}: {exc}{where}")
            except Exception:
                pass

    sys.excepthook = hook
    try:
        import threading

        def thread_hook(args) -> None:
            hook(args.exc_type, args.exc_value, args.exc_traceback)

        threading.excepthook = thread_hook
    except Exception:
        pass
