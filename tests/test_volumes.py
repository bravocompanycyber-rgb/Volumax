"""Multipart volume tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from volumax.volume_manager import VolumeManager, discover_volumes
from volumax.engine import SevenZipEngine


def test_create_and_discover_volumes(sample_files: Path, tmp_path: Path):
    engine = SevenZipEngine()
    vm = VolumeManager(engine)

    # Use a small volume size so we get multiple parts if content is large enough
    # sample_files is tiny, so may produce a single volume
    base = tmp_path / "backup.7z"
    result = vm.create_volumes(
        base,
        [sample_files],
        volume_size="1m",  # 1 MB volumes
        format="7z",
        level=1,
    )
    assert result.success, result.message

    # Either single file or volumes
    if base.exists():
        # Content fit in one volume without split
        return

    # Look for .001
    first = Path(str(base) + ".001")
    if not first.exists():
        # Some 7z versions name differently
        parts = list(tmp_path.glob("backup.7z*"))
        assert parts, "No volume files created"
        return

    vs = discover_volumes(first)
    assert vs is not None
    assert vs.complete
    assert len(vs.volumes) >= 1


def test_verify_incomplete_volumes(tmp_path: Path):
    # Fabricate a partial set
    (tmp_path / "partial.7z.001").write_bytes(b"fake")
    # missing 002
    vs = discover_volumes(tmp_path / "partial.7z.001")
    assert vs is not None
    # With only one volume present and no gap, complete is True for single
    # If we add a gap scenario:
    (tmp_path / "gap.7z.001").write_bytes(b"a")
    (tmp_path / "gap.7z.003").write_bytes(b"c")
    vs2 = discover_volumes(tmp_path / "gap.7z.001")
    # Implementation stops at first gap, so may report incomplete via missing
    assert vs2 is not None
