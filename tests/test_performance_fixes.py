"""Regression tests for the speed/robustness fixes."""

from __future__ import annotations

import os
from pathlib import Path

from volumax.backends.sevenzip import SevenZipBackend
from volumax.checksums import hash_file
from volumax.duplicate_finder import DuplicateFinder
from volumax.extraction import ExtractionSafety, SafeExtractor
from volumax.packaging import IndependentZipPackager


def test_large_listing_does_not_deadlock(tmp_path: Path):
    """Pipes are drained while 7-Zip runs (a full pipe used to hang forever)."""
    src = tmp_path / "many"
    src.mkdir()
    for i in range(6000):
        (src / f"file_with_a_reasonably_long_name_{i:05d}.txt").write_text("x")
    be = SevenZipBackend()
    arc = tmp_path / "many.7z"
    assert be.create_archive(arc, [src]).success
    res = be.list_archive(arc)
    assert res.success and len(res.entries) >= 6000


def test_progress_is_reported(tmp_path: Path):
    src = tmp_path / "blob.bin"
    src.write_bytes(os.urandom(8 * 1024 * 1024))
    seen: list[int] = []
    res = SevenZipBackend().create_archive(
        tmp_path / "blob.7z", [src], progress=lambda p, m="": seen.append(p)
    )
    assert res.success and seen and max(seen) > 0  # job queue sets the final 100%


def test_staging_is_inside_destination_and_cleaned(tmp_path: Path, sample_files: Path):
    be = SevenZipBackend()
    arc = tmp_path / "s.7z"
    assert be.create_archive(arc, [sample_files]).success
    dest = tmp_path / "out"
    res = SafeExtractor().extract(arc, dest)
    assert res.success
    assert not any(p.name.startswith(".volumax_stage_") for p in dest.iterdir())
    assert (dest / "sample" / "hello.txt").read_text(encoding="utf-8") == "Hello VOLUMAX\n"


def test_containment_check_is_component_aware(tmp_path: Path):
    base = tmp_path / "out"
    base.mkdir()
    (tmp_path / "out-evil").mkdir()
    safety = ExtractionSafety()
    # a sibling dir sharing the prefix must NOT count as inside
    assert safety.safe_destination(base, "../out-evil/x.txt") is None
    assert safety.safe_destination(base, "ok/x.txt") is not None


def test_duplicates_head_and_full_hash(tmp_path: Path):
    a = os.urandom(300_000)
    (tmp_path / "a.bin").write_bytes(a)
    (tmp_path / "b.bin").write_bytes(a)
    # same size and same first 64 KB, different tail -> must NOT be a duplicate
    (tmp_path / "c.bin").write_bytes(a[:100_000] + os.urandom(200_000))
    groups = DuplicateFinder().scan([tmp_path])
    assert len(groups) == 1
    assert {p.name for p in groups[0].paths} == {"a.bin", "b.bin"}


def test_hash_file_modes_agree(tmp_path: Path):
    f = tmp_path / "f.bin"
    f.write_bytes(os.urandom(1_000_000))
    fast = hash_file(f)
    slow = hash_file(f, progress=lambda d, t: None)
    assert fast == slow


def test_packager_unique_names_and_stored_media(tmp_path: Path):
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    (tmp_path / "x" / "a.txt").write_text("1")
    (tmp_path / "y" / "a.txt").write_text("2")
    p = IndependentZipPackager(max_bytes=10 * 1024 * 1024)
    items = p.collect_files([tmp_path / "x" / "a.txt", tmp_path / "y" / "a.txt"])
    plan = p.plan([i.source for i in items], tmp_path / "o")
    names = [f.arcname for pkg in plan.packages for f in pkg.files]
    assert len(names) == len(set(names)) == 2
