"""Archive integrity testing and repair helpers."""

from __future__ import annotations

import logging
from pathlib import Path

from .engine import EngineResult, SevenZipEngine
from .volume_manager import VolumeManager, discover_volumes

logger = logging.getLogger("volumax.integrity")


class IntegrityChecker:
    def __init__(self, engine: SevenZipEngine | None = None) -> None:
        self.engine = engine or SevenZipEngine()
        self.volumes = VolumeManager(self.engine)

    def test(self, path: Path, password: str | None = None) -> EngineResult:
        path = Path(path)
        if not path.exists():
            return EngineResult(False, f"File not found: {path}")

        # Multi-volume?
        vs = discover_volumes(path)
        if vs is not None:
            return self.volumes.verify_volumes(path)

        return self.engine.test_archive(path, password=password)

    def test_and_report(self, path: Path, password: str | None = None) -> dict:
        result = self.test(path, password=password)
        return {
            "path": str(path),
            "success": result.success,
            "message": result.message,
            "returncode": result.returncode,
        }
