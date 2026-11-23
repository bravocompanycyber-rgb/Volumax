"""Multipart / split-volume archive management using 7-Zip."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .engine import EngineResult, SevenZipEngine

logger = logging.getLogger("volumax.volume")


VOLUME_PATTERN = re.compile(
    r"^(?P<stem>.+)\.(?P<ext>7z|zip|rar)\.(?P<num>\d{3,})$",
    re.IGNORECASE,
)


@dataclass
class VolumeSet:
    """Represents a set of split volumes that form one logical archive."""
    base_name: str
    extension: str
    volumes: list[Path] = field(default_factory=list)
    missing: list[int] = field(default_factory=list)
    complete: bool = False

    @property
    def first_volume(self) -> Path | None:
        return self.volumes[0] if self.volumes else None

    @property
    def total_size(self) -> int:
        return sum(v.stat().st_size for v in self.volumes if v.exists())


def discover_volumes(path: Path) -> VolumeSet | None:
    """
    Given any path that looks like part of a multi-volume set,
    discover the full sequence.
    """
    path = Path(path)
    name = path.name
    m = VOLUME_PATTERN.match(name)
    if not m:
        # Also accept plain .001 without intermediate extension
        m2 = re.match(r"^(?P<stem>.+)\.(?P<num>\d{3,})$", name, re.I)
        if not m2:
            return None
        stem = m2.group("stem")
        ext = ""
        num = int(m2.group("num"))
    else:
        stem = m.group("stem")
        ext = m.group("ext")
        num = int(m.group("num"))

    parent = path.parent
    volumes: list[Path] = []
    missing: list[int] = []

    # Scan for consecutive parts starting at 001
    idx = 1
    while True:
        if ext:
            candidate = parent / f"{stem}.{ext}.{idx:03d}"
        else:
            candidate = parent / f"{stem}.{idx:03d}"
        if candidate.exists():
            volumes.append(candidate)
            idx += 1
        else:
            # Allow a gap only if we haven't found any yet? No — stop at first gap
            if volumes:
                # Check a few more in case of non-contiguous naming (rare)
                found_later = False
                for extra in range(idx + 1, idx + 5):
                    if ext:
                        c = parent / f"{stem}.{ext}.{extra:03d}"
                    else:
                        c = parent / f"{stem}.{extra:03d}"
                    if c.exists():
                        missing.append(idx)
                        volumes.append(c)
                        idx = extra + 1
                        found_later = True
                        break
                if not found_later:
                    break
            else:
                break

    complete = len(missing) == 0 and len(volumes) > 0
    return VolumeSet(
        base_name=stem,
        extension=ext,
        volumes=volumes,
        missing=missing,
        complete=complete,
    )


class VolumeManager:
    """Create and verify multipart archives."""

    def __init__(self, engine: SevenZipEngine | None = None) -> None:
        self.engine = engine or SevenZipEngine()

    def create_volumes(
        self,
        archive_base: Path,
        sources: Sequence[Path],
        *,
        volume_size: str = "100m",
        format: str = "7z",
        level: int = 5,
        password: str | None = None,
        encrypt_filenames: bool = False,
    ) -> EngineResult:
        """
        Create a multipart archive.
        archive_base should be the stem, e.g. /path/Backup.7z
        7-Zip will produce Backup.7z.001, Backup.7z.002, ...
        """
        archive_base = Path(archive_base)
        # Ensure the base ends with the correct extension for 7-Zip
        if format == "7z" and not str(archive_base).lower().endswith(".7z"):
            archive_base = archive_base.with_suffix(".7z")
        elif format == "zip" and not str(archive_base).lower().endswith(".zip"):
            archive_base = archive_base.with_suffix(".zip")

        result = self.engine.create_archive(
            archive_base,
            sources,
            format=format,
            level=level,
            password=password,
            encrypt_filenames=encrypt_filenames,
            volume_size=volume_size,
        )
        if result.success:
            # Discover what was actually created
            vs = discover_volumes(Path(str(archive_base) + ".001"))
            if vs is None:
                # Sometimes 7-Zip creates the first volume without .001 when small
                if archive_base.exists():
                    result.message = (
                        f"Created single-volume archive {archive_base.name} "
                        "(content fit in one volume)"
                    )
                    result.output_path = archive_base
                else:
                    result.success = False
                    result.message = "Volumes were not found after creation"
            else:
                result.message = (
                    f"Created {len(vs.volumes)} volume(s), total "
                    f"{vs.total_size} bytes. All parts are required for extraction."
                )
                result.output_path = vs.first_volume
        return result

    def verify_volumes(self, any_volume: Path) -> EngineResult:
        vs = discover_volumes(any_volume)
        if vs is None:
            return EngineResult(False, "Not recognised as a multi-volume set")

        if not vs.complete:
            return EngineResult(
                False,
                f"Incomplete set: missing volume indices {vs.missing}. "
                f"Found {len(vs.volumes)} volume(s).",
            )

        # Test the archive using the first volume
        first = vs.first_volume
        if first is None:
            return EngineResult(False, "No volumes found")

        test = self.engine.test_archive(first)
        if test.success:
            test.message = (
                f"Volume set OK: {len(vs.volumes)} parts, "
                f"{vs.total_size} bytes total. Archive integrity verified."
            )
        return test

    def extract_volumes(
        self,
        any_volume: Path,
        destination: Path,
        *,
        password: str | None = None,
    ) -> EngineResult:
        vs = discover_volumes(any_volume)
        if vs is None:
            return EngineResult(False, "Not recognised as a multi-volume set")
        if not vs.complete:
            return EngineResult(
                False,
                f"Cannot extract: missing volumes {vs.missing}. "
                "All parts are required.",
            )
        first = vs.first_volume
        assert first is not None
        return self.engine.extract_archive(first, destination, password=password)
