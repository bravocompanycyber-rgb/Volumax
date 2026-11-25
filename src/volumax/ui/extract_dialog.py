"""Extract Archive page."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
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

from ..compat import safe_is_file
from ..archive_manager import ArchiveManager
from ..jobs import get_job_queue
from ..settings import get_settings
from .archive_browser import ARCHIVE_FILTER
from .convert_dialog import _strip_archive_ext

logger = logging.getLogger("volumax.ui.extract")


class _Done(QObject):
    """Bridges the worker thread to the GUI thread (signals are queued across threads)."""

    finished = Signal(str)


class ExtractArchiveDialog(QWidget):
    def __init__(self, manager: ArchiveManager, embedded: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.settings = get_settings()
        self._done = _Done(self)
        self._done.finished.connect(self._open_folder)
        self.setAcceptDrops(True)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Extract Archive")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        form_group = QGroupBox("Archive && Destination  (drop an archive here)")
        form = QFormLayout(form_group)

        self.archive_edit = QLineEdit()
        self.archive_edit.textChanged.connect(self._suggest_dest)
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
        self.password_edit.setPlaceholderText("Only if the archive is encrypted")
        form.addRow("Password:", self.password_edit)

        self.subfolder_check = QCheckBox("Extract into a new folder named after the archive")
        self.subfolder_check.setChecked(bool(self.settings.get("extract_to_subfolder", True)))
        self.subfolder_check.setToolTip("Keeps a messy archive from spilling hundreds of files into your folder.")
        form.addRow("", self.subfolder_check)

        self.safe_check = QCheckBox("Safe extraction (path traversal, symlink && bomb protection)")
        self.safe_check.setChecked(bool(self.settings.safe_extraction))
        form.addRow("", self.safe_check)

        self.overwrite_check = QCheckBox("Overwrite existing files")
        self.overwrite_check.setChecked(True)
        form.addRow("", self.overwrite_check)

        self.open_check = QCheckBox("Open the folder when finished")
        self.open_check.setChecked(bool(self.settings.get("open_after_extract", True)))
        form.addRow("", self.open_check)
        layout.addWidget(form_group)

        self.btn_extract = QPushButton("Extract")
        self.btn_extract.setObjectName("gold")
        self.btn_extract.clicked.connect(self._extract)
        layout.addWidget(self.btn_extract)
        self.status = QLabel("")
        self.status.setStyleSheet("color: #a9b6cb;")
        layout.addWidget(self.status)
        layout.addStretch()

    # drag & drop
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.archive_edit.setText(urls[0])

    def set_archive(self, path: Path) -> None:
        self.archive_edit.setText(str(path))

    def _suggest_dest(self) -> None:
        text = self.archive_edit.text().strip()
        if text and not self.dest_edit.text().strip():
            self.dest_edit.setText(str(Path(text).parent))

    def _browse_archive(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Archive", self.settings.get("last_extract_dir", ""), ARCHIVE_FILTER
        )
        if path:
            self.archive_edit.setText(path)
            self.dest_edit.setText(str(Path(path).parent))
            self.settings.set("last_extract_dir", str(Path(path).parent))

    def _browse_dest(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Destination", self.dest_edit.text())
        if path:
            self.dest_edit.setText(path)

    def _open_folder(self, folder: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _extract(self) -> None:
        arch = Path(self.archive_edit.text().strip())
        dest_text = self.dest_edit.text().strip()
        if not safe_is_file(arch):
            QMessageBox.warning(self, "Missing archive", "Select a valid archive file.")
            return
        if not dest_text:
            QMessageBox.warning(self, "Missing destination", "Select a destination folder.")
            return

        dest = Path(dest_text)
        if self.subfolder_check.isChecked():
            dest = dest / _strip_archive_ext(arch.name)

        password = self.password_edit.text() or None
        safe = self.safe_check.isChecked()
        overwrite = self.overwrite_check.isChecked()
        open_after = self.open_check.isChecked()
        manager, done = self.manager, self._done

        for key, value in (("extract_to_subfolder", self.subfolder_check.isChecked()),
                           ("open_after_extract", open_after), ("safe_extraction", safe)):
            self.settings.set(key, value)
        self.settings.save()

        def job(progress=None, cancel=None, pause=None):
            result = manager.extract(
                arch, dest, password=password, overwrite=overwrite, safe=safe,
                progress=progress, cancel=cancel, pause=pause,
            )
            if result.success and open_after:
                done.finished.emit(str(dest))
            return result

        j = get_job_queue().submit(f"Extract {arch.name}", job)
        self.status.setText(f"Queued as job {j.id} — progress is in the Job Queue.")
