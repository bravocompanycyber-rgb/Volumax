"""Built-in self test: `VOLUMAX.exe --selftest REPORT.json`.

The build runs this against every finished executable, so a package with a missing DLL,
Qt plugin, bundled 7-Zip or asset fails the BUILD instead of failing on a customer's PC.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Callable, Dict, List


def _check(results: Dict[str, str], name: str, fn: Callable[[], object]) -> bool:
    try:
        detail = fn()
        results[name] = "ok" + (f": {detail}" if detail else "")
        return True
    except Exception as exc:  # noqa: BLE001
        results[name] = f"FAILED: {exc.__class__.__name__}: {exc}"
        results[name + ".trace"] = traceback.format_exc()
        return False


def run(report_path: str) -> int:
    from . import QT_BINDING, __version__
    from .config import ASSETS_DIR, ENGINES_DIR, PROJECT_ROOT, find_7zip_exe

    checks: Dict[str, str] = {}
    ok: List[bool] = []

    def qt_modules():
        import importlib

        for m in ("QtCore", "QtGui", "QtWidgets", "QtNetwork"):
            importlib.import_module(f"PySide6.{m}")
        return QT_BINDING

    def assets():
        for rel in ("logo.ico", "logo.png"):
            if not (ASSETS_DIR / rel).is_file():
                raise FileNotFoundError(ASSETS_DIR / rel)
        return str(ASSETS_DIR)

    def engine_bundled():
        # In a frozen build the engine MUST come from the bundle, not from the machine.
        exe = find_7zip_exe()
        if exe is None:
            raise FileNotFoundError("7-Zip not found")
        if getattr(sys, "frozen", False):
            inside = Path(exe).resolve().is_relative_to(Path(PROJECT_ROOT).resolve()) if hasattr(
                Path, "is_relative_to") else str(exe).startswith(str(PROJECT_ROOT))
            bundled_names = [p.name for p in (ENGINES_DIR / "7zip").glob("*")] if (ENGINES_DIR / "7zip").is_dir() else []
            if not bundled_names:
                raise FileNotFoundError(f"no engines/7zip in bundle ({ENGINES_DIR})")
            if os.name == "nt" and not inside:
                raise RuntimeError(f"using a system 7-Zip instead of the bundled one: {exe}")
        return str(exe)

    def roundtrip():
        from .archive_manager import ArchiveManager

        mgr = ArchiveManager()
        with tempfile.TemporaryDirectory(prefix="volumax_selftest_") as tmp:
            t = Path(tmp)
            (t / "src").mkdir()
            (t / "src" / "é ü 日本.txt").write_text("selftest " * 500, encoding="utf-8")
            for fmt in ("7z", "zip"):
                arc = t / f"a.{fmt}"
                res = mgr.create(arc, [t / "src"], format=fmt)
                if not res.success:
                    raise RuntimeError(f"create {fmt}: {res.message}")
                lst = mgr.list_contents(arc)
                if not lst.success or not any("日本" in e.path for e in lst.entries):
                    raise RuntimeError(f"list {fmt}: unicode name lost ({lst.message})")
                if not mgr.test_integrity(arc).success:
                    raise RuntimeError(f"test {fmt} failed")
                out = t / f"out_{fmt}"
                res = mgr.extract(arc, out)
                if not res.success or not (out / "src" / "é ü 日本.txt").is_file():
                    raise RuntimeError(f"extract {fmt}: {res.message}")
        return "7z+zip create/list/test/extract"

    def gui():
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([sys.argv[0]])
        from .ui.main_window import MainWindow

        w = MainWindow()
        w.show()
        for key in list(w.pages):
            w.goto(key)
            app.processEvents()
        w.close()
        return f"{len(w.pages)} pages"

    ok.append(_check(checks, "qt_modules", qt_modules))
    ok.append(_check(checks, "assets", assets))
    ok.append(_check(checks, "engine", engine_bundled))
    ok.append(_check(checks, "archive_roundtrip", roundtrip))
    ok.append(_check(checks, "main_window", gui))

    report = {
        "ok": all(ok),
        "version": __version__,
        "binding": QT_BINDING,
        "python": platform.python_version(),
        "machine": platform.machine(),
        "system": f"{platform.system()} {platform.release()}",
        "frozen": bool(getattr(sys, "frozen", False)),
        "project_root": str(PROJECT_ROOT),
        "checks": checks,
    }
    Path(report_path).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if report["ok"] else 1
