"""End-to-end UI flows. Runs on BOTH stacks (PySide6/Python 3.12 and PySide2/Python 3.8)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("volumax")
import volumax  # noqa: E402,F401  (installs the Qt alias on the legacy stack)

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def pump(app, until, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if until():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture()
def window(app):
    from volumax.ui.main_window import MainWindow

    w = MainWindow()
    w.show()
    yield w
    w.close()


def make_archive(tmp_path: Path) -> Path:
    from volumax.archive_manager import ArchiveManager

    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("hello " * 2000)
    (src / "sub" / "b.txt").write_text("world " * 2000)
    arc = tmp_path / "t.7z"
    assert ArchiveManager().create(arc, [src]).success
    return arc


def test_all_pages_construct_and_switch(window):
    assert len(window.pages) >= 11
    for key in window.pages:
        window.goto(key)


def test_open_archive_lists_and_navigates(app, window, tmp_path):
    br = window.pages["browser"]
    br.load_archive(make_archive(tmp_path))
    assert pump(app, lambda: "files" in br.status_lbl.text() and "Reading" not in br.status_lbl.text())
    assert br.model.rowCount() >= 1


def test_drop_archive_opens_browser(app, window, tmp_path):
    arc = make_archive(tmp_path)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(arc))])
    ev = QDropEvent(QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    window.dropEvent(ev)
    br = window.pages["browser"]
    assert pump(app, lambda: "files" in br.status_lbl.text() and "Reading" not in br.status_lbl.text())


def test_duplicate_scan_background(app, window, tmp_path):
    (tmp_path / "x.bin").write_bytes(os.urandom(100_000))
    (tmp_path / "y.bin").write_bytes((tmp_path / "x.bin").read_bytes())
    pg = window.pages["duplicates"]
    pg.root_edit.setText(str(tmp_path))
    pg._scan()
    assert pump(app, lambda: pg.table.rowCount() == 1 and pg.btn_scan.isEnabled())


def test_queue_panel_refreshes(app, window):
    q = window.pages["queue"]
    q.refresh()  # must not raise on an empty queue
