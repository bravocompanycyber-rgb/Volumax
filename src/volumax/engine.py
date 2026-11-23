"""Engine facade — uses backend adapters + native ZIP helpers."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import Sequence

from .backends.base import ArchiveEntry, BackendResult

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

    def list_archive(self, archive: Path, password: str | None = None) -> BackendResult:
        return self._backend.list_archive(archive, password=password)

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
        progress=None,
        cancel=None,
    ) -> BackendResult:
        import tempfile
        with tempfile.TemporaryDirectory(prefix="volumax_conv_") as tmp:
            tmp_path = Path(tmp)
            res = self.extract_archive(source, tmp_path, password=password, progress=progress, cancel=cancel)
            if not res.success:
                return res
            items = list(tmp_path.iterdir())
            if not items:
                return BackendResult(False, "Source archive was empty")
            return self.create_archive(
                target, items, format=format, level=level, password=password,
                progress=progress, cancel=cancel,
            )


def create_zip_native(
    archive: Path,
    files: Sequence[tuple[Path, str]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
    compresslevel: int = 6,
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
