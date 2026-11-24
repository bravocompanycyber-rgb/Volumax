"""Split-volume archive page."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
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

logger = logging.getLogger("volumax.ui.volumes")


class VolumeDialog(QWidget):
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

        title = QLabel("Split Volumes (Multipart Archives)")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)

        info = QLabel(
            "Creates one logical archive split into volumes (e.g. Backup.7z.001, .002, …). "
            "All parts are required for extraction."
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
        btn_row.addWidget(b1)
        btn_row.addWidget(b2)
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
        form.addRow("Output base (e.g. Backup.7z):", r)

        self.vol_size = QSpinBox()
        self.vol_size.setRange(1, 10000)
        self.vol_size.setValue(self.settings.volume_size_mb)
        form.addRow("Volume size (MB):", self.vol_size)

        self.format_combo = QComboBox()
        self.format_combo.addItems(["7z", "zip"])
        form.addRow("Format:", self.format_combo)

        layout.addWidget(opt)

        self.btn = QPushButton("Create Volumes")
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
        path, _ = QFileDialog.getSaveFileName(
            self, "Output Base Name", "", "7z Archive (*.7z);;ZIP (*.zip)"
        )
        if path:
            self.out_edit.setText(path)

    def _run(self) -> None:
        if not self.sources:
            QMessageBox.warning(self, "No sources", "Add files first.")
            return
        out = self.out_edit.text().strip()
        if not out:
            QMessageBox.warning(self, "No output", "Specify output base path.")
            return

        vol = f"{self.vol_size.value()}m"
        fmt = self.format_combo.currentText()

        sources = list(self.sources)  # snapshot
        manager = self.manager
        preset = self.settings.compression_preset
        archive = Path(out)

        def job(progress=None, cancel=None, pause=None):
            return manager.create(
                archive, sources, format=fmt, volume_size=vol, preset=preset,
                progress=progress, cancel=cancel, pause=pause,
            )

        j = get_job_queue().submit("Create volumes", job)
        self.status_lbl.setText(f"Queued as job {j.id} — progress is in the Job Queue.")
