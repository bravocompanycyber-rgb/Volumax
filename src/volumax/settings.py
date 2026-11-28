"""Persistent application settings."""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from .config import DEFAULT_SETTINGS, SETTINGS_FILE

logger = logging.getLogger("volumax.settings")


class Settings:
    """Thread-safe-ish settings store backed by a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or SETTINGS_FILE
        self._data: dict[str, Any] = deepcopy(DEFAULT_SETTINGS)
        self.recovered_from = ""
        self.load()

    def load(self) -> None:
        """Load settings; a missing/corrupt file is repaired, never fatal."""
        if not self._path.exists():
            self.save()
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("settings root is not an object")
        except (OSError, ValueError) as exc:  # JSONDecodeError is a ValueError
            logger.error("Settings unreadable (%s); recovering", exc)
            self.recovered_from = self._quarantine()
            self._data = deepcopy(DEFAULT_SETTINGS)
            self.save()
            return
        merged = deepcopy(DEFAULT_SETTINGS)
        merged.update(loaded)
        self._data = merged

    def _quarantine(self) -> str:
        """Move the bad file aside (kept for the user) and return its new path."""
        try:
            import time
            bad = self._path.with_name(f"{self._path.stem}.corrupt-{int(time.time())}{self._path.suffix}")
            os.replace(self._path, bad)
            return str(bad)
        except OSError:
            return ""

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Atomic write: a crash mid-save must never leave a corrupt settings file
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._path)
        except OSError as exc:
            logger.error("Failed to save settings: %s", exc)

    @property
    def path(self) -> Path:
        return self._path

    def reset(self) -> None:
        self._data = deepcopy(DEFAULT_SETTINGS)
        self.save()

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def update(self, mapping: dict[str, Any]) -> None:
        self._data.update(mapping)

    def as_dict(self) -> dict[str, Any]:
        return deepcopy(self._data)

    # Convenience typed accessors
    @property
    def independent_zip_max_mb(self) -> int:
        return int(self._data.get("independent_zip_max_mb", 20))

    @property
    def independent_zip_ceiling_mb(self) -> int:
        return int(self._data.get("independent_zip_ceiling_mb", 30))

    @property
    def volume_size_mb(self) -> int:
        return int(self._data.get("volume_size_mb", 100))

    @property
    def compression_level(self) -> int:
        return int(self._data.get("compression_level", 5))

    @property
    def compression_preset(self) -> str:
        return str(self._data.get("compression_preset", "maximum"))

    @property
    def safe_extraction(self) -> bool:
        return bool(self._data.get("safe_extraction", True))


# Singleton used by the application
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
