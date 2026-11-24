"""Independent ZIP packages page."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
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

logger = logging.getLogger("volumax.ui.packages")


class IndependentPackageDialog(QWidget):
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

        title = QLabel("Independent ZIP Packages")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        info = QLabel(
            "Create multiple separate ZIP files. Each ZIP is independently extractable. "
            "You choose the maximum package size (MB). Packages are filled by their real "
            "compressed size, and the final ZIP size is verified — nothing oversized is kept."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #8b9bb4;")
        layout.addWidget(info)

        src_group = QGroupBox("Sources")
        src_l = QVBoxLayout(src_group)
        self.source_list = QListWidget()
        src_l.addWidget(self.source_list)
        btn_row = QHBoxLayout()
        b1 = QPushButton("Add Files")
        b1.clicked.connect(self._add_files)
        b2 = QPushButton("Add Folder")
        b2.setObjectName("secondary")
        b2.clicked.connect(self._add_folder)
        b3 = QPushButton("Clear")
        b3.setObjectName("secondary")
        b3.clicked.connect(lambda: (self.sources.clear(), self.source_list.clear()))
        btn_row.addWidget(b1)
        btn_row.addWidget(b2)
        btn_row.addWidget(b3)
        btn_row.addStretch()
        src_l.addLayout(btn_row)
        layout.addWidget(src_group)

        opt = QGroupBox("Options")
        form = QFormLayout(opt)

        self.out_edit = QLineEdit()
        btn_out = QPushButton("Browse")
        btn_out.setObjectName("secondary")
        btn_out.clicked.connect(self._browse_out)
        r = QHBoxLayout()
        r.addWidget(self.out_edit, 1)
        r.addWidget(btn_out)
        form.addRow("Output folder:", r)

        self.base_name = QLineEdit("package")
        form.addRow("Base name:", self.base_name)

        self.max_mb = QSpinBox()
        self.max_mb.setRange(1, 102400)
        self.max_mb.setValue(self.settings.independent_zip_max_mb)
        form.addRow("Max size (MB):", self.max_mb)

        layout.addWidget(opt)

        self.btn = QPushButton("Create Packages")
        self.btn.setObjectName("gold")
        self.btn.clicked.connect(self._run)
        layout.addWidget(self.btn)
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #8b9bb4;")
        layout.addWidget(self.status_lbl)
        layout.addStretch()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for u in event.mimeData().urls():
            p = Path(u.toLocalFile())
            if u.isLocalFile() and p.exists() and p not in self.sources:
                self.sources.append(p)
                self.source_list.addItem(str(p))

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

    def _browse_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Output Folder")
        if path:
            self.out_edit.setText(path)

    def _run(self) -> None:
        if not self.sources:
            QMessageBox.warning(self, "No sources", "Add files or folders first.")
            return
        out = self.out_edit.text().strip()
        if not out:
            QMessageBox.warning(self, "No output", "Choose an output folder.")
            return

        max_mb = self.max_mb.value()
        base = self.base_name.text().strip() or "package"

        sources = list(self.sources)  # snapshot
        manager = self.manager

        def job(progress=None, cancel=None):
            return manager.create_independent_packages(
                sources, Path(out), base, max_mb=max_mb, progress=progress, cancel=cancel,
            )

        j = get_job_queue().submit("Independent packages", job)
        self.status_lbl.setText(f"Queued as job {j.id} — progress is in the Job Queue.")
