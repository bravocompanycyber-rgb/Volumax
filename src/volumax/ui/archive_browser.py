"""Archive browser page — list contents without freezing the UI."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..archive_manager import ArchiveManager

logger = logging.getLogger("volumax.ui.browser")


class _ListWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, manager: ArchiveManager, path: Path, password: str | None = None) -> None:
        super().__init__()
        self.manager = manager
        self.path = path
        self.password = password

    def run(self) -> None:
        try:
            result = self.manager.list_contents(self.path, password=self.password)
            self.finished.emit(result)
        except Exception as exc:
            logger.exception("List worker failed")
            self.failed.emit(str(exc))


class ArchiveBrowserPage(QWidget):
    def __init__(self, manager: ArchiveManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.current: Path | None = None
        self._thread: QThread | None = None
        self._worker: _ListWorker | None = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Archive Browser")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Path to archive…")
        self.btn_open = QPushButton("Open")
        self.btn_open.clicked.connect(self._browse)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setObjectName("secondary")
        self.btn_refresh.clicked.connect(self._refresh)
        row.addWidget(self.path_edit, 1)
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_refresh)
        layout.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Path", "Size", "Packed", "Modified", "Encrypted"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        layout.addWidget(self.table, 1)

        self.status_lbl = QLabel("Ready")
        layout.addWidget(self.status_lbl)

    def _set_busy(self, busy: bool) -> None:
        self.btn_open.setEnabled(not busy)
        self.btn_refresh.setEnabled(not busy)
        self.path_edit.setEnabled(not busy)
        if busy:
            self.status_lbl.setText("Listing archive… please wait")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Archive",
            "",
            "Archives (*.zip *.7z *.rar *.tar *.tar.gz *.tgz *.tar.bz2 *.tar.xz);;All (*)",
        )
        if path:
            self.load_archive(Path(path))

    def load_archive(self, path: Path) -> None:
        self.current = path
        self.path_edit.setText(str(path))
        self._refresh()

    def _refresh(self) -> None:
        path_str = self.path_edit.text().strip()
        if not path_str:
            return
        path = Path(path_str)
        if not path.exists():
            QMessageBox.warning(self, "Not found", f"File not found:\n{path}")
            return

        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1000)

        self.table.setRowCount(0)
        self._set_busy(True)

        self._thread = QThread(self)
        self._worker = _ListWorker(self.manager, path)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_list_done)
        self._worker.failed.connect(self._on_list_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_worker)
        self._thread.start()

    def _cleanup_worker(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    def _on_list_done(self, result) -> None:
        self._set_busy(False)
        self.table.setRowCount(0)

        if not result.success:
            self.status_lbl.setText(f"Error: {result.message}")
            QMessageBox.critical(self, "List failed", result.message)
            return

        entries = result.entries or []
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(entries))
            for row, entry in enumerate(entries):
                self.table.setItem(row, 0, QTableWidgetItem(entry.path))
                self.table.setItem(row, 1, QTableWidgetItem(str(entry.size)))
                self.table.setItem(row, 2, QTableWidgetItem(str(entry.compressed_size)))
                self.table.setItem(row, 3, QTableWidgetItem(entry.timestamp or ""))
                self.table.setItem(
                    row, 4, QTableWidgetItem("Yes" if entry.encrypted else "")
                )
        finally:
            self.table.setUpdatesEnabled(True)

        self.status_lbl.setText(f"{len(entries)} entries — {self.path_edit.text()}")

    def _on_list_failed(self, message: str) -> None:
        self._set_busy(False)
        self.status_lbl.setText(f"Error: {message}")
        QMessageBox.critical(self, "List failed", message)