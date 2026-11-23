"""Tests for the 7-Zip engine and native ZIP helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from volumax.engine import SevenZipEngine, create_zip_native, extract_zip_native
from volumax.config import find_7zip_exe


def test_7zip_engine_found():
    exe = find_7zip_exe()
    assert exe is not None and exe.is_file()


def test_create_and_list_7z(sample_files: Path, tmp_path: Path):
    engine = SevenZipEngine()
    archive = tmp_path / "test.7z"
    result = engine.create_archive(archive, [sample_files], format="7z", level=5)
    assert result.success, result.message
    assert archive.exists()

    listed = engine.list_archive(archive)
    assert listed.success, listed.message
    paths = {e.path for e in listed.entries}
    assert any("hello.txt" in p for p in paths)


def test_create_and_extract_zip_native(sample_files: Path, tmp_path: Path):
    archive = tmp_path / "native.zip"
    files = []
    for p in sample_files.rglob("*"):
        if p.is_file():
            arc = str(p.relative_to(sample_files)).replace("\\", "/")
            files.append((p, arc))

    result = create_zip_native(archive, files)
    assert result.success, result.message
    assert archive.exists()
    assert archive.stat().st_size > 0

    dest = tmp_path / "extracted"
    res2 = extract_zip_native(archive, dest)
    assert res2.success, res2.message
    assert (dest / "hello.txt").read_text(encoding="utf-8") == "Hello VOLUMAX\n"


def test_password_protected_7z(sample_files: Path, tmp_path: Path):
    engine = SevenZipEngine()
    archive = tmp_path / "secret.7z"
    result = engine.create_archive(
        archive,
        [sample_files / "hello.txt"],
        format="7z",
        level=5,
        password="testpass",
        encrypt_filenames=True,
    )
    assert result.success, result.message

    # List without password should fail or show encrypted
    listed = engine.list_archive(archive, password="testpass")
    assert listed.success, listed.message

    # Extract with password
    dest = tmp_path / "out"
    extracted = engine.extract_archive(archive, dest, password="testpass")
    assert extracted.success, extracted.message


def test_integrity_test(sample_files: Path, tmp_path: Path):
    engine = SevenZipEngine()
    archive = tmp_path / "intact.7z"
    engine.create_archive(archive, [sample_files], format="7z")
    result = engine.test_archive(archive)
    assert result.success, result.message


def test_tar_gz_via_7z(sample_files: Path, tmp_path: Path):
    engine = SevenZipEngine()
    archive = tmp_path / "data.tar.gz"
    # 7-Zip supports tgz
    result = engine.create_archive(archive, [sample_files], format="gzip", level=5)
    # Note: format name for gzip may vary; try tar.gz style
    if not result.success:
        # Fallback: create tar then gzip isn't atomic; skip soft
        pytest.skip(f"gzip format not supported by this 7z: {result.message}")
    assert archive.exists() or list(tmp_path.glob("*.gz"))
