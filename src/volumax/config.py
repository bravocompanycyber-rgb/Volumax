"""VOLUMAX configuration — paths, formats, defaults."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final


def _resolve_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


PROJECT_ROOT: Final[Path] = _resolve_project_root()
ASSETS_DIR: Final[Path] = PROJECT_ROOT / "assets"
ENGINES_DIR: Final[Path] = PROJECT_ROOT / "engines"
LOGS_DIR: Final[Path] = PROJECT_ROOT / "logs"
SETTINGS_FILE: Final[Path] = PROJECT_ROOT / "settings.json"

SEVEN_ZIP_EXE_CANDIDATES = [
    Path("/tmp/volumax_engine/7z"),
    Path("/usr/bin/7z"),
    Path("/usr/lib/7zip/7z"),
    ENGINES_DIR / "7zip" / "7z",
    ENGINES_DIR / "7zip" / "7z.exe",
    Path(r"C:\Program Files\7-Zip\7z.exe"),
    Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
]


def find_7zip_exe() -> Path | None:
    for candidate in SEVEN_ZIP_EXE_CANDIDATES:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


DEFAULT_SETTINGS: dict = {
    "theme": "dark",
    "accent": "#3b82f6",
    "compression_level": 5,
    "default_format": "7z",
    "independent_zip_max_mb": 100,  # user-configurable, no forced limit
    "independent_zip_ceiling_mb": 0,  # 0 = unlimited; user sets max only
    "volume_size_mb": 100,
    "preserve_timestamps": True,
    "safe_extraction": True,
    "max_extraction_files": 100_000,
    "max_extraction_size_gb": 50,
    "overwrite_policy": "ask",
    "job_history_limit": 200,
    "log_level": "INFO",
    "worker_count": 2,
    "recent_files": [],
    "window_geometry": None,
    "last_create_dir": "",
    "last_extract_dir": "",
    "smart_compression": True,
}

SUPPORTED_FORMATS: Final[tuple[str, ...]] = (
    "zip", "7z", "tar", "tar.gz", "tgz", "tar.bz2", "tbz2", "tar.xz", "txz",
)

FORMAT_EXTENSIONS: Final[dict[str, tuple[str, ...]]] = {
    "zip": (".zip",),
    "7z": (".7z",),
    "tar": (".tar",),
    "tar.gz": (".tar.gz", ".tgz"),
    "tar.bz2": (".tar.bz2", ".tbz2", ".tbz"),
    "tar.xz": (".tar.xz", ".txz"),
}

LOW_GAIN_EXTENSIONS: Final[frozenset[str]] = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mkv", ".avi", ".mov",
    ".mp3", ".aac", ".flac", ".ogg", ".zip", ".7z", ".rar", ".gz", ".bz2",
    ".xz", ".zst", ".pdf", ".docx", ".xlsx", ".pptx",
})

COMPRESSION_PRESETS: Final[dict[str, int]] = {
    "store": 0,
    "fastest": 1,
    "fast": 3,
    "normal": 5,
    "maximum": 7,
    "ultra": 9,
}
