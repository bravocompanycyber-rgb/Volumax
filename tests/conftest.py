"""Pytest fixtures for VOLUMAX tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

# Ensure src is on path
import sys
ROOT = Path(__file__).resolve().parent.parent
import os, tempfile
os.environ.setdefault("VOLUMAX_HOME", tempfile.mkdtemp(prefix="volumax_test_home_"))
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def tmp_dir(tmp_path: Path):
    return tmp_path


@pytest.fixture
def sample_files(tmp_path: Path):
    """Create a small set of sample files and folders."""
    base = tmp_path / "sample"
    base.mkdir()
    (base / "hello.txt").write_text("Hello VOLUMAX\n", encoding="utf-8")
    (base / "data.bin").write_bytes(b"\x00\x01\x02\x03" * 100)
    sub = base / "subdir"
    sub.mkdir()
    (sub / "nested.txt").write_text("nested content", encoding="utf-8")
    (base / "empty_dir").mkdir()
    (base / "unicode_ファイル.txt").write_text("日本語テスト", encoding="utf-8")
    return base

