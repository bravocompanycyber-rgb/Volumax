"""Independent ZIP packaging — each package is fully extractable alone."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .engine import EngineResult, create_zip_native
from .settings import get_settings

logger = logging.getLogger("volumax.packaging")


@dataclass
class FileItem:
    source: Path
    arcname: str
    size: int  # uncompressed size


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
        compresslevel: int = 6,
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

    def plan(
        self,
        sources: Sequence[Path],
        output_dir: Path,
        base_name: str = "package",
        *,
        base: Path | None = None,
    ) -> PackagingResult:
        """Build a packaging plan without writing files yet."""
        items = self.collect_files(sources, base=base)
        if not items:
            return PackagingResult(False, message="No files to package")

        skipped: list[tuple[Path, str]] = []
        usable: list[FileItem] = []

        for item in items:
            if item.size > self.ceiling_bytes:
                skipped.append(
                    (
                        item.source,
                        f"File size {item.size} exceeds absolute ceiling "
                        f"{self.ceiling_bytes} ({self.ceiling_bytes // (1024*1024)} MB)",
                    )
                )
            elif item.size > self.max_bytes:
                skipped.append(
                    (
                        item.source,
                        f"File size {item.size} exceeds package limit "
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
        usable.sort(key=lambda x: x.size, reverse=True)
        packages: list[PackagePlan] = []

        for item in usable:
            placed = False
            for pkg in packages:
                # Cheap size check first, then O(1) name-collision check
                if pkg.estimated_size + item.size > self.max_bytes:
                    continue
                if item.arcname in pkg.names:
                    stem, ext = os.path.splitext(item.arcname)
                    candidate = item.arcname
                    n = 1
                    while candidate in pkg.names:
                        candidate = f"{stem}_{n}{ext}"
                        n += 1
                    item = FileItem(item.source, candidate, item.size)
                pkg.files.append(item)
                pkg.names.add(item.arcname)
                pkg.estimated_size += item.size
                placed = True
                break

            if not placed:
                idx = len(packages) + 1
                out = output_dir / f"{base_name}_{idx:03d}.zip"
                packages.append(
                    PackagePlan(
                        index=idx, files=[item], estimated_size=item.size,
                        output_path=out, names={item.arcname},
                    )
                )

        return PackagingResult(True, packages=packages, skipped=skipped)

    def execute(
        self,
        plan: PackagingResult,
        *,
        dry_run: bool = False,
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

        for pkg in plan.packages:
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
    ) -> PackagingResult:
        """Plan + execute in one call."""
        plan = self.plan(sources, output_dir, base_name, base=base)
        if not plan.success:
            return plan
        return self.execute(plan)
