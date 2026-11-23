"""Find duplicate files by content hash (size -> head-hash -> full-hash, parallel)."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from .checksums import hash_file

logger = logging.getLogger("volumax.duplicates")

HEAD_BYTES = 64 * 1024
MAX_WORKERS = min(8, (os.cpu_count() or 2))


@dataclass
class DuplicateGroup:
    hash: str
    size: int
    paths: list[Path] = field(default_factory=list)

    @property
    def wasted_bytes(self) -> int:
        if len(self.paths) < 2:
            return 0
        return self.size * (len(self.paths) - 1)


def _walk_sizes(root: Path, min_size: int, size_map: dict[int, list[Path]]) -> None:
    """Iterative scandir walk; DirEntry.stat() avoids a second syscall on Windows."""
    stack = [str(root)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            size = entry.stat(follow_symlinks=False).st_size
                            if size >= min_size:
                                size_map[size].append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            continue


class DuplicateFinder:
    def __init__(self, algorithm: str = "sha256") -> None:
        self.algorithm = algorithm

    def _hash_many(
        self,
        paths: list[Path],
        *,
        max_bytes: int | None,
        progress: Callable[[str], None] | None,
        cancel: Callable[[], bool] | None,
    ) -> dict[Path, str]:
        def work(p: Path) -> tuple[Path, str | None]:
            if cancel and cancel():
                return p, None
            try:
                return p, hash_file(p, self.algorithm, max_bytes=max_bytes)
            except OSError as exc:
                logger.warning("Could not hash %s: %s", p, exc)
                return p, None

        out: dict[Path, str] = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for p, digest in pool.map(work, paths):
                if progress:
                    progress(str(p))
                if digest is not None:
                    out[p] = digest
        return out

    def scan(
        self,
        roots: Sequence[Path],
        *,
        min_size: int = 1,
        progress: Callable[[str], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> list[DuplicateGroup]:
        # Pass 1: group by size (free)
        size_map: dict[int, list[Path]] = defaultdict(list)
        for root in roots:
            root = Path(root)
            if root.exists():
                _walk_sizes(root, min_size, size_map)

        groups: list[DuplicateGroup] = []
        for size, same_size in size_map.items():
            if len(same_size) < 2:
                continue
            if cancel and cancel():
                break

            # Pass 2: hash only the first 64 KB — rules out most non-duplicates
            candidates = same_size
            if size > HEAD_BYTES:
                head = self._hash_many(
                    same_size, max_bytes=HEAD_BYTES, progress=progress, cancel=cancel
                )
                by_head: dict[str, list[Path]] = defaultdict(list)
                for p, d in head.items():
                    by_head[d].append(p)
                candidates = [p for ps in by_head.values() if len(ps) > 1 for p in ps]
                if len(candidates) < 2:
                    continue

            # Pass 3: full hash, only for survivors
            full = self._hash_many(candidates, max_bytes=None, progress=progress, cancel=cancel)
            by_full: dict[str, list[Path]] = defaultdict(list)
            for p, d in full.items():
                by_full[d].append(p)
            for digest, ps in by_full.items():
                if len(ps) > 1:
                    groups.append(DuplicateGroup(hash=digest, size=size, paths=ps))

        groups.sort(key=lambda g: g.wasted_bytes, reverse=True)
        return groups
