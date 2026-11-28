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


def _machine(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
        off = int.from_bytes(head[0x3C:0x40], "little")
        m = int.from_bytes(head[off + 4: off + 6], "little")
        return {0x14C: "x86", 0x8664: "x64", 0xAA64: "arm64"}.get(m, hex(m))
    except Exception:
        return "?"


def engine_diagnostics() -> str:
    """What the packaged engine looks like and what it says (used when a check fails)."""
    import subprocess

    from .config import find_7zip_exe

    lines: List[str] = []
    exe = find_7zip_exe()
    lines.append(f"engine exe: {exe}")
    if exe is None:
        return "\n".join(lines)
    for p in sorted(Path(exe).parent.glob("*")):
        try:
            lines.append(f"  {p.name:16s} {p.stat().st_size:>10,d} bytes  {_machine(p) if p.suffix.lower() in ('.exe', '.dll') else ''}")
        except OSError:
            pass
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run([str(exe), "i"], capture_output=True, text=True, timeout=30,
                             stdin=subprocess.DEVNULL, creationflags=flags)
        lines.append("`7z i` (formats the engine can load):")
        lines.append((out.stdout + out.stderr).strip()[:1200])
    except Exception as exc:  # noqa: BLE001
        lines.append(f"could not run 7z i: {exc}")
    return "\n".join(lines)


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

    def health():
        from . import selfheal

        bad = [c.name for c in selfheal.run_checks() if not c.ok and not c.warn]
        if bad:
            raise RuntimeError("health checks failed: " + ", ".join(bad))
        return "engine/settings/folders healthy"

    def extras_check():
        from . import extras
        from .archive_manager import ArchiveManager

        mgr = ArchiveManager()
        with tempfile.TemporaryDirectory(prefix="volumax_selftest_") as tmp:
            t = Path(tmp)
            (t / "d").mkdir()
            (t / "d" / "n.txt").write_text("preview me " * 50)
            arc = t / "e.zip"
            if not mgr.create(arc, [t / "d"], format="zip").success:
                raise RuntimeError("create failed")
            ok_, note = extras.verify_created(mgr, arc, sidecar=True)
            if not ok_ or not extras.verify_sha256_sidecar(arc)[0]:
                raise RuntimeError(f"verify/checksum: {note}")
            member = next(e.path for e in mgr.list_contents(arc).entries if e.path.endswith("n.txt"))
            pv = extras.preview_member(mgr, arc, member)
            try:
                if pv.kind != "text" or "preview me" not in pv.text:
                    raise RuntimeError(f"preview: {pv.kind} {pv.text[:60]}")
            finally:
                pv.cleanup()
            if not extras.compare_archives(mgr, arc, arc).identical:
                raise RuntimeError("compare")
        return "verify, checksum, preview, compare"

    def smallpack_check():
        from . import smallpack

        if not smallpack.available():
            return "skipped (optional 'zstandard' not installed)"
        with tempfile.TemporaryDirectory(prefix="volumax_selftest_") as tmp:
            t = Path(tmp)
            (t / "s").mkdir()
            for i in range(20):
                (t / "s" / f"{i}.log").write_text(f"line {i} " * 40)
            r = smallpack.create_pack([t / "s"], t / "p.vxsp")
            e = smallpack.extract_pack(t / "p.vxsp", t / "o")
            if not (r.success and e.success and (t / "o" / "s" / "7.log").is_file()):
                raise RuntimeError(f"{r.message} / {e.message}")
        return "zstandard small-file pack round-trip"

    def vault_check():
        from . import vault as vlt

        if not vlt.AVAILABLE:
            raise RuntimeError("PyNaCl/libsodium is missing from this build")
        with tempfile.TemporaryDirectory(prefix="volumax_selftest_") as tmp:
            t = Path(tmp)
            (t / "s").mkdir()
            (t / "s" / "a.txt").write_text("vault self-test " * 50)
            dest = t / "v.jpg"                       # extension is irrelevant on purpose
            vlt.create_vault(dest, [t / "s"], vlt.CreateOptions(
                vlt.Secret("passphrase", "selftest passphrase"), ops=1, mem_kib=8192))
            if not vlt.sniff(dest):
                raise RuntimeError("signature not recognised")
            try:
                vlt.unlock(dest, vlt.Secret("passphrase", "wrong passphrase!"))
                raise RuntimeError("a wrong secret was accepted")
            except vlt.WrongSecret:
                pass
            with vlt.unlock(dest, vlt.Secret("passphrase", "selftest passphrase")) as s:
                if s.extract(t / "o") != 1 or s.read_member("s/a.txt")[:5] != b"vault":
                    raise RuntimeError("round trip failed")
        return "libsodium: Argon2id + XChaCha20-Poly1305 round-trip"

    ok.append(_check(checks, "health", health))
    ok.append(_check(checks, "vault", vault_check))
    ok.append(_check(checks, "extras", extras_check))
    ok.append(_check(checks, "smallpack", smallpack_check))

    if not all(ok):
        try:
            checks["engine_diag"] = engine_diagnostics()
        except Exception as exc:  # noqa: BLE001
            checks["engine_diag"] = f"diagnostics failed: {exc}"
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
