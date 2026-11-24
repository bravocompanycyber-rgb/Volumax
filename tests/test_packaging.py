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
    import os

    big = tmp_path / "big.bin"
    # 2 MB of incompressible data (compressible data would legitimately fit now,
    # because packages are sized by *compressed* bytes)
    big.write_bytes(os.urandom(2 * 1024 * 1024))
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


def test_packages_are_packed_by_compressed_size(tmp_path: Path):
    """Compressible data must fill packages by its COMPRESSED size (far fewer ZIPs),
    and the prediction must match the real file size closely and never exceed the limit."""
    import os

    src = tmp_path / "src"
    src.mkdir()
    for i in range(40):
        # 400 KB of repetitive text each = 16 MB source, ~100 KB compressed in total
        (src / f"log{i}.txt").write_text(("line %d of the log\n" % i) * 20000)
    (src / "noise.bin").write_bytes(os.urandom(300_000))

    out = tmp_path / "out"
    out.mkdir()
    limit = 512 * 1024
    packager = IndependentZipPackager(max_bytes=limit, ceiling_bytes=limit)
    result = packager.package([src], out, "p")
    assert result.success, result.message
    # by source size this would need >= 32 packages; by compressed size just a couple
    assert len(result.packages) <= 3, len(result.packages)
    for pkg in result.packages:
        assert pkg.actual_size <= limit
        # prediction is an upper bound that is tight (within 3% + container slack)
        assert pkg.estimated_size >= pkg.actual_size
        assert pkg.estimated_size - pkg.actual_size < 0.03 * limit + 2048
    # every source file is present exactly once across packages
    import zipfile

    names = []
    for pkg in result.packages:
        with zipfile.ZipFile(pkg.output_path) as zf:
            assert zf.testzip() is None
            names += [n for n in zf.namelist() if not n.endswith("/")]
    assert sorted(names) == sorted(p.name for p in src.iterdir())
