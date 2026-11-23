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
        self, archive: Path, password: str | None = None
    ) -> EngineResult:
        return self.engine.list_archive(archive, password=password)

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
    ) -> EngineResult:
        if volume_size:
            return self.volumes.create_volumes(
                archive,
                sources,
                volume_size=volume_size,
                format=format,
                level=level,
                password=password,
                encrypt_filenames=encrypt_filenames,
            )
        return self.engine.create_archive(
            archive,
            sources,
            format=format,
            level=level,
            password=password,
            encrypt_filenames=encrypt_filenames,
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
    ) -> EngineResult:
        if safe:
            return self.extractor.extract(
                archive,
                destination,
                password=password,
                selected=selected,
                overwrite=overwrite,
            )
        return self.engine.extract_archive(
            archive,
            destination,
            password=password,
            selected_files=selected,
            overwrite=overwrite,
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
    ) -> PackagingResult:
        if max_mb is not None:
            self.packager.max_bytes = max_mb * 1024 * 1024
        return self.packager.package(sources, output_dir, base_name, base=base)

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
    ) -> EngineResult:
        return self.engine.convert_archive(
            source, target, format=format, level=level, password=password
        )
