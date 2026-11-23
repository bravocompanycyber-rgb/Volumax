"""Create Archive page / dialog."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..archive_manager import ArchiveManager
from ..jobs import get_job_queue
from ..settings import get_settings

logger = logging.getLogger("volumax.ui.create")


class CreateArchiveDialog(QWidget):
    def __init__(self, manager: ArchiveManager, embedded: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.settings = get_settings()
        self.sources: list[Path] = []
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Create Archive")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        # Sources
        src_group = QGroupBox("Source Files & Folders")
        src_layout = QVBoxLayout(src_group)
        self.source_list = QListWidget()
        self.source_list.setMinimumHeight(120)
        src_layout.addWidget(self.source_list)

        btn_row = QHBoxLayout()
        btn_add_files = QPushButton("Add Files")
        btn_add_files.clicked.connect(self._add_files)
        btn_add_folder = QPushButton("Add Folder")
        btn_add_folder.setObjectName("secondary")
        btn_add_folder.clicked.connect(self._add_folder)
        btn_clear = QPushButton("Clear")
        btn_clear.setObjectName("secondary")
        btn_clear.clicked.connect(self._clear_sources)
        btn_row.addWidget(btn_add_files)
        btn_row.addWidget(btn_add_folder)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        src_layout.addLayout(btn_row)
        layout.addWidget(src_group)

        # Options
        opt = QGroupBox("Options")
        form = QFormLayout(opt)

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Output archive path…")
        btn_browse = QPushButton("Browse")
        btn_browse.setObjectName("secondary")
        btn_browse.clicked.connect(self._browse_output)
        out_row = QHBoxLayout()
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(btn_browse)
        form.addRow("Output:", out_row)

        self.format_combo = QComboBox()
        self.format_combo.addItems(["7z", "zip", "tar", "tar.gz", "tar.bz2", "tar.xz"])
        form.addRow("Format:", self.format_combo)

        self.level_spin = QSpinBox()
        self.level_spin.setRange(0, 9)
        self.level_spin.setValue(self.settings.compression_level)
        form.addRow("Compression (0–9):", self.level_spin)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Optional password")
        form.addRow("Password:", self.password_edit)

        self.encrypt_names = QCheckBox("Encrypt filenames (7z only)")
        form.addRow("", self.encrypt_names)

        layout.addWidget(opt)

        # Action
        self.btn_create = QPushButton("Create Archive")
        self.btn_create.setObjectName("gold")
        self.btn_create.clicked.connect(self._create)
        layout.addWidget(self.btn_create)
        layout.addStretch()

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Select Files")
        for f in files:
            p = Path(f)
            if p not in self.sources:
                self.sources.append(p)
                self.source_list.addItem(str(p))

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            p = Path(folder)
            if p not in self.sources:
                self.sources.append(p)
                self.source_list.addItem(str(p))

    def _clear_sources(self) -> None:
        self.sources.clear()
        self.source_list.clear()

    def _browse_output(self) -> None:
        fmt = self.format_combo.currentText()
        ext = f".{fmt}" if not fmt.startswith("tar.") else f".{fmt}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Archive As", "", f"Archive (*{ext})"
        )
        if path:
            self.output_edit.setText(path)

    def _create(self) -> None:
        if not self.sources:
            QMessageBox.warning(self, "No sources", "Add at least one file or folder.")
            return
        out = self.output_edit.text().strip()
        if not out:
            QMessageBox.warning(self, "No output", "Specify an output archive path.")
            return

        archive = Path(out)
        fmt = self.format_combo.currentText()
        level = self.level_spin.value()
        password = self.password_edit.text() or None
        encrypt = self.encrypt_names.isChecked()

        def job(progress=None, cancel=None):
            return self.manager.create(
                archive,
                self.sources,
                format=fmt,
                level=level,
                password=password,
                encrypt_filenames=encrypt,
                progress=progress,
                cancel=cancel,
            )

        queue = get_job_queue()
        j = queue.submit(f"Create {archive.name}", job)
        QMessageBox.information(
            self,
            "Job queued",
            f"Archive creation queued (job {j.id}).\nWatch progress in the Job Queue.",
        )
