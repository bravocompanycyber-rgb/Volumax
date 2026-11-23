"""Integrity Centre page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from ..archive_manager import ArchiveManager
from ..checksums import hash_file, SUPPORTED_ALGORITHMS
from .widgets.workers import run_in_background


class IntegrityPage(QWidget):
    def __init__(self, manager: ArchiveManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Integrity Centre")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        # Archive test
        g1 = QGroupBox("Archive Integrity Test")
        f1 = QFormLayout(g1)
        self.arch_edit = QLineEdit()
        btn = QPushButton("Browse")
        btn.setObjectName("secondary")
        btn.clicked.connect(self._browse_arch)
        row = QHBoxLayout()
        row.addWidget(self.arch_edit, 1)
        row.addWidget(btn)
        f1.addRow("Archive:", row)
        self.pwd = QLineEdit()
        self.pwd.setEchoMode(QLineEdit.EchoMode.Password)
        f1.addRow("Password:", self.pwd)
        btn_test = QPushButton("Test Integrity")
        btn_test.setObjectName("gold")
        btn_test.clicked.connect(self._test)
        f1.addRow("", btn_test)
        layout.addWidget(g1)

        # File checksum
        g2 = QGroupBox("File Checksum")
        f2 = QFormLayout(g2)
        self.file_edit = QLineEdit()
        btn2 = QPushButton("Browse")
        btn2.setObjectName("secondary")
        btn2.clicked.connect(self._browse_file)
        row2 = QHBoxLayout()
        row2.addWidget(self.file_edit, 1)
        row2.addWidget(btn2)
        f2.addRow("File:", row2)
        self.algo = QComboBox()
        self.algo.addItems(list(SUPPORTED_ALGORITHMS))
        self.algo.setCurrentText("sha256")
        f2.addRow("Algorithm:", self.algo)
        btn_hash = QPushButton("Compute Hash")
        btn_hash.clicked.connect(self._hash)
        f2.addRow("", btn_hash)
        layout.addWidget(g2)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(160)
        layout.addWidget(self.output, 1)

    def _browse_arch(self):
        p, _ = QFileDialog.getOpenFileName(self, "Archive", "", "Archives (*.7z *.zip *.tar *);;All (*)")
        if p:
            self.arch_edit.setText(p)

    def _browse_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "File")
        if p:
            self.file_edit.setText(p)

    def _test(self):
        path = self.arch_edit.text().strip()
        if not path or not Path(path).exists():
            QMessageBox.warning(self, "Missing", "Select a valid archive.")
            return
        pwd = self.pwd.text() or None
        self.output.append(f"Testing {path} …\n")

        def work():
            return self.manager.test_integrity(Path(path), password=pwd)

        def done(res):
            status = "PASSED" if res.success else "FAILED"
            self.output.append(f"[{status}] {res.message}\n")

        self._test_task = run_in_background(work, done, lambda m: self.output.append(f"Error: {m}\n"))

    def _hash(self):
        path = self.file_edit.text().strip()
        if not path or not Path(path).exists():
            QMessageBox.warning(self, "Missing", "Select a file.")
            return
        algo = self.algo.currentText()
        self.output.append(f"Hashing {path} …\n")
        self._hash_task = run_in_background(
            lambda: hash_file(Path(path), algo),
            lambda digest: self.output.append(f"{algo.upper()}  {digest}  {path}\n"),
            lambda m: self.output.append(f"Error: {m}\n"),
        )
