"""Diagnostics page: health checks, one-click repair, locate 7z, export a support report."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QAbstractItemView,
)

from .. import selfheal
from ..archive_manager import ArchiveManager
from ..config import LOGS_DIR
from .widgets.workers import run_in_background

logger = logging.getLogger("volumax.ui.diagnostics")

# Status text is paired with colour AND a word, so it never relies on colour alone.
_ICON = {"OK": "✔ OK", "WARN": "⚠ Attention", "FAIL": "✖ Problem"}


class DiagnosticsPage(QWidget):
    def __init__(self, manager: ArchiveManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)
        title = QLabel("Diagnostics & Repair")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        lay.addWidget(title)
        note = QLabel("VOLUMAX checks its own engine, settings and folders. Nothing outside its own "
                      "folders is scanned, and nothing is changed without you pressing Repair.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #a9b6cb;")
        lay.addWidget(note)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Status", "Check", "Details"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(240)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.btn_run = QPushButton("Run checks")
        self.btn_run.clicked.connect(self.refresh)
        self.btn_fix = QPushButton("Repair")
        self.btn_fix.setObjectName("gold")
        self.btn_fix.clicked.connect(self._repair)
        self.btn_loc = QPushButton("Locate 7z.exe…")
        self.btn_loc.setObjectName("secondary")
        self.btn_loc.clicked.connect(self._locate)
        self.btn_rep = QPushButton("Save support report…")
        self.btn_rep.setObjectName("secondary")
        self.btn_rep.clicked.connect(self._report)
        self.btn_log = QPushButton("Open logs folder")
        self.btn_log.setObjectName("secondary")
        self.btn_log.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOGS_DIR))))
        for b in (self.btn_run, self.btn_fix, self.btn_loc, self.btn_rep, self.btn_log):
            row.addWidget(b)
        lay.addLayout(row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        lay.addWidget(self.log)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        self.btn_run.setEnabled(False)

        def done(checks) -> None:
            self.btn_run.setEnabled(True)
            self.table.setRowCount(len(checks))
            for r, c in enumerate(checks):
                self.table.setItem(r, 0, QTableWidgetItem(_ICON[c.status]))
                self.table.setItem(r, 1, QTableWidgetItem(c.name))
                detail = c.detail + (f"   → {c.fix}" if (not c.ok and c.fix) else "")
                self.table.setItem(r, 2, QTableWidgetItem(detail))
            bad = [c for c in checks if not c.ok and not c.warn]
            self.log.setPlainText("Everything looks good." if not bad and all(c.ok for c in checks)
                                  else f"{len([c for c in checks if not c.ok])} item(s) need attention.")

        def failed(msg: str) -> None:
            self.btn_run.setEnabled(True)
            self.log.setPlainText(f"The check itself failed: {msg}")

        run_in_background(lambda: selfheal.run_checks(self.manager), done, failed)

    def _repair(self) -> None:
        def done(actions) -> None:
            self.log.setPlainText("\n".join(actions))
            self.refresh()

        run_in_background(lambda: selfheal.repair(self.manager), done, self.log.setPlainText)

    def _locate(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Find 7z.exe (or 7zz)", "", "7-Zip (7z.exe 7zz 7z);;All files (*)")
        if not path:
            return
        ok, msg = selfheal.locate_engine(self.manager, Path(path))
        if not ok:
            QMessageBox.warning(self, "Locate 7-Zip", msg)
        self.log.setPlainText(msg)
        self.refresh()

    def _report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save report", "volumax-report.txt", "Text (*.txt)")
        if not path:
            return
        try:
            selfheal.export_report(Path(path), self.manager)
            self.log.setPlainText(f"Report saved to {path}")
        except OSError as exc:
            QMessageBox.warning(self, "Report", f"Could not save: {exc}")
