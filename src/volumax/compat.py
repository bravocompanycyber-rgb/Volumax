"""Small shims so one code base runs on Python 3.8 (Windows 7/8/8.1 'Legacy' build)
and on current Python (Windows 10/11 'Modern' build)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO


def is_relative_to(path: Path, other: Path) -> bool:
    """Path.is_relative_to (3.9+), component-aware like the original."""
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


def file_digest(fileobj: BinaryIO, algorithm: str, bufsize: int = 4 * 1024 * 1024) -> str:
    """hashlib.file_digest (3.11+) with a buffered fallback; returns the hex digest."""
    native = getattr(hashlib, "file_digest", None)
    if native is not None:
        return native(fileobj, algorithm).hexdigest()
    h = hashlib.new(algorithm)
    buf = bytearray(bufsize)
    view = memoryview(buf)
    readinto = getattr(fileobj, "readinto", None)
    while True:
        n = readinto(view) if readinto else 0
        if not n:
            break
        h.update(view[:n])
    return h.hexdigest()


ARCHIVE_SUFFIXES = (
    ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".tbz2", ".tbz", ".txz",
    ".iso", ".cab", ".wim", ".001", ".zipx", ".jar", ".apk", ".arj", ".lzh", ".z",
)


def looks_like_archive(path) -> bool:
    return path.name.lower().endswith(ARCHIVE_SUFFIXES)


def safe_is_file(p) -> bool:
    """Path.is_file() that never raises (too-long names, NUL, odd devices -> False)."""
    try:
        return bool(p.is_file())
    except (OSError, ValueError):
        return False


def safe_is_dir(p) -> bool:
    try:
        return bool(p.is_dir())
    except (OSError, ValueError):
        return False


def safe_exists(p) -> bool:
    try:
        return bool(p.exists())
    except (OSError, ValueError):
        return False
