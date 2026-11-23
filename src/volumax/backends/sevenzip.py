"""Official 7-Zip backend adapter."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Sequence

from ..config import find_7zip_exe
from .base import (
    ArchiveBackend,
    ArchiveEntry,
    BackendCapabilities,
    BackendResult,
    CancelCheck,
    ProgressCallback,
)

logger = logging.getLogger("volumax.backends.sevenzip")

_PERCENT_RE = re.compile(r"^\s*(\d{1,3})%")
_SPLIT_RE = re.compile(r"[\x08\r\n]+")


class SevenZipBackend(ArchiveBackend):
    def __init__(self, exe_path: Path | None = None) -> None:
        self.exe = Path(exe_path) if exe_path else find_7zip_exe()
        if self.exe is None or not self.exe.is_file():
            raise FileNotFoundError(
                "7-Zip engine not found. Place 7z.exe in engines/7zip/ "
                "or install 7-Zip system-wide."
            )
        logger.info("7-Zip backend: %s", self.exe)

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name="7-Zip",
            formats_create=("zip", "7z", "tar", "gzip", "bzip2", "xz"),
            formats_extract=("zip", "7z", "tar", "gzip", "bzip2", "xz", "rar", "cab", "iso", "wim", "001"),
            supports_password=True,
            supports_encrypt_filenames=True,
            supports_volumes=True,
            supports_solid=True,
            supports_update=True,
        )

    def _run(
        self,
        args: Sequence[str],
        *,
        progress: ProgressCallback | None = None,
        cancel: CancelCheck | None = None,
        timeout: int | None = None,
    ) -> BackendResult:
        cmd = [str(self.exe), *args]
        logger.debug("CMD: %s", " ".join(cmd))
        env = None
        lib_dir = self.exe.parent
        if (lib_dir / "7z.so").exists() or (lib_dir / "7z.dll").exists():
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = str(lib_dir) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        # Don't flash a console window on Windows
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=creationflags,
            )
        except OSError as exc:
            return BackendResult(False, f"Cannot start 7-Zip: {exc}")

        out_lines: list[str] = []
        err_lines: list[str] = []

        track = "-bsp1" in args  # only a/x/t emit progress; listings must stay raw

        def pump_stdout() -> None:
            assert proc.stdout is not None
            if not track:
                out_lines.append(proc.stdout.read())  # drains continuously
                return
            # 7-Zip redraws its progress using backspaces/CRs, so split on those.
            last = -1
            buf = ""

            def handle(part: str) -> None:
                nonlocal last
                m = _PERCENT_RE.match(part)
                if m:
                    pct = min(100, int(m.group(1)))
                    if progress and pct != last:
                        last = pct
                        try:
                            progress(pct, part.strip()[:120])
                        except Exception:  # a UI callback must never kill the pump
                            logger.exception("progress callback failed")
                elif part.strip():
                    out_lines.append(part + "\n")

            while True:
                chunk = proc.stdout.read(8192)
                if not chunk:
                    break
                parts = _SPLIT_RE.split(buf + chunk)
                buf = parts.pop()  # possibly incomplete trailing fragment
                for part in parts:
                    handle(part)
            handle(buf)

        def pump_stderr() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                err_lines.append(line)

        # Drain both pipes continuously: a full pipe buffer would block 7-Zip
        # forever on large listings/extractions.
        threads = [
            threading.Thread(target=pump_stdout, daemon=True),
            threading.Thread(target=pump_stderr, daemon=True),
        ]
        for t in threads:
            t.start()

        deadline = time.monotonic() + timeout if timeout else None
        try:
            while True:
                if cancel and cancel():
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    return BackendResult(False, "Cancelled by user", -1)
                if deadline and time.monotonic() > deadline:
                    proc.kill()
                    return BackendResult(False, f"7-Zip timed out after {timeout}s", -2)
                try:
                    proc.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            for t in threads:
                t.join(timeout=5)

        stdout = "".join(out_lines)
        stderr = "".join(err_lines)
        success = proc.returncode == 0
        msg = "OK" if success else (stderr or stdout or f"Exit {proc.returncode}").strip()
        return BackendResult(
            success=success,
            message=msg[:2000],
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def list_archive(self, archive: Path, password: str | None = None) -> BackendResult:
        args = ["l", "-slt", "-ba"]
        if password:
            args.append(f"-p{password}")
        args.append(str(archive))
        result = self._run(args)
        if result.success:
            result.entries = self._parse_list(result.stdout)
        return result

    def _parse_list(self, text: str) -> list[ArchiveEntry]:
        entries: list[ArchiveEntry] = []
        current: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line:
                if current.get("Path"):
                    entries.append(self._to_entry(current))
                current = {}
                continue
            if " = " in line:
                k, _, v = line.partition(" = ")
                current[k.strip()] = v.strip()
        if current.get("Path"):
            entries.append(self._to_entry(current))
        return entries

    @staticmethod
    def _to_entry(d: dict[str, str]) -> ArchiveEntry:
        path = d.get("Path", "").replace("\\", "/")
        attrs = d.get("Attributes", "")
        is_dir = "D" in attrs or path.endswith("/")
        return ArchiveEntry(
            path=path,
            size=int(d.get("Size") or 0),
            compressed_size=int(d.get("Packed Size") or 0),
            is_dir=is_dir,
            timestamp=d.get("Modified"),
            crc=d.get("CRC"),
            encrypted=d.get("Encrypted", "").upper() in ("+", "YES", "TRUE"),
        )

    def create_archive(
        self,
        archive: Path,
        sources: Sequence[Path],
        *,
        format: str = "7z",
        level: int = 5,
        password: str | None = None,
        encrypt_filenames: bool = False,
        solid: bool = True,
        volume_size: str | None = None,
        progress: ProgressCallback | None = None,
        cancel: CancelCheck | None = None,
    ) -> BackendResult:
        archive = Path(archive)
        archive.parent.mkdir(parents=True, exist_ok=True)
        fmt = format.replace("tar.gz", "gzip").replace("tar.bz2", "bzip2").replace("tar.xz", "xz")
        args: list[str] = ["a", f"-t{fmt}", f"-mx={level}", "-mmt=on", "-y", "-bsp1"]
        if password:
            args.append(f"-p{password}")
            if encrypt_filenames and fmt == "7z":
                args.append("-mhe=on")
            # Prefer AES-256 for ZIP (not weak ZipCrypto)
            if fmt == "zip":
                args.append("-mem=AES256")
        if not solid and fmt == "7z":
            args.append("-ms=off")
        if volume_size:
            args.append(f"-v{volume_size}")
        args.append(str(archive))
        for src in sources:
            args.append(str(src))
        result = self._run(args, progress=progress, cancel=cancel)
        if result.success:
            result.output_path = archive
        return result

    def extract_archive(
        self,
        archive: Path,
        destination: Path,
        *,
        password: str | None = None,
        selected_files: Sequence[str] | None = None,
        overwrite: bool = True,
        progress: ProgressCallback | None = None,
        cancel: CancelCheck | None = None,
    ) -> BackendResult:
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        args = ["x", "-y", "-mmt=on", "-bsp1", "-aoa" if overwrite else "-aos"]
        if password:
            args.append(f"-p{password}")
        args.extend([f"-o{destination}", str(archive)])
        if selected_files:
            args.append("--")
            args.extend(selected_files)
        return self._run(args, progress=progress, cancel=cancel)

    def test_archive(
        self,
        archive: Path,
        password: str | None = None,
        progress: ProgressCallback | None = None,
        cancel: CancelCheck | None = None,
    ) -> BackendResult:
        args = ["t", "-mmt=on", "-bsp1"]
        if password:
            args.append(f"-p{password}")
        args.append(str(archive))
        return self._run(args, progress=progress, cancel=cancel)
