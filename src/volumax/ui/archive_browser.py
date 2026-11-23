"""Archive browser page — list contents of an archive."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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


class ArchiveBrowserPage(QWidget):
    def __init__(self, manager: ArchiveManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.current: Path | None = None
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
        btn = QPushButton("Open")
        btn.clicked.connect(self._browse)
        btn_refresh = QPushButton("Refresh")
        btn_refresh.setObjectName("secondary")
        btn_refresh.clicked.connect(self._refresh)
        row.addWidget(self.path_edit, 1)
        row.addWidget(btn)
        row.addWidget(btn_refresh)
        layout.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Path", "Size", "Packed", "Modified", "Encrypted"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        self.status_lbl = QLabel("")
        layout.addWidget(self.status_lbl)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Archive",
            "",
            "Archives (*.zip *.7z *.tar *.tar.gz *.tgz *.tar.bz2 *.tar.xz);;All (*)",
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

        result = self.manager.list_contents(path)
        self.table.setRowCount(0)
        if not result.success:
            self.status_lbl.setText(f"Error: {result.message}")
            QMessageBox.critical(self, "List failed", result.message)
            return

        for entry in result.entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(entry.path))
            self.table.setItem(row, 1, QTableWidgetItem(str(entry.size)))
            self.table.setItem(row, 2, QTableWidgetItem(str(entry.compressed_size)))
            self.table.setItem(row, 3, QTableWidgetItem(entry.timestamp or ""))
            self.table.setItem(
                row, 4, QTableWidgetItem("Yes" if entry.encrypted else "")
            )

        self.status_lbl.setText(f"{len(result.entries)} entries")
