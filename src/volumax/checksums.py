"""File and archive checksum utilities."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Callable, Iterable

logger = logging.getLogger("volumax.checksums")

ProgressCb = Callable[[int, int], None]  # bytes_done, total


def hash_file(
    path: Path,
    algorithm: str = "sha256",
    *,
    chunk_size: int = 1024 * 1024,
    progress: ProgressCb | None = None,
) -> str:
    path = Path(path)
    h = hashlib.new(algorithm)
    total = path.stat().st_size
    done = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return h.hexdigest()


def hash_files(
    paths: Iterable[Path],
    algorithm: str = "sha256",
) -> dict[str, str]:
    results: dict[str, str] = {}
    for p in paths:
        p = Path(p)
        if p.is_file():
            try:
                results[str(p)] = hash_file(p, algorithm)
            except OSError as exc:
                logger.error("Checksum failed for %s: %s", p, exc)
                results[str(p)] = ""
    return results


def verify_checksum(
    path: Path,
    expected: str,
    algorithm: str = "sha256",
) -> bool:
    actual = hash_file(path, algorithm)
    return actual.lower() == expected.lower()


SUPPORTED_ALGORITHMS = ("md5", "sha1", "sha256", "sha512")
