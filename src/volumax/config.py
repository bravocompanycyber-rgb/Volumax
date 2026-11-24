"""VOLUMAX configuration — paths, formats, defaults."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final


def _resolve_project_root() -> Path:
    """Folder holding bundled resources (assets/, engines/).

    PyInstaller 6 onedir puts data files in ``_internal`` (sys._MEIPASS), which
    is NOT the folder containing the .exe, so look there first when frozen.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def _resolve_user_dir() -> Path:
    """Per-user writable folder for settings and logs.

    Writing next to the program fails under C:\\Program Files, so use
    %APPDATA%\\VOLUMAX (or ~/.config/volumax). VOLUMAX_HOME overrides it.
    """
    override = os.environ.get("VOLUMAX_HOME")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "VOLUMAX"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "volumax"


PROJECT_ROOT: Final[Path] = _resolve_project_root()
USER_DIR: Final[Path] = _resolve_user_dir()
ASSETS_DIR: Final[Path] = PROJECT_ROOT / "assets"
ENGINES_DIR: Final[Path] = PROJECT_ROOT / "engines"
LOGS_DIR: Final[Path] = USER_DIR / "logs"
SETTINGS_FILE: Final[Path] = USER_DIR / "settings.json"

# Bundled engine first (known-good version, identical on every machine),
# then system installs.
SEVEN_ZIP_EXE_CANDIDATES = [
    ENGINES_DIR / "7zip" / "7z.exe",
    ENGINES_DIR / "7zip" / "7z",
    Path(r"C:\Program Files\7-Zip\7z.exe"),
    Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
    Path("/usr/bin/7zz"),
    Path("/usr/bin/7z"),
    Path("/usr/local/bin/7zz"),
    Path("/usr/lib/7zip/7z"),
]


def find_7zip_exe() -> Path | None:
    override = os.environ.get("VOLUMAX_7Z")
    if override and Path(override).is_file():
        return Path(override)
    for candidate in SEVEN_ZIP_EXE_CANDIDATES:
        try:
            if candidate.is_file():
                # A Windows .exe can't run on Linux/macOS; skip it there.
                if candidate.suffix.lower() == ".exe" and os.name != "nt":
                    continue
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
    "max_extraction_files": 5_000_000,
    "max_extraction_size_gb": 10_240,
    "overwrite_policy": "ask",
    "job_history_limit": 200,
    "log_level": "INFO",
    "worker_count": 2,
    "recent_files": [],
    "window_geometry": None,
    "last_create_dir": "",
    "last_extract_dir": "",
    "smart_compression": True,
    "compression_preset": "maximum",   # store/fastest/fast/normal/maximum/ultra
    "solid": True,
    "max_dictionary_mb": 512,           # cap for adaptive LZMA2 dictionary
    "threads": 0,                       # 0 = all cores
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
