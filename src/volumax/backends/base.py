"""Abstract archive backend interface for extensibility."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence


ProgressCallback = Callable[[int, str], None]
CancelCheck = Callable[[], bool]


@dataclass
class BackendCapabilities:
    name: str
    formats_create: tuple[str, ...]
    formats_extract: tuple[str, ...]
    supports_password: bool = True
    supports_encrypt_filenames: bool = False
    supports_volumes: bool = False
    supports_solid: bool = False
    supports_update: bool = False


@dataclass
class ArchiveEntry:
    path: str
    size: int = 0
    compressed_size: int = 0
    is_dir: bool = False
    timestamp: str | None = None
    crc: str | None = None
    encrypted: bool = False


@dataclass
class BackendResult:
    success: bool
    message: str = ""
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    entries: list[ArchiveEntry] = field(default_factory=list)
    output_path: Path | None = None
    extra: dict = field(default_factory=dict)


class ArchiveBackend(ABC):
    """Contract every compression/extraction engine must implement."""

    @abstractmethod
    def capabilities(self) -> BackendCapabilities: ...

    @abstractmethod
    def list_archive(
        self, archive: Path, password: str | None = None, detailed: bool = False
    ) -> BackendResult: ...

    @abstractmethod
    def create_archive(
        self,
        archive: Path,
        sources: Sequence[Path],
        *,
        format: str = "7z",
        level: int = 5,
        password: str | None = None,
        encrypt_filenames: bool = False,
        solid: bool = True,
        volume_size: str | None = None,
        progress: ProgressCallback | None = None,
        cancel: CancelCheck | None = None,
        **options: object,
    ) -> BackendResult: ...

    @abstractmethod
    def extract_archive(
        self,
        archive: Path,
        destination: Path,
        *,
        password: str | None = None,
        selected_files: Sequence[str] | None = None,
        overwrite: bool = True,
        progress: ProgressCallback | None = None,
        cancel: CancelCheck | None = None,
        pause: CancelCheck | None = None,
    ) -> BackendResult: ...

    @abstractmethod
    def test_archive(
        self,
        archive: Path,
        password: str | None = None,
        progress: ProgressCallback | None = None,
        cancel: CancelCheck | None = None,
    ) -> BackendResult: ...
