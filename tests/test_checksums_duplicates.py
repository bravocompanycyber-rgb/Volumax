"""Checksum and duplicate finder tests."""

from __future__ import annotations

from pathlib import Path

from volumax.checksums import hash_file, verify_checksum
from volumax.duplicate_finder import DuplicateFinder


def test_hash_file(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text("hello")
    h = hash_file(f, "sha256")
    assert len(h) == 64
    assert verify_checksum(f, h, "sha256")


def test_duplicate_finder(tmp_path: Path):
    d = tmp_path / "files"
    d.mkdir()
    (d / "a.txt").write_text("same content")
    (d / "b.txt").write_text("same content")
    (d / "c.txt").write_text("different")

    finder = DuplicateFinder()
    groups = finder.scan([d])
    assert len(groups) == 1
    assert len(groups[0].paths) == 2
    assert groups[0].wasted_bytes > 0
