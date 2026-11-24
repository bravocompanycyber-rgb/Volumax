"""High-level archive operations facade."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from .engine import ArchiveEntry, EngineResult, SevenZipEngine
from .backends.base import BackendResult
from .extraction import SafeExtractor
from .integrity import IntegrityChecker
from .packaging import IndependentZipPackager, PackagingResult
from .volume_manager import VolumeManager

logger = logging.getLogger("volumax.archive_manager")


class ArchiveManager:
    """Unified API used by the GUI and CLI."""

    def __init__(self) -> None:
        self.engine = SevenZipEngine()
        self.extractor = SafeExtractor(self.engine)
        self.volumes = VolumeManager(self.engine)
        self.integrity = IntegrityChecker(self.engine)
        self.packager = IndependentZipPackager()

    # ---- Inspection -------------------------------------------------------

    def list_contents(
        self, archive: Path, password: str | None = None, detailed: bool = False
    ) -> EngineResult:
        return self.engine.list_archive(archive, password=password, detailed=detailed)

    # ---- Create -----------------------------------------------------------

    def create(
        self,
        archive: Path,
        sources: Sequence[Path],
        *,
        format: str = "7z",
        level: int = 5,
        password: str | None = None,
        encrypt_filenames: bool = False,
        volume_size: str | None = None,
        progress=None,
        cancel=None,
        **options,
    ) -> EngineResult:
        """``options``: preset, solid, threads, smart, dictionary_mb, max_dictionary_mb, pause."""
        return self.engine.create_archive(
            archive,
            sources,
            format=format,
            level=level,
            password=password,
            encrypt_filenames=encrypt_filenames,
            volume_size=volume_size,
            progress=progress,
            cancel=cancel,
            **options,
        )

    # ---- Extract ----------------------------------------------------------

    def extract(
        self,
        archive: Path,
        destination: Path,
        *,
        password: str | None = None,
        selected: Sequence[str] | None = None,
        overwrite: bool = True,
        safe: bool = True,
        progress=None,
        cancel=None,
        pause=None,
    ) -> EngineResult:
        if safe:
            return self.extractor.extract(
                archive,
                destination,
                password=password,
                selected=selected,
                overwrite=overwrite,
                progress=progress,
                cancel=cancel,
                pause=pause,
            )
        return self.engine.extract_archive(
            archive,
            destination,
            password=password,
            selected_files=selected,
            overwrite=overwrite,
            progress=progress,
            cancel=cancel,
            pause=pause,
        )

    # ---- Independent packages ---------------------------------------------

    def create_independent_packages(
        self,
        sources: Sequence[Path],
        output_dir: Path,
        base_name: str = "package",
        *,
        max_mb: int | None = None,
        base: Path | None = None,
        progress=None,
        cancel=None,
    ) -> PackagingResult:
        if max_mb is not None:
            self.packager.max_bytes = max_mb * 1024 * 1024
            self.packager.ceiling_bytes = max(self.packager.ceiling_bytes, self.packager.max_bytes)
        result = self.packager.package(
            sources, output_dir, base_name, base=base, progress=progress, cancel=cancel
        )
        if result.skipped:
            names = ", ".join(p.name for p, _ in result.skipped[:5])
            more = f" (+{len(result.skipped) - 5} more)" if len(result.skipped) > 5 else ""
            result.message += f" — {len(result.skipped)} file(s) too large and skipped: {names}{more}"
        return result

    # ---- Integrity --------------------------------------------------------

    def test_integrity(
        self, path: Path, password: str | None = None
    ) -> EngineResult:
        return self.integrity.test(path, password=password)

    # ---- Conversion -------------------------------------------------------

    def convert(
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
    ) -> EngineResult:
        return self.engine.convert_archive(
            source, target, format=format, level=level, password=password,
            target_password=target_password, progress=progress, cancel=cancel,
            pause=pause, **options,
        )
