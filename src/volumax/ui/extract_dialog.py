"""Extract Archive page."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..archive_manager import ArchiveManager
from ..jobs import get_job_queue
from ..settings import get_settings

logger = logging.getLogger("volumax.ui.extract")


class ExtractArchiveDialog(QWidget):
    def __init__(self, manager: ArchiveManager, embedded: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.settings = get_settings()
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Extract Archive")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        form_group = QGroupBox("Archive & Destination")
        form = QFormLayout(form_group)

        self.archive_edit = QLineEdit()
        btn_arch = QPushButton("Browse")
        btn_arch.setObjectName("secondary")
        btn_arch.clicked.connect(self._browse_archive)
        row1 = QHBoxLayout()
        row1.addWidget(self.archive_edit, 1)
        row1.addWidget(btn_arch)
        form.addRow("Archive:", row1)

        self.dest_edit = QLineEdit()
        btn_dest = QPushButton("Browse")
        btn_dest.setObjectName("secondary")
        btn_dest.clicked.connect(self._browse_dest)
        row2 = QHBoxLayout()
        row2.addWidget(self.dest_edit, 1)
        row2.addWidget(btn_dest)
        form.addRow("Destination:", row2)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password:", self.password_edit)

        self.safe_check = QCheckBox("Safe extraction (path traversal & bomb protection)")
        self.safe_check.setChecked(True)
        form.addRow("", self.safe_check)

        self.overwrite_check = QCheckBox("Overwrite existing files")
        self.overwrite_check.setChecked(True)
        form.addRow("", self.overwrite_check)

        layout.addWidget(form_group)

        self.btn_extract = QPushButton("Extract")
        self.btn_extract.setObjectName("gold")
        self.btn_extract.clicked.connect(self._extract)
        layout.addWidget(self.btn_extract)
        layout.addStretch()

    def _browse_archive(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Archive",
            self.settings.get("last_extract_dir", ""),
            "Archives (*.zip *.7z *.tar *.tar.gz *.tgz *.tar.bz2 *.tar.xz);;All (*)",
        )
        if path:
            self.archive_edit.setText(path)
            self.settings.set("last_extract_dir", str(Path(path).parent))

    def _browse_dest(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Destination")
        if path:
            self.dest_edit.setText(path)

    def _extract(self) -> None:
        arch = self.archive_edit.text().strip()
        dest = self.dest_edit.text().strip()
        if not arch or not Path(arch).exists():
            QMessageBox.warning(self, "Missing archive", "Select a valid archive file.")
            return
        if not dest:
            QMessageBox.warning(self, "Missing destination", "Select a destination folder.")
            return

        password = self.password_edit.text() or None
        safe = self.safe_check.isChecked()
        overwrite = self.overwrite_check.isChecked()

        def job(progress=None, cancel=None):
            return self.manager.extract(
                Path(arch),
                Path(dest),
                password=password,
                overwrite=overwrite,
                safe=safe,
            )

        j = get_job_queue().submit(f"Extract {Path(arch).name}", job)
        QMessageBox.information(
            self, "Job queued", f"Extraction queued (job {j.id})."
        )
