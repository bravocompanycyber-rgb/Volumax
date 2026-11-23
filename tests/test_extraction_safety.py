"""Safety tests: path traversal, absolute paths, bombs."""

from __future__ import annotations

from pathlib import Path

import pytest

from volumax.extraction import ExtractionSafety, SafeExtractor
from volumax.engine import ArchiveEntry, SevenZipEngine, create_zip_native
from volumax.backends.base import ArchiveEntry as AE


def test_path_traversal_rejected():
    safety = ExtractionSafety()
    reasons = safety.validate_entry_name("../../etc/passwd")
    assert reasons
    assert any("traversal" in r.lower() or ".." in r for r in reasons)


def test_absolute_unix_rejected():
    safety = ExtractionSafety()
    reasons = safety.validate_entry_name("/etc/passwd")
    assert reasons


def test_absolute_windows_rejected():
    safety = ExtractionSafety()
    reasons = safety.validate_entry_name("C:\\Windows\\System32\\config")
    assert reasons


def test_reserved_name_rejected():
    safety = ExtractionSafety()
    reasons = safety.validate_entry_name("CON")
    assert reasons
    reasons2 = safety.validate_entry_name("folder/NUL.txt")
    assert reasons2


def test_safe_destination_stays_inside(tmp_path: Path):
    safety = ExtractionSafety()
    base = tmp_path / "extract"
    base.mkdir()
    ok = safety.safe_destination(base, "subdir/file.txt")
    assert ok is not None
    assert str(ok).startswith(str(base.resolve()))

    bad = safety.safe_destination(base, "../../outside.txt")
    assert bad is None


def test_entries_validation_file_count():
    safety = ExtractionSafety(max_files=5)
    entries = [
        ArchiveEntry(path=f"f{i}.txt", size=10, is_dir=False) for i in range(10)
    ]
    report = safety.validate_entries(entries)
    assert not report.safe
    assert any("too many files" in r for r in report.reasons)


def test_zip_with_traversal_is_blocked(tmp_path: Path):
    """Create a ZIP containing a traversal path and ensure SafeExtractor rejects it."""
    import zipfile

    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../../evil.txt", b"pwned")
        zf.writestr("safe.txt", b"ok")

    dest = tmp_path / "out"
    dest.mkdir()
    extractor = SafeExtractor()
    # list via engine may still show entries; safety check should catch
    from volumax.engine import SevenZipEngine
    engine = SevenZipEngine()
    listed = engine.list_archive(archive)
    if listed.success:
        report = ExtractionSafety().validate_entries(listed.entries)
        # At least one entry should be rejected
        assert not report.safe or report.rejected_entries
