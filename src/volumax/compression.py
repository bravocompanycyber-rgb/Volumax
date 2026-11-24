"""Compression planning: analyse the sources, then choose the best 7-Zip settings.

Findings that shaped the choices (measured on a mixed 48 MB corpus):

* ``-mx=9`` is ~16% smaller than 7-Zip's ``-mx=5`` default at about the same speed.
* A huge dictionary / ``fb=273`` adds only ~0.2% for ~45% more time, so that is
  reserved for the "ultra" preset.
* ``-ms=e`` (solid-by-extension) made things ~40% *worse*; never used.
* On text/source code, PPMd is ~10% smaller than LZMA2 *and* faster, so
  text-dominated inputs switch to PPMd automatically.
* Already-compressed media (jpg/mp4/zip/...) gains nothing from heavy settings,
  so media-dominated inputs are downgraded to a fast level to save time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from .config import LOW_GAIN_EXTENSIONS

try:  # optional: used to size dictionaries safely for the machine
    import psutil
except Exception:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

PRESETS: dict[str, int] = {
    "store": 0,
    "fastest": 1,
    "fast": 3,
    "normal": 5,
    "maximum": 9,
    "ultra": 9,
}

TEXT_EXTENSIONS = frozenset(
    {
        ".txt", ".md", ".rst", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".html", ".htm",
        ".css", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".py", ".pyi", ".java", ".c", ".h",
        ".cpp", ".hpp", ".cc", ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".bat", ".ps1",
        ".sql", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".log", ".tex", ".svg",
        ".lua", ".kt", ".swift", ".r", ".pl", ".vue", ".scss", ".less", ".srt", ".vtt",
        ".gitignore", ".env", ".properties", ".gradle", ".cmake", ".mk",
    }
)

_MB = 1024 * 1024


@dataclass
class SourceProfile:
    total_bytes: int = 0
    file_count: int = 0
    text_bytes: int = 0
    low_gain_bytes: int = 0

    @property
    def text_ratio(self) -> float:
        return self.text_bytes / self.total_bytes if self.total_bytes else 0.0

    @property
    def low_gain_ratio(self) -> float:
        return self.low_gain_bytes / self.total_bytes if self.total_bytes else 0.0


def analyze_sources(
    sources: Sequence[Path],
    cancel: Callable[[], bool] | None = None,
    max_files: int = 3_000_000,
) -> SourceProfile:
    """Fast scandir walk that classifies bytes as text / already-compressed / other."""
    prof = SourceProfile()
    stack: list[str] = []

    def account(name: str, size: int) -> None:
        prof.file_count += 1
        prof.total_bytes += size
        ext = os.path.splitext(name)[1].lower()
        if ext in TEXT_EXTENSIONS:
            prof.text_bytes += size
        elif ext in LOW_GAIN_EXTENSIONS:
            prof.low_gain_bytes += size

    for src in sources:
        s = str(src)
        try:
            if os.path.isdir(s):
                stack.append(s)
            elif os.path.isfile(s):
                account(s, os.path.getsize(s))
        except OSError:
            continue

    while stack and prof.file_count < max_files:
        if cancel and cancel():
            break
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            account(entry.name, entry.stat(follow_symlinks=False).st_size)
                    except OSError:
                        continue
        except OSError:
            continue
    return prof


def _pow2_at_least(n: int, lo: int, hi: int) -> int:
    v = lo
    while v < n and v < hi:
        v *= 2
    return min(v, hi)


def _available_mb() -> int:
    if psutil is not None:
        try:
            return int(psutil.virtual_memory().available // _MB)
        except Exception:
            pass
    return 2048


@dataclass
class CompressionPlan:
    args: list[str] = field(default_factory=list)
    method: str = "lzma2"
    level: int = 5
    dictionary_mb: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def description(self) -> str:
        bits = [f"{self.method.upper()} level {self.level}"]
        if self.dictionary_mb:
            bits.append(f"{self.dictionary_mb} MB dictionary")
        bits.extend(self.notes)
        return ", ".join(bits)


def resolve_preset(preset: str | int | None, level: int | None) -> tuple[str, int]:
    """Return (preset_name, numeric_level) from whatever the caller supplied."""
    if isinstance(preset, str) and preset.lower() in PRESETS:
        name = preset.lower()
        return name, PRESETS[name]
    if isinstance(preset, int):
        level = preset
    lvl = 5 if level is None else max(0, min(9, int(level)))
    names = {0: "store", 1: "fastest", 3: "fast", 5: "normal", 9: "maximum"}
    return names.get(lvl, "normal"), lvl


def plan_compression(
    fmt: str,
    *,
    preset: str | int | None = None,
    level: int | None = None,
    profile: SourceProfile | None = None,
    solid: bool = True,
    threads: int = 0,
    max_dictionary_mb: int = 512,
    dictionary_mb: int | None = None,
    smart: bool = True,
) -> CompressionPlan:
    """Build the 7-Zip method switches for ``fmt`` (7z, zip, gzip, bzip2, xz, tar...)."""
    name, lvl = resolve_preset(preset, level)
    prof = profile or SourceProfile()
    plan = CompressionPlan(level=lvl)
    mmt = f"-mmt={threads}" if threads and threads > 0 else "-mmt=on"
    total_mb = max(1, -(-prof.total_bytes // _MB))  # ceil: dictionary must cover the data

    # Heavy settings are wasted on data that is already compressed.
    if smart and lvl > 1 and prof.total_bytes >= _MB and prof.low_gain_ratio >= 0.85:
        lvl = 1
        plan.level = 1
        plan.notes.append("mostly already-compressed files: fast level chosen")
        name = "fastest"

    if fmt in ("tar", "wim"):
        plan.method = "store"
        plan.level = 0
        return plan

    if lvl == 0:
        plan.method = "store"
        plan.args = ["-mx=0"]
        return plan

    if fmt == "7z":
        if name in ("maximum", "ultra") and lvl == 9:
            avail = _available_mb()
            text_heavy = (
                smart
                and prof.total_bytes >= 64 * 1024
                and prof.text_ratio >= 0.7
                and prof.low_gain_ratio < 0.2
            )
            if text_heavy:
                # PPMd: ~10% smaller and faster than LZMA2 on text/source code.
                mem = _pow2_at_least(total_mb, 16, min(max_dictionary_mb, 512, max(16, avail // 6)))
                plan.method = "ppmd"
                plan.dictionary_mb = mem
                plan.args = ["-mx=9", f"-m0=ppmd:mem={mem}m:o=16"]
                plan.notes.append("text-dominant data: PPMd")
            else:
                if name == "ultra":
                    # LZMA2 needs ~10x the dictionary in RAM per thread.
                    cap = min(max_dictionary_mb, 1536, max(16, avail // 24))
                    d = dictionary_mb or _pow2_at_least(total_mb, 16, cap)
                    plan.dictionary_mb = d
                    plan.args = ["-mx=9", f"-m0=lzma2:d={d}m:fb=273", "-mqs=on"]
                else:
                    # 7-Zip's own -mx=9 is the best speed/ratio trade-off.
                    d = dictionary_mb or _pow2_at_least(total_mb, 16, 64)  # never below mx=5's 16 MB
                    plan.dictionary_mb = d
                    plan.args = ["-mx=9", f"-md={d}m"]
                plan.method = "lzma2"
        else:
            plan.method = "lzma2"
            plan.args = [f"-mx={lvl}"]
        plan.args.append(mmt)
        if not solid:
            plan.args.append("-ms=off")
        return plan

    if fmt == "zip":
        plan.method = "deflate"
        plan.args = [f"-mx={lvl}", mmt]
        return plan

    # gzip / bzip2 / xz single-stream codecs (run on a .tar)
    plan.method = fmt
    plan.args = [f"-mx={lvl}", mmt]
    return plan
