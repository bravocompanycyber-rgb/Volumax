"""Backend adapters — primary 7-Zip, extensible for future engines."""

from .base import BackendCapabilities, BackendResult, ArchiveBackend
from .sevenzip import SevenZipBackend

__all__ = [
    "BackendCapabilities",
    "BackendResult",
    "ArchiveBackend",
    "SevenZipBackend",
]
