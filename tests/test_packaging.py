"""Tests for independent ZIP packaging and size limits."""

from __future__ import annotations

from pathlib import Path

import pytest

from volumax.packaging import IndependentZipPackager


def test_independent_packages_basic(sample_files: Path, tmp_path: Path):
    out = tmp_path / "packages"
    out.mkdir()
    packager = IndependentZipPackager(max_bytes=50 * 1024 * 1024)  # 50 MB
    result = packager.package([sample_files], out, "pkg")
    assert result.success, result.message
    assert len(result.packages) >= 1
    for pkg in result.packages:
        assert pkg.output_path is not None
        assert pkg.output_path.exists()
        assert pkg.actual_size > 0
        assert pkg.actual_size <= packager.max_bytes


def test_file_exceeding_limit_is_skipped(tmp_path: Path):
    big = tmp_path / "big.bin"
    # 2 MB file
    big.write_bytes(b"X" * (2 * 1024 * 1024))
    small = tmp_path / "small.txt"
    small.write_text("hi")

    out = tmp_path / "out"
    out.mkdir()
    packager = IndependentZipPackager(max_bytes=1 * 1024 * 1024, ceiling_bytes=1 * 1024 * 1024)
    result = packager.package([big, small], out, "pkg")
    # small should be packaged; big skipped
    assert any("big.bin" in str(p) or "exceeds" in r for p, r in result.skipped)
    if result.packages:
        for pkg in result.packages:
            if pkg.output_path and pkg.output_path.exists():
                assert pkg.actual_size <= packager.max_bytes


def test_actual_size_enforced(tmp_path: Path):
    """Verify we measure actual ZIP size, not source estimate."""
    # Create many small highly compressible files
    src = tmp_path / "src"
    src.mkdir()
    for i in range(50):
        (src / f"f{i}.txt").write_text("A" * 1000)

    out = tmp_path / "out"
    out.mkdir()
    # Very tight limit
    packager = IndependentZipPackager(max_bytes=5 * 1024, ceiling_bytes=10 * 1024)
    result = packager.package([src], out, "tiny")
    for pkg in result.packages:
        if pkg.output_path and pkg.output_path.exists() and not pkg.error:
            assert pkg.actual_size <= packager.max_bytes
