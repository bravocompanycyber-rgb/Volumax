"""Official 7-Zip backend adapter."""

from __future__ import annotations

import logging
import subprocess
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
        try:
            import os
            lib_dir = self.exe.parent
            so = lib_dir / "7z.so"
            dll = lib_dir / "7z.dll"
            if so.exists() or dll.exists():
                env = os.environ.copy()
                env["LD_LIBRARY_PATH"] = str(lib_dir) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
        except OSError as exc:
            return BackendResult(False, f"Cannot start 7-Zip: {exc}")

        while True:
            if cancel and cancel():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return BackendResult(False, "Cancelled by user", -1)
            if proc.poll() is not None:
                break
            time.sleep(0.04)

        stdout, stderr = proc.communicate()
        success = proc.returncode == 0
        msg = "OK" if success else (stderr or stdout or f"Exit {proc.returncode}").strip()
        return BackendResult(
            success=success,
            message=msg[:2000],
            returncode=proc.returncode,
            stdout=stdout or "",
            stderr=stderr or "",
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
        args: list[str] = ["a", f"-t{fmt}", f"-mx={level}", "-y", "-bsp1"]
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
        args = ["x", "-y", "-aoa" if overwrite else "-aos"]
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
        args = ["t"]
        if password:
            args.append(f"-p{password}")
        args.append(str(archive))
        return self._run(args, progress=progress, cancel=cancel)
