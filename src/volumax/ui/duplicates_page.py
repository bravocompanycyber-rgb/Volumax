"""Duplicate Finder page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..duplicate_finder import DuplicateFinder
from .widgets.workers import run_in_background


class DuplicatesPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Duplicate Finder")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        info = QLabel("Scan folders for exact duplicate files by content hash (SHA-256).")
        info.setStyleSheet("color: #8b9bb4;")
        layout.addWidget(info)

        row = QHBoxLayout()
        self.root_edit = QLineEdit()
        self.root_edit.setPlaceholderText("Folder to scan…")
        btn_browse = QPushButton("Browse")
        btn_browse.setObjectName("secondary")
        btn_browse.clicked.connect(self._browse)
        self.btn_scan = btn_scan = QPushButton("Scan")
        btn_scan.setObjectName("gold")
        btn_scan.clicked.connect(self._scan)
        row.addWidget(self.root_edit, 1)
        row.addWidget(btn_browse)
        row.addWidget(btn_scan)
        layout.addLayout(row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Hash (short)", "Size", "Paths"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        self.status = QLabel("")
        layout.addWidget(self.status)

    def _browse(self):
        p = QFileDialog.getExistingDirectory(self, "Folder to scan")
        if p:
            self.root_edit.setText(p)

    def _scan(self):
        root = self.root_edit.text().strip()
        if not root or not Path(root).is_dir():
            QMessageBox.warning(self, "Missing", "Select a valid folder.")
            return
        self.btn_scan.setEnabled(False)
        self.status.setText("Scanning… (the window stays responsive)")
        self.table.setRowCount(0)

        def work():
            return DuplicateFinder().scan([Path(root)])

        self._task = run_in_background(work, self._on_scan_done, self._on_scan_failed)

    def _on_scan_done(self, groups) -> None:
        self.btn_scan.setEnabled(True)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(groups))
            for row, g in enumerate(groups):
                self.table.setItem(row, 0, QTableWidgetItem(g.hash[:16] + "…"))
                self.table.setItem(row, 1, QTableWidgetItem(str(g.size)))
                self.table.setItem(row, 2, QTableWidgetItem("\n".join(str(p) for p in g.paths)))
        finally:
            self.table.setUpdatesEnabled(True)
        wasted = sum(g.wasted_bytes for g in groups)
        self.status.setText(
            f"Found {len(groups)} duplicate group(s). "
            f"Reclaimable ≈ {wasted / (1024*1024):.2f} MB"
        )

    def _on_scan_failed(self, message: str) -> None:
        self.btn_scan.setEnabled(True)
        self.status.setText(f"Error: {message}")
        QMessageBox.critical(self, "Scan failed", message)
