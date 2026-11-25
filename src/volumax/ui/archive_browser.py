"""Archive browser — opens instantly, navigates folders, searches, extracts."""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..compat import safe_exists, safe_is_file
from ..archive_manager import ArchiveManager
from ..jobs import get_job_queue
from ..listing import ArchiveTree, clear_cache, load_tree
from .archive_model import UP_ROW, ArchiveModel, human_size
from .widgets.workers import run_in_background

logger = logging.getLogger("volumax.ui.browser")

ARCHIVE_FILTER = (
    "Archives (*.zip *.7z *.rar *.tar *.tar.gz *.tgz *.tar.bz2 *.tbz2 *.tar.xz *.txz "
    "*.gz *.bz2 *.xz *.iso *.cab *.wim *.001);;All files (*)"
)
RISKY_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".com", ".scr", ".msi", ".ps1", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".lnk", ".jar", ".reg", ".hta", ".cpl", ".dll", ".sh", ".app", ".pif",
}

_TEMP_DIRS: list[str] = []


@atexit.register
def _cleanup_temp() -> None:
    for d in _TEMP_DIRS:
        shutil.rmtree(d, ignore_errors=True)


class ArchiveBrowserPage(QWidget):
    opened = Signal(str)  # path of an archive that opened successfully

    def __init__(self, manager: ArchiveManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.current: Path | None = None
        self.tree: ArchiveTree | None = None
        self._password: str | None = None
        self._task = None
        self._gen = 0  # load generation: results of superseded loads are ignored
        self.setAcceptDrops(True)
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        title = QLabel("Archive Browser")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Open an archive, or drop one here…")
        self.path_edit.returnPressed.connect(self._refresh)
        self.btn_open = QPushButton("Open…")
        self.btn_open.clicked.connect(self._browse)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setObjectName("secondary")
        self.btn_refresh.clicked.connect(lambda: self._refresh(use_cache=False))
        row.addWidget(self.path_edit, 1)
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_refresh)
        layout.addLayout(row)

        nav = QHBoxLayout()
        self.btn_up = QPushButton("⬆ Up")
        self.btn_up.setObjectName("secondary")
        self.btn_up.clicked.connect(self._go_up)
        self.location = QLabel("")
        self.location.setStyleSheet("color: #a9b6cb;")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search in archive…  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(320)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._apply_search)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        nav.addWidget(self.btn_up)
        nav.addWidget(self.location, 1)
        nav.addWidget(self.search)
        layout.addLayout(nav)

        self.model = ArchiveModel(self)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.setSortingEnabled(True)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(24)  # uniform rows = fast layout
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.view.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in ((1, 90), (2, 90), (3, 150), (4, 100)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.view.setColumnWidth(col, width)
        self.view.doubleClicked.connect(self._activated)
        layout.addWidget(self.view, 1)

        bottom = QHBoxLayout()
        self.btn_extract_all = QPushButton("Extract All…")
        self.btn_extract_all.setObjectName("gold")
        self.btn_extract_all.clicked.connect(self._extract_all)
        self.btn_extract_sel = QPushButton("Extract Selected…")
        self.btn_extract_sel.clicked.connect(self._extract_selected)
        self.btn_test = QPushButton("Test")
        self.btn_test.setObjectName("secondary")
        self.btn_test.clicked.connect(self._test)
        self.status_lbl = QLabel("Ready")
        bottom.addWidget(self.btn_extract_all)
        bottom.addWidget(self.btn_extract_sel)
        bottom.addWidget(self.btn_test)
        bottom.addStretch()
        bottom.addWidget(self.status_lbl)
        layout.addLayout(bottom)

        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search.setFocus)
        QShortcut(QKeySequence("Backspace"), self.view, activated=self._go_up)
        QShortcut(QKeySequence("Return"), self.view, activated=self._activate_current)
        self._set_enabled(False)

    def _set_enabled(self, loaded: bool) -> None:
        for w in (self.btn_extract_all, self.btn_extract_sel, self.btn_test, self.btn_up, self.search):
            w.setEnabled(loaded)

    # --------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.load_archive(Path(urls[0]))

    # -------------------------------------------------------------- loading
    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Archive", "", ARCHIVE_FILTER)
        if path:
            self.load_archive(Path(path))

    def load_archive(self, path: Path, password: str | None = None) -> None:
        if password is None:
            self._password = None
        self.current = Path(path)
        self.path_edit.setText(str(path))
        self._refresh()

    def _refresh(self, use_cache: bool = True) -> None:
        path_str = self.path_edit.text().strip()
        if not path_str:
            return
        path = Path(path_str)
        if not safe_is_file(path):
            QMessageBox.warning(self, "Not found", f"File not found:\n{path}")
            return
        self.current = path
        if use_cache is False:
            clear_cache()
        self.btn_open.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        self.status_lbl.setText("Reading archive…")
        password = self._password

        def work():
            return load_tree(self.manager, path, password, use_cache=use_cache)

        self._gen += 1
        gen = self._gen
        self._task = run_in_background(
            work,
            lambda payload: self._on_loaded(payload) if gen == self._gen else None,
            lambda msg: self._on_failed(msg) if gen == self._gen else None,
        )

    def _on_loaded(self, payload) -> None:
        result, tree = payload
        self.btn_open.setEnabled(True)
        self.btn_refresh.setEnabled(True)

        if tree is not None and tree.needs_password:
            pwd, ok = QInputDialog.getText(
                self, "Password required",
                f"“{self.current.name}” is encrypted. Enter the password:",
                QLineEdit.EchoMode.Password,
            )
            if ok and pwd:
                self._password = pwd
                self._refresh()
            else:
                self.status_lbl.setText("Password required")
            return

        if tree is None:
            self.model.set_tree(None)
            self._set_enabled(False)
            self.status_lbl.setText(f"Error: {result.message[:120]}")
            QMessageBox.critical(self, "Cannot open archive", result.message[:1500])
            return

        self.tree = tree
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.model.set_tree(tree)
        self._set_enabled(True)
        self._update_location()
        took = " (cached)" if result.message == "cached" else f" in {tree.elapsed * 1000:.0f} ms"
        ratio = (
            f" · packed {tree.total_packed / tree.total_size * 100:.0f}%"
            if tree.total_size and tree.total_packed
            else ""
        )
        self.status_lbl.setText(
            f"{tree.file_count:,} files, {tree.dir_count:,} folders · "
            f"{human_size(tree.total_size)}{ratio}{took}"
        )
        self.view.setFocus()
        if self.current:
            self.opened.emit(str(self.current))

    def _on_failed(self, message: str) -> None:
        self.btn_open.setEnabled(True)
        self.btn_refresh.setEnabled(True)
        self.status_lbl.setText(f"Error: {message[:120]}")
        QMessageBox.critical(self, "Cannot open archive", message[:1500])

    # ----------------------------------------------------------- navigation
    def _update_location(self) -> None:
        name = self.current.name if self.current else ""
        cwd = self.model.cwd
        self.location.setText(f"{name} / {cwd.replace('/', ' / ')}" if cwd else name)
        self.btn_up.setEnabled(bool(cwd) or self.model.searching)

    def _apply_search(self) -> None:
        self.model.set_query(self.search.text())
        if self.model.searching:
            self.location.setText(f"Search results for “{self.search.text().strip()}”")
            self.status_lbl.setText(f"{self.model.rowCount():,} matches")
        else:
            self._update_location()

    def _go_up(self) -> None:
        if self.model.searching:
            self.search.clear()
            return
        cwd = self.model.cwd
        if cwd:
            self.model.set_cwd(cwd.rpartition("/")[0])
            self._update_location()

    def _activate_current(self) -> None:
        idx = self.view.currentIndex()
        if idx.isValid():
            self._activated(idx)

    def _activated(self, index: QModelIndex) -> None:
        entry = self.model.entry_at(index.row())
        if entry is None:
            return
        if entry is UP_ROW:
            self._go_up()
        elif entry.is_dir:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.model.set_cwd(entry.path)
            self._update_location()
        else:
            self._open_file(entry.path)

    # -------------------------------------------------------------- actions
    def _selected_names(self) -> list[str]:
        """Archive paths for the selection; folders expand to every file beneath them."""
        assert self.tree is not None
        rows = sorted({i.row() for i in self.view.selectionModel().selectedRows()})
        files: list[str] = []
        prefixes: list[str] = []
        for r in rows:
            e = self.model.entry_at(r)
            if e is None or e is UP_ROW:
                continue
            if e.is_dir:
                prefixes.append(e.path + "/")
            else:
                files.append(e.path)
        if prefixes:
            pre = tuple(prefixes)
            files.extend(e.path for e in self.tree.entries if not e.is_dir and e.path.startswith(pre))
        return list(dict.fromkeys(files))

    def _ask_destination(self) -> Path | None:
        assert self.current is not None
        start = str(self.current.parent)
        folder = QFileDialog.getExistingDirectory(self, "Extract to…", start)
        return Path(folder) if folder else None

    def _submit_extract(self, dest: Path, names: list[str] | None, label: str) -> None:
        archive = self.current
        pwd = self._password
        manager = self.manager
        assert archive is not None

        def job(progress=None, cancel=None, pause=None):
            return manager.extract(
                archive, dest, password=pwd, selected=names,
                progress=progress, cancel=cancel, pause=pause,
            )

        j = get_job_queue().submit(f"Extract {label} ← {archive.name}", job)
        self.status_lbl.setText(f"Extraction queued ({j.id}) — see Job Queue")

    def _extract_all(self) -> None:
        dest = self._ask_destination()
        if dest:
            self._submit_extract(dest, None, "all")

    def _extract_selected(self) -> None:
        names = self._selected_names()
        if not names:
            QMessageBox.information(self, "Nothing selected", "Select files or folders first.")
            return
        dest = self._ask_destination()
        if dest:
            self._submit_extract(dest, names, f"{len(names)} file(s)")

    def _test(self) -> None:
        archive, pwd, manager = self.current, self._password, self.manager
        if archive is None:
            return

        def job(progress=None, cancel=None, pause=None):
            return manager.test_integrity(archive, password=pwd)

        j = get_job_queue().submit(f"Test {archive.name}", job)
        self.status_lbl.setText(f"Integrity test queued ({j.id})")

    def _open_file(self, name: str) -> None:
        """Extract one file to a private temp folder and open it with its default app."""
        ext = os.path.splitext(name)[1].lower()
        if ext in RISKY_EXTENSIONS:
            ans = QMessageBox.warning(
                self, "Open executable file?",
                f"“{name.rpartition('/')[2]}” can run code on your computer.\n"
                "Only open it if you trust this archive.",
                QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if ans != QMessageBox.StandardButton.Open:
                return
        archive, pwd, manager = self.current, self._password, self.manager
        if archive is None:
            return
        tmp = tempfile.mkdtemp(prefix="volumax_open_")
        _TEMP_DIRS.append(tmp)
        self.status_lbl.setText(f"Extracting {name.rpartition('/')[2]}…")

        def work():
            return manager.extract(archive, Path(tmp), password=pwd, selected=[name])

        def done(res) -> None:
            target = Path(tmp) / name
            if res.success and safe_exists(target):
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
                self.status_lbl.setText(f"Opened {target.name}")
            else:
                self.status_lbl.setText("Could not open file")
                QMessageBox.warning(self, "Open failed", res.message[:800])

        self._open_task = run_in_background(work, done, lambda m: self.status_lbl.setText(m[:120]))
