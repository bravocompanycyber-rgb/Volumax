"""Engine facade — uses backend adapters + native ZIP helpers."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import Sequence

from .backends.base import ArchiveEntry, BackendResult
from .config import LOW_GAIN_EXTENSIONS

# Public re-exports
__all__ = ["ArchiveEntry", "BackendResult", "EngineResult", "SevenZipEngine", "create_zip_native", "extract_zip_native"]
from .backends.sevenzip import SevenZipBackend

logger = logging.getLogger("volumax.engine")

# Re-export for compatibility
EngineResult = BackendResult


class SevenZipEngine:
    """Compatibility wrapper around SevenZipBackend."""

    def __init__(self, exe_path: Path | None = None) -> None:
        self._backend = SevenZipBackend(exe_path)

    @property
    def exe(self) -> Path:
        return self._backend.exe

    def version(self) -> str:
        """First line of 7-Zip's banner, e.g. '7-Zip 23.01 (x64) : Copyright ...'."""
        import subprocess

        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            out = subprocess.run(
                [str(self.exe)], capture_output=True, text=True, timeout=10,
                stdin=subprocess.DEVNULL, creationflags=flags,
            ).stdout
            for line in out.splitlines():
                if "7-Zip" in line:
                    return line.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        return "unknown"

    def list_archive(
        self, archive: Path, password: str | None = None, detailed: bool = False
    ) -> BackendResult:
        return self._backend.list_archive(archive, password=password, detailed=detailed)

    def create_archive(self, archive: Path, sources: Sequence[Path], **kwargs) -> BackendResult:
        return self._backend.create_archive(archive, sources, **kwargs)

    def extract_archive(self, archive: Path, destination: Path, **kwargs) -> BackendResult:
        return self._backend.extract_archive(archive, destination, **kwargs)

    def test_archive(self, archive: Path, password: str | None = None, **kwargs) -> BackendResult:
        return self._backend.test_archive(archive, password=password, **kwargs)

    def convert_archive(
        self,
        source: Path,
        target: Path,
        *,
        format: str = "7z",
        level: int = 5,
        password: str | None = None,
        target_password: str | None = None,
        progress=None,
        cancel=None,
        pause=None,
        **options,
    ) -> BackendResult:
        """Re-pack ``source`` as ``target``. ``password`` opens the source;
        ``target_password`` (default: none) protects the result.

        The working folder is created NEXT TO the target (same drive as the output),
        not in the system temp folder, which is often a small system drive."""
        import shutil
        import tempfile

        def scaled(lo: int, hi: int):
            if not progress:
                return None
            return lambda pct, msg="": progress(lo + (hi - lo) * pct // 100, msg)

        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            tmp_ctx = tempfile.TemporaryDirectory(prefix=".volumax_conv_", dir=target.parent)
        except OSError:
            tmp_ctx = tempfile.TemporaryDirectory(prefix="volumax_conv_")
        with tmp_ctx as tmp:
            tmp_path = Path(tmp)
            res = self.extract_archive(
                source, tmp_path, password=password,
                progress=scaled(0, 50), cancel=cancel, pause=pause,
            )
            if not res.success:
                return res
            items = list(tmp_path.iterdir())
            if not items:
                return BackendResult(False, "Source archive was empty")
            if target.exists():
                target.unlink()
            return self.create_archive(
                target, items, format=format, level=level,
                password=target_password,
                progress=scaled(50, 100), cancel=cancel, pause=pause, **options,
            )


def create_zip_native(
    archive: Path,
    files: Sequence[tuple[Path, str]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
    compresslevel: int = 6,
    smart: bool = True,
) -> BackendResult:
    archive = Path(archive)
    archive.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(
            archive, mode="w", compression=compression,
            compresslevel=compresslevel, allowZip64=True,
        ) as zf:
            for src, arcname in files:
                src = Path(src)
                if src.is_dir():
                    if not arcname.endswith("/"):
                        arcname += "/"
                    zf.writestr(arcname, b"")
                elif smart and src.suffix.lower() in LOW_GAIN_EXTENSIONS:
                    # jpg/mp4/zip/... don't shrink: storing is much faster
                    zf.write(src, arcname, compress_type=zipfile.ZIP_STORED)
                else:
                    zf.write(src, arcname)
        size = archive.stat().st_size
        return BackendResult(True, f"Created {archive.name} ({size} bytes)", output_path=archive)
    except Exception as exc:
        if archive.exists():
            try:
                archive.unlink()
            except OSError:
                pass
        return BackendResult(False, str(exc))


def extract_zip_native(
    archive: Path,
    destination: Path,
    *,
    selected: Sequence[str] | None = None,
) -> BackendResult:
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive, "r") as zf:
            members = selected if selected else zf.namelist()
            for name in members:
                zf.extract(name, destination)
        return BackendResult(True, "Extracted successfully")
    except Exception as exc:
        return BackendResult(False, str(exc))
