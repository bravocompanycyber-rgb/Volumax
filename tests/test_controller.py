"""Controller runs the context-menu verbs end to end (in-process, both Qt stacks)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import volumax  # noqa: F401

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from volumax import cli  # noqa: E402
from volumax.archive_manager import ArchiveManager  # noqa: E402
from volumax.controller import Controller  # noqa: E402


@pytest.fixture()
def ctl(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    c = Controller(app)
    errors = []
    monkeypatch.setattr(Controller, "_error", staticmethod(lambda t, m: errors.append((t, m))))
    monkeypatch.setattr("volumax.controller.QDesktopServices.openUrl", lambda *_: True)
    monkeypatch.setattr(Controller, "notify", lambda self, t, m: errors.append(("notify", m)) or None)
    c.errors = errors
    c.pump = lambda until, timeout=20: _pump(app, until, timeout)
    return c


def _pump(app, until, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if until():
            return True
        time.sleep(0.01)
    return False


def _archive(tmp: Path, name="pack.7z") -> Path:
    src = tmp / "src" / "proj"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("hello")
    (src / "sub" / "b.txt").write_text("world")
    arc = tmp / name
    assert ArchiveManager().create(arc, [src]).success
    return arc


def test_extract_here_single_top_level(ctl, tmp_path):
    arc = _archive(tmp_path)
    box = tmp_path / "box"
    box.mkdir()
    moved = box / arc.name
    arc.rename(moved)
    ctl.handle(cli.Command(cli.EXTRACT_HERE, [moved]))
    assert ctl.pump(lambda: (box / "proj" / "sub" / "b.txt").exists() and ctl._busy == 0)
    assert not [e for e in ctl.errors if e[0] != "notify"]


def test_extract_to_folder(ctl, tmp_path):
    arc = _archive(tmp_path)
    ctl.handle(cli.Command(cli.EXTRACT_FOLDER, [arc]))
    assert ctl.pump(lambda: (tmp_path / "pack" / "proj" / "a.txt").exists() and ctl._busy == 0)
    assert not ctl.errors


def test_add_to_zip_and_7z(ctl, tmp_path):
    f1, f2 = tmp_path / "one.txt", tmp_path / "two.txt"
    f1.write_text("1" * 5000)
    f2.write_text("2" * 5000)
    ctl.handle(cli.Command(cli.ADD_TO, [f1, f2], "zip"))
    ctl.handle(cli.Command(cli.ADD_TO, [f1], "7z"))
    assert ctl.pump(lambda: ctl._busy == 0 and (tmp_path / "one.7z").exists())
    zips = list(tmp_path.glob("*.zip"))
    assert len(zips) == 1
    assert ArchiveManager().test_integrity(zips[0]).success
    assert ArchiveManager().test_integrity(tmp_path / "one.7z").success


def test_wrong_path_reports_instead_of_crashing(ctl, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a)))
    ctl.handle(cli.Command(cli.EXTRACT_HERE, [tmp_path / "nope.7z"]))
    assert shown and ctl._busy == 0
