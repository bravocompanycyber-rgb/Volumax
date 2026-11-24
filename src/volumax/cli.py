"""Command line interface — what Explorer's right-click menu and file associations call.

    volumax.exe [ARCHIVE]                    open in the browser (double-click / "Open with")
    volumax.exe --extract-here ARCHIVE...    extract next to the archive
    volumax.exe --extract-to-folder ARCHIVE  extract into a folder named after the archive
    volumax.exe --add PATH...                open "Create archive" with these items
    volumax.exe --add-to 7z|zip PATH...      create "<name>.7z|zip" next to the first item (no form)
    volumax.exe --version | --help
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from . import __version__

OPEN = "open"
EXTRACT_HERE = "extract-here"
EXTRACT_FOLDER = "extract-to-folder"
ADD = "add"
ADD_TO = "add-to"

QUICK_FORMATS = ("7z", "zip")
# Compound extensions that must be stripped as one unit when naming output folders
_COMPOUND = (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst", ".tar.lz", ".tar.lzma")


@dataclass
class Command:
    kind: str = ""                 # "" = just start the app
    paths: List[Path] = field(default_factory=list)
    fmt: str = "7z"


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # never sys.exit from a GUI app's parser
        raise ValueError(message)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="volumax", add_help=False, description="VOLUMAX archive manager")
    p.add_argument("--extract-here", nargs="+", metavar="ARCHIVE")
    p.add_argument("--extract-to-folder", nargs="+", metavar="ARCHIVE")
    p.add_argument("--add", nargs="+", metavar="PATH")
    p.add_argument("--add-to", nargs="+", metavar=("FORMAT", "PATH"))
    p.add_argument("--open", nargs="+", metavar="ARCHIVE")
    p.add_argument("--version", action="store_true")
    p.add_argument("--help", "-h", action="store_true")
    p.add_argument("paths", nargs="*")
    return p


def parse(argv: Sequence[str]) -> Command:
    """Parse arguments (without argv[0]). Unknown flags are ignored, never fatal."""
    try:
        ns, _unknown = build_parser().parse_known_args(list(argv))
    except ValueError:
        return Command()
    if ns.add_to:
        fmt = ns.add_to[0].lower().lstrip(".")
        rest = ns.add_to[1:]
        if fmt in QUICK_FORMATS and rest:
            return Command(ADD_TO, [Path(x) for x in rest], fmt)
        return Command()
    if ns.extract_here:
        return Command(EXTRACT_HERE, [Path(x) for x in ns.extract_here])
    if ns.extract_to_folder:
        return Command(EXTRACT_FOLDER, [Path(x) for x in ns.extract_to_folder])
    if ns.add:
        return Command(ADD, [Path(x) for x in ns.add])
    opened = list(ns.open or []) + list(ns.paths or [])
    if opened:
        return Command(OPEN, [Path(x) for x in opened])
    return Command()


def wants_version(argv: Sequence[str]) -> bool:
    return "--version" in argv


def wants_help(argv: Sequence[str]) -> bool:
    return "--help" in argv or "-h" in argv


def help_text() -> str:
    return (__doc__ or "").strip()


# --------------------------------------------------------------------- planning
def archive_stem(name: str) -> str:
    """'photos.tar.gz' -> 'photos', 'a.b.7z' -> 'a.b', 'x.7z.001' -> 'x'."""
    low = name.lower()
    for ext in _COMPOUND:
        if low.endswith(ext):
            return name[: -len(ext)]
    p = Path(name)
    if p.suffix[1:].isdigit() and len(p.suffix) == 4:  # .001 split volumes
        p = Path(p.stem)
    return p.stem or name


def unique_path(path: Path) -> Path:
    """path, or 'name (1)', 'name (2)' … — never overwrite something that exists."""
    if not path.exists():
        return path
    n = 1
    while True:
        cand = path.with_name(f"{path.stem} ({n}){path.suffix}") if path.suffix and path.is_file() \
            else path.with_name(f"{path.name} ({n})")
        if not cand.exists():
            return cand
        n += 1


def top_level_names(entry_paths: Sequence[str]) -> set:
    out = set()
    for p in entry_paths:
        p = p.replace("\\", "/").strip("/")
        if p:
            out.add(p.split("/", 1)[0])
    return out


def plan_extract_destination(
    archive: Path, entry_paths: Sequence[str], mode: str
) -> Tuple[Path, str]:
    """Where to extract so nothing existing is overwritten and the user never gets a mess.

    * EXTRACT_FOLDER: always into '<archive name>/' (made unique if it exists).
    * EXTRACT_HERE: next to the archive when it has ONE top-level item and that item does
      not exist yet; otherwise into '<archive name>/' — like WinRAR's smart extract.
    Returns (destination, note).
    """
    parent = archive.parent
    folder = parent / archive_stem(archive.name)
    tops = top_level_names(entry_paths)
    if mode == EXTRACT_HERE and len(tops) == 1 and not (parent / next(iter(tops))).exists():
        return parent, "next to the archive"
    return unique_path(folder), f"into “{unique_path(folder).name}”"


def plan_quick_archive(fmt: str, paths: Sequence[Path]) -> Path:
    """Output path for `--add-to`: named after the single item, or the parent folder."""
    first = Path(paths[0])
    if len(paths) == 1:
        base = first.stem if first.is_file() else first.name
    else:
        base = first.parent.name or "Archive"
    return unique_path(first.parent / f"{base}.{fmt}")
