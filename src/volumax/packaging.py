"""Independent ZIP packaging — each package is fully extractable alone."""

from __future__ import annotations

import logging
import os
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .config import LOW_GAIN_EXTENSIONS
from .engine import EngineResult, create_zip_native
from .settings import get_settings

logger = logging.getLogger("volumax.packaging")


@dataclass
class FileItem:
    source: Path
    arcname: str
    size: int  # uncompressed size
    cost: int | None = None  # bytes this file will occupy inside the ZIP (measured)

    @property
    def weight(self) -> int:
        return self.size if self.cost is None else self.cost


@dataclass
class PackagePlan:
    """One independent ZIP that will be produced."""
    index: int
    files: list[FileItem] = field(default_factory=list)
    estimated_size: int = 0  # sum of source sizes (upper bound)
    output_path: Path | None = None
    actual_size: int = 0
    error: str | None = None
    names: set[str] = field(default_factory=set, repr=False)  # arcname index


@dataclass
class PackagingResult:
    success: bool
    packages: list[PackagePlan] = field(default_factory=list)
    message: str = ""
    skipped: list[tuple[Path, str]] = field(default_factory=list)  # (path, reason)


class IndependentZipPackager:
    """
    Create multiple independent ZIP files, each under a hard size limit.

    Rules:
    - Every ZIP must be independently extractable.
    - Size is measured on the *actual* output file, not the source estimate.
    - Files larger than the limit are reported and never placed in a package.
    - Folder structure is preserved via arcnames.
    - Filename collisions inside a single package are detected.
    """

    def __init__(
        self,
        max_bytes: int | None = None,
        ceiling_bytes: int | None = None,
        compresslevel: int = 9,
    ) -> None:
        settings = get_settings()
        if max_bytes is None:
            max_bytes = settings.independent_zip_max_mb * 1024 * 1024
        if ceiling_bytes is None:
            ceil_mb = settings.independent_zip_ceiling_mb
            # 0 or negative = no absolute ceiling beyond max_bytes
            ceiling_bytes = (ceil_mb * 1024 * 1024) if ceil_mb and ceil_mb > 0 else max_bytes
        self.max_bytes = max(1, int(max_bytes))
        self.ceiling_bytes = max(self.max_bytes, int(ceiling_bytes)) if ceiling_bytes else self.max_bytes
        self.compresslevel = compresslevel

    def collect_files(
        self,
        sources: Sequence[Path],
        *,
        base: Path | None = None,
    ) -> list[FileItem]:
        """Walk sources and produce flat list of FileItems with relative arcnames."""
        items: list[FileItem] = []
        for src in sources:
            src = Path(src)
            if not src.exists():
                logger.warning("Source does not exist: %s", src)
                continue
            if src.is_file():
                arc = src.name if base is None else str(src.relative_to(base)).replace("\\", "/")
                items.append(FileItem(src, arc, src.stat().st_size))
            else:
                root = src if base is None else base
                for dirpath, dirnames, filenames in os.walk(src):
                    # Preserve empty directories
                    rel_dir = Path(dirpath).relative_to(root)
                    if not filenames and not dirnames:
                        arc = str(rel_dir).replace("\\", "/") + "/"
                        items.append(FileItem(Path(dirpath), arc, 0))
                    for fn in filenames:
                        full = Path(dirpath) / fn
                        arc = str(full.relative_to(root)).replace("\\", "/")
                        try:
                            size = full.stat().st_size
                        except OSError:
                            size = 0
                        items.append(FileItem(full, arc, size))
        return items

    # ZIP container overhead per entry (local + central header, ZIP64 slack) and per archive
    @staticmethod
    def _entry_overhead(arcname: str) -> int:
        return 76 + 2 * len(arcname.encode("utf-8")) + 24

    ARCHIVE_OVERHEAD = 22 + 56 + 20 + 512  # end records + safety margin

    def _measure_one(self, item: FileItem) -> None:
        """Exact deflate size using the same zlib parameters zipfile uses."""
        overhead = self._entry_overhead(item.arcname)
        if item.arcname.endswith("/") or item.size == 0:
            item.cost = overhead
            return
        if item.source.suffix.lower() in LOW_GAIN_EXTENSIONS:
            item.cost = item.size + overhead  # written STORED
            return
        try:
            comp = zlib.compressobj(self.compresslevel, zlib.DEFLATED, -15)
            total = 0
            with open(item.source, "rb") as f:
                while chunk := f.read(1024 * 1024):
                    total += len(comp.compress(chunk))
            total += len(comp.flush())
            # zipfile falls back to the raw size cost bound for incompressible data
            item.cost = total + overhead
        except OSError:
            item.cost = item.size + overhead

    def measure(self, items: list[FileItem], progress=None, cancel=None) -> None:
        """Measure every file's real compressed size in parallel (zlib releases the GIL)."""
        done = 0
        with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 2))) as pool:
            for _ in pool.map(self._measure_one, items):
                done += 1
                if progress and done % 25 == 0:
                    progress(done * 40 // max(1, len(items)), "Measuring compressed sizes…")
                if cancel and cancel():
                    break

    def plan(
        self,
        sources: Sequence[Path],
        output_dir: Path,
        base_name: str = "package",
        *,
        base: Path | None = None,
        measure: bool = True,
        progress=None,
        cancel=None,
    ) -> PackagingResult:
        """Build a packaging plan without writing files yet.

        With ``measure=True`` (default) packages are filled according to each file's
        true *compressed* size, so every ZIP is as close to the limit as possible
        instead of being filled with limit-worth of *uncompressed* data.
        """
        items = self.collect_files(sources, base=base)
        if not items:
            return PackagingResult(False, message="No files to package")
        if measure:
            self.measure(items, progress, cancel)

        skipped: list[tuple[Path, str]] = []
        usable: list[FileItem] = []

        for item in items:
            if item.weight > self.ceiling_bytes:
                skipped.append(
                    (
                        item.source,
                        f"File size {item.weight} exceeds absolute ceiling "
                        f"{self.ceiling_bytes} ({self.ceiling_bytes // (1024*1024)} MB)",
                    )
                )
            elif item.weight + self.ARCHIVE_OVERHEAD > self.max_bytes:
                skipped.append(
                    (
                        item.source,
                        f"File size {item.weight} exceeds package limit "
                        f"{self.max_bytes} ({self.max_bytes // (1024*1024)} MB). "
                        "Raise the limit or exclude this file.",
                    )
                )
            else:
                usable.append(item)

        if not usable and skipped:
            return PackagingResult(
                False,
                message="All files exceed the size limit",
                skipped=skipped,
            )

        # Greedy bin-packing: first-fit decreasing
        usable.sort(key=lambda x: x.weight, reverse=True)
        packages: list[PackagePlan] = []

        for item in usable:
            placed = False
            for pkg in packages:
                # Cheap size check first, then O(1) name-collision check
                if pkg.estimated_size + item.weight > self.max_bytes:
                    continue
                if item.arcname in pkg.names:
                    stem, ext = os.path.splitext(item.arcname)
                    candidate = item.arcname
                    n = 1
                    while candidate in pkg.names:
                        candidate = f"{stem}_{n}{ext}"
                        n += 1
                    item = FileItem(item.source, candidate, item.size, item.cost)
                pkg.files.append(item)
                pkg.names.add(item.arcname)
                pkg.estimated_size += item.weight
                placed = True
                break

            if not placed:
                idx = len(packages) + 1
                out = output_dir / f"{base_name}_{idx:03d}.zip"
                packages.append(
                    PackagePlan(
                        index=idx, files=[item],
                        estimated_size=self.ARCHIVE_OVERHEAD + item.weight,
                        output_path=out, names={item.arcname},
                    )
                )

        return PackagingResult(True, packages=packages, skipped=skipped)

    def execute(
        self,
        plan: PackagingResult,
        *,
        dry_run: bool = False,
        progress=None,
        cancel=None,
    ) -> PackagingResult:
        """
        Create the ZIP files described by the plan.
        After each ZIP is written, its actual size is checked.
        Oversized packages are deleted and marked with an error.
        """
        if not plan.success or not plan.packages:
            return plan

        if dry_run:
            return plan

        total = len(plan.packages)
        for n, pkg in enumerate(plan.packages):
            if cancel and cancel():
                plan.success = False
                plan.message = "Cancelled"
                return plan
            if progress:
                progress(40 + 60 * n // max(1, total), f"Writing {pkg.output_path.name if pkg.output_path else ''}")
            if not pkg.output_path:
                continue
            pairs = [(f.source, f.arcname) for f in pkg.files]
            result = create_zip_native(
                pkg.output_path,
                pairs,
                compresslevel=self.compresslevel,
            )
            if not result.success:
                pkg.error = result.message
                plan.success = False
                continue

            actual = pkg.output_path.stat().st_size
            pkg.actual_size = actual

            if actual > self.max_bytes:
                # Hard failure — never silently ship an oversized package
                try:
                    pkg.output_path.unlink()
                except OSError:
                    pass
                pkg.error = (
                    f"Actual ZIP size {actual} exceeds limit {self.max_bytes}. "
                    "Package deleted. Try a higher limit or fewer/smaller files."
                )
                plan.success = False
                logger.error(pkg.error)
            else:
                logger.info(
                    "Created %s (%d bytes, %d files)",
                    pkg.output_path.name,
                    actual,
                    len(pkg.files),
                )

        if any(p.error for p in plan.packages):
            plan.message = "One or more packages failed size verification"
            plan.success = False
        else:
            plan.message = f"Created {len(plan.packages)} independent package(s)"
            plan.success = True

        return plan

    def package(
        self,
        sources: Sequence[Path],
        output_dir: Path,
        base_name: str = "package",
        *,
        base: Path | None = None,
        progress=None,
        cancel=None,
    ) -> PackagingResult:
        """Plan + execute in one call."""
        plan = self.plan(sources, output_dir, base_name, base=base, progress=progress, cancel=cancel)
        if not plan.success:
            return plan
        return self.execute(plan, progress=progress, cancel=cancel)
