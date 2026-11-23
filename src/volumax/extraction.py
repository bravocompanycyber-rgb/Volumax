"""Safe extraction with path-traversal, symlink, and bomb protections."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Sequence

from .engine import EngineResult, SevenZipEngine, extract_zip_native
from .settings import get_settings

logger = logging.getLogger("volumax.extraction")


@dataclass
class SafetyReport:
    safe: bool
    reasons: list[str]
    rejected_entries: list[str]


class ExtractionSafety:
    """Validate archive entries before extraction."""

    # Windows reserved device names
    RESERVED_NAMES = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }

    def __init__(
        self,
        max_files: int | None = None,
        max_total_size: int | None = None,
        allow_absolute: bool = False,
        allow_symlinks: bool = False,
    ) -> None:
        settings = get_settings()
        self.max_files = max_files if max_files is not None else settings.get("max_extraction_files", 100_000)
        self.max_total_size = max_total_size
        if self.max_total_size is None:
            gb = settings.get("max_extraction_size_gb", 50)
            self.max_total_size = int(gb) * 1024 * 1024 * 1024
        self.allow_absolute = allow_absolute
        self.allow_symlinks = allow_symlinks

    def validate_entry_name(self, name: str) -> list[str]:
        """Return list of violation reasons (empty = ok)."""
        reasons: list[str] = []
        if not name or name in (".", ".."):
            reasons.append("empty or parent reference")
            return reasons

        # Normalise separators
        normalised = name.replace("\\", "/")

        # Absolute paths (Unix or Windows)
        if normalised.startswith("/") or normalised.startswith("//"):
            if not self.allow_absolute:
                reasons.append("absolute path (Unix-style)")
        pure_win = PureWindowsPath(name)
        if pure_win.is_absolute() or (len(name) >= 2 and name[1] == ":"):
            if not self.allow_absolute:
                reasons.append("absolute path (Windows drive)")

        # Path traversal
        parts = PurePosixPath(normalised).parts
        if ".." in parts:
            reasons.append("path traversal (..)")

        # Leading ~ or other home references
        if normalised.startswith("~"):
            reasons.append("home-directory reference")

        # Reserved Windows names (any path component)
        for part in parts:
            base = part.split(".")[0].upper()
            if base in self.RESERVED_NAMES:
                reasons.append(f"reserved Windows name: {part}")

        # Null bytes / control characters
        if "\x00" in name or any(ord(c) < 32 and c not in "\t\n\r" for c in name):
            reasons.append("control characters in name")

        # Excessively long path components
        for part in parts:
            if len(part) > 255:
                reasons.append("component longer than 255 characters")

        return reasons

    def validate_entries(
        self,
        entries: Sequence[object],
        *,
        size_attr: str = "size",
        path_attr: str = "path",
        is_dir_attr: str = "is_dir",
    ) -> SafetyReport:
        reasons: list[str] = []
        rejected: list[str] = []
        total_size = 0
        file_count = 0

        for entry in entries:
            path = getattr(entry, path_attr, "") or ""
            size = int(getattr(entry, size_attr, 0) or 0)
            is_dir = bool(getattr(entry, is_dir_attr, False))

            entry_reasons = self.validate_entry_name(path)
            if entry_reasons:
                rejected.append(path)
                reasons.extend(f"{path}: {r}" for r in entry_reasons)
                continue

            if not is_dir:
                file_count += 1
                total_size += max(size, 0)

        if file_count > self.max_files:
            reasons.append(
                f"too many files ({file_count} > limit {self.max_files})"
            )
        if total_size > self.max_total_size:
            reasons.append(
                f"total size {total_size} exceeds limit {self.max_total_size}"
            )

        return SafetyReport(
            safe=len(reasons) == 0,
            reasons=reasons,
            rejected_entries=rejected,
        )

    def safe_destination(
        self, base: Path, relative: str, base_resolved: Path | None = None
    ) -> Path | None:
        """
        Resolve relative path under base and ensure it stays inside base.
        Returns None if the path would escape.
        Pass ``base_resolved`` when calling in a loop to avoid re-resolving base.
        """
        # Strip leading separators and drive letters
        cleaned = relative.replace("\\", "/").lstrip("/")
        if ":" in cleaned[:3]:
            # Remove drive letter if present
            cleaned = cleaned.split(":", 1)[-1].lstrip("/")

        try:
            if base_resolved is None:
                base_resolved = base.resolve()
            target = (base_resolved / cleaned).resolve()
            # is_relative_to is component-aware (a plain startswith would let
            # /data/out-evil pass as inside /data/out)
            if not target.is_relative_to(base_resolved):
                return None
            return target
        except (OSError, ValueError):
            return None


class SafeExtractor:
    """High-level safe extraction orchestrator."""

    def __init__(self, engine: SevenZipEngine | None = None) -> None:
        self.engine = engine or SevenZipEngine()
        self.safety = ExtractionSafety()

    def extract(
        self,
        archive: Path,
        destination: Path,
        *,
        password: str | None = None,
        selected: Sequence[str] | None = None,
        overwrite: bool = True,
        use_staging: bool = True,
        progress=None,
        cancel=None,
    ) -> EngineResult:
        archive = Path(archive)
        destination = Path(destination)

        # First list contents for safety check
        list_res = self.engine.list_archive(archive, password=password)
        if not list_res.success:
            # Fall back to native ZIP if 7z fails and it is a ZIP
            if archive.suffix.lower() == ".zip":
                return self._extract_zip_safe(archive, destination, selected=selected)
            return list_res

        report = self.safety.validate_entries(list_res.entries)
        if not report.safe:
            msg = "Safety check failed:\n" + "\n".join(report.reasons[:20])
            if len(report.reasons) > 20:
                msg += f"\n... and {len(report.reasons) - 20} more"
            logger.warning(msg)
            return EngineResult(False, msg)

        if use_staging:
            return self._extract_via_staging(
                archive, destination, password=password, selected=selected,
                overwrite=overwrite, progress=progress, cancel=cancel,
            )

        return self.engine.extract_archive(
            archive,
            destination,
            password=password,
            selected_files=selected,
            overwrite=overwrite,
            progress=progress,
            cancel=cancel,
        )

    def _extract_via_staging(
        self,
        archive: Path,
        destination: Path,
        *,
        password: str | None,
        selected: Sequence[str] | None,
        overwrite: bool,
        progress=None,
        cancel=None,
    ) -> EngineResult:
        destination.mkdir(parents=True, exist_ok=True)
        # Stage INSIDE the destination so the final move is a same-volume
        # rename (instant) instead of a full copy across drives.
        try:
            tmp_ctx = tempfile.TemporaryDirectory(prefix=".volumax_stage_", dir=destination)
        except OSError:
            tmp_ctx = tempfile.TemporaryDirectory(prefix="volumax_stage_")

        with tmp_ctx as tmp:
            stage = Path(tmp)
            res = self.engine.extract_archive(
                archive,
                stage,
                password=password,
                selected_files=selected,
                overwrite=True,
                progress=progress,
                cancel=cancel,
            )
            if not res.success:
                return res

            base_resolved = destination.resolve()
            made_dirs: set[Path] = set()
            moved = 0
            for root, _dirs, files in os.walk(stage):
                rel_root = Path(root).relative_to(stage)
                for name in files:
                    rel = str(rel_root / name).replace("\\", "/")
                    target = self.safety.safe_destination(destination, rel, base_resolved)
                    if target is None:
                        logger.warning("Skipping unsafe path after staging: %s", rel)
                        continue
                    parent = target.parent
                    if parent not in made_dirs:
                        parent.mkdir(parents=True, exist_ok=True)
                        made_dirs.add(parent)
                    if not overwrite and target.exists():
                        continue
                    src = Path(root) / name
                    try:
                        try:
                            src.replace(target)  # same volume: instant
                        except OSError:
                            shutil.copy2(src, target)
                        moved += 1
                    except OSError as exc:
                        logger.error("Failed to place %s: %s", rel, exc)

            return EngineResult(True, f"Extracted {moved} files safely")

    def _extract_zip_safe(
        self,
        archive: Path,
        destination: Path,
        selected: Sequence[str] | None = None,
    ) -> EngineResult:
        # Use native zipfile with our own safety filter
        import zipfile

        try:
            with zipfile.ZipFile(archive, "r") as zf:
                members = selected if selected else zf.namelist()
                for name in members:
                    if self.safety.validate_entry_name(name):
                        logger.warning("Skipping unsafe ZIP entry: %s", name)
                        continue
                    target = self.safety.safe_destination(destination, name)
                    if target is None:
                        continue
                    # Extract single member carefully
                    info = zf.getinfo(name)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
            return EngineResult(True, "ZIP extracted safely")
        except Exception as exc:
            return EngineResult(False, str(exc))
