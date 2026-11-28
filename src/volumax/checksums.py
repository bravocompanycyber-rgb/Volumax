"""File and archive checksum utilities."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from .compat import file_digest
from typing import Callable, Iterable

logger = logging.getLogger("volumax.checksums")

ProgressCb = Callable[[int, int], None]  # bytes_done, total


def hash_file(
    path: Path,
    algorithm: str = "sha256",
    *,
    chunk_size: int = 4 * 1024 * 1024,
    progress: ProgressCb | None = None,
    max_bytes: int | None = None,
) -> str:
    """Hash a file. ``max_bytes`` hashes only the first N bytes (quick pre-check)."""
    path = Path(path)
    if progress is None and max_bytes is None:
        with open(path, "rb") as f:
            return file_digest(f, algorithm)  # C-speed loop on 3.11+

    h = hashlib.new(algorithm)
    total = path.stat().st_size if max_bytes is None else min(max_bytes, path.stat().st_size)
    done = 0
    buf = bytearray(chunk_size)
    view = memoryview(buf)
    with open(path, "rb", buffering=0) as f:
        while done < total:
            n = f.readinto(view[: min(chunk_size, total - done)])
            if not n:
                break
            h.update(view[:n])
            done += n
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
