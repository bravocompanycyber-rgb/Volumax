"""Archive listing: folder-tree index + cache, built once off the GUI thread.

Opening an archive costs one 7-Zip call (compact format, ~0.4 s for 200 000
entries). The result is indexed into a folder tree so navigating into a folder,
sorting and searching never touch the archive again, and re-opening an
unchanged archive is served from an in-memory cache.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from .archive_manager import ArchiveManager
from .backends.base import ArchiveEntry, BackendResult


@dataclass
class ArchiveTree:
    entries: list[ArchiveEntry]
    children: dict[str, list[ArchiveEntry]] = field(default_factory=dict)
    file_count: int = 0
    dir_count: int = 0
    total_size: int = 0
    total_packed: int = 0
    elapsed: float = 0.0
    needs_password: bool = False

    @staticmethod
    def build(entries: list[ArchiveEntry]) -> "ArchiveTree":
        tree = ArchiveTree(entries=entries)
        children = tree.children
        children[""] = []
        dirs: dict[str, ArchiveEntry] = {}

        def ensure_dir(path: str) -> None:
            """Register ``path`` and any missing ancestors as folders."""
            while path and path not in dirs:
                parent = path.rpartition("/")[0]
                node = ArchiveEntry(path=path, is_dir=True)
                dirs[path] = node
                children.setdefault(path, [])
                ensure_parent_list(parent).append(node)
                path = parent

        def ensure_parent_list(parent: str) -> list[ArchiveEntry]:
            lst = children.get(parent)
            if lst is None:
                lst = children[parent] = []
            return lst

        for e in entries:
            path = e.path.strip("/")
            if not path:
                continue
            e.path = path
            if e.is_dir:
                if path in dirs:
                    # keep timestamp from the real entry
                    dirs[path].timestamp = e.timestamp or dirs[path].timestamp
                    continue
                parent = path.rpartition("/")[0]
                dirs[path] = e
                children.setdefault(path, [])
                ensure_parent_list(parent).append(e)
                ensure_dir(parent)
            else:
                parent = path.rpartition("/")[0]
                ensure_dir(parent)
                ensure_parent_list(parent).append(e)
                tree.file_count += 1
                tree.total_size += e.size
                tree.total_packed += e.compressed_size
        tree.dir_count = len(dirs)
        return tree


# --------------------------------------------------------------------- cache
_CACHE: "OrderedDict[tuple, ArchiveTree]" = OrderedDict()
_CACHE_MAX = 6
_LOCK = threading.Lock()


def _key(path: Path, password: str | None) -> tuple:
    st = os.stat(path)
    return (str(path), st.st_mtime_ns, st.st_size, bool(password))


def load_tree(
    manager: ArchiveManager,
    path: Path,
    password: str | None = None,
    *,
    use_cache: bool = True,
) -> tuple[BackendResult, ArchiveTree | None]:
    """List ``path`` and return ``(result, tree)``; ``tree`` is None on failure."""
    path = Path(path)
    started = time.perf_counter()
    try:
        key = _key(path, password)
    except OSError as exc:
        return BackendResult(False, f"Cannot read archive: {exc}"), None

    if use_cache:
        with _LOCK:
            hit = _CACHE.get(key)
            if hit is not None:
                _CACHE.move_to_end(key)
                return BackendResult(True, "cached", entries=hit.entries), hit

    result = manager.list_contents(path, password=password)
    if not result.success:
        tree = ArchiveTree(entries=[], needs_password=bool(result.extra.get("needs_password")))
        return result, None if not tree.needs_password else tree
    tree = ArchiveTree.build(result.entries)
    tree.elapsed = time.perf_counter() - started
    with _LOCK:
        _CACHE[key] = tree
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return result, tree


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()
