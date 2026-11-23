"""Find duplicate files by content hash."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .checksums import hash_file

logger = logging.getLogger("volumax.duplicates")


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


class DuplicateFinder:
    def __init__(self, algorithm: str = "sha256") -> None:
        self.algorithm = algorithm

    def scan(
        self,
        roots: Sequence[Path],
        *,
        min_size: int = 1,
        progress: Callable[[str], None] | None = None,
    ) -> list[DuplicateGroup]:
        # First pass: group by size (cheap)
        size_map: dict[int, list[Path]] = defaultdict(list)

        for root in roots:
            root = Path(root)
            if not root.exists():
                continue
            for dirpath, _, filenames in os.walk(root):
                for fn in filenames:
                    full = Path(dirpath) / fn
                    try:
                        st = full.stat()
                        if st.st_size >= min_size:
                            size_map[st.st_size].append(full)
                    except OSError:
                        continue

        # Second pass: hash only groups with size collisions
        hash_map: dict[str, list[Path]] = defaultdict(list)
        candidates = {sz: paths for sz, paths in size_map.items() if len(paths) > 1}

        total = sum(len(p) for p in candidates.values())
        done = 0
        for size, paths in candidates.items():
            for p in paths:
                if progress:
                    progress(str(p))
                try:
                    digest = hash_file(p, self.algorithm)
                    hash_map[digest].append(p)
                except OSError as exc:
                    logger.warning("Could not hash %s: %s", p, exc)
                done += 1

        groups: list[DuplicateGroup] = []
        for digest, paths in hash_map.items():
            if len(paths) > 1:
                size = paths[0].stat().st_size
                groups.append(DuplicateGroup(hash=digest, size=size, paths=paths))

        groups.sort(key=lambda g: g.wasted_bytes, reverse=True)
        return groups
