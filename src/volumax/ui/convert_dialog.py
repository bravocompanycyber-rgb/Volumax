"""Convert Archive page — re-pack any archive into another format."""

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
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..compat import safe_exists, safe_is_file
from ..archive_manager import ArchiveManager
from ..compression import PRESETS
from ..jobs import get_job_queue
from ..settings import get_settings
from .archive_browser import ARCHIVE_FILTER
from .create_dialog import EXTENSIONS, FORMATS, PRESET_LABELS

logger = logging.getLogger("volumax.ui.convert")


def _strip_archive_ext(name: str) -> str:
    lower = name.lower()
    for ext in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz", ".7z", ".zip",
                ".rar", ".tar", ".gz", ".bz2", ".xz", ".iso", ".cab", ".wim"):
        if lower.endswith(ext):
            return name[: -len(ext)]
    return Path(name).stem


class ConvertDialog(QWidget):
    def __init__(self, manager: ArchiveManager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.settings = get_settings()
        self.setAcceptDrops(True)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        title = QLabel("Convert Archive")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)
        info = QLabel(
            "Re-pack an archive into another format (e.g. RAR → 7z, ZIP → 7z for a much smaller "
            "file). The original is never modified."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #a9b6cb;")
        layout.addWidget(info)

        box = QGroupBox("Conversion")
        form = QFormLayout(box)

        self.src_edit = QLineEdit()
        self.src_edit.setPlaceholderText("Source archive (or drop it here)…")
        self.src_edit.textChanged.connect(self._suggest_target)
        b1 = QPushButton("Browse")
        b1.setObjectName("secondary")
        b1.clicked.connect(self._browse_src)
        r1 = QHBoxLayout()
        r1.addWidget(self.src_edit, 1)
        r1.addWidget(b1)
        form.addRow("Source:", r1)

        self.src_pwd = QLineEdit()
        self.src_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.src_pwd.setPlaceholderText("Only if the source is encrypted")
        form.addRow("Source password:", self.src_pwd)

        self.fmt = QComboBox()
        self.fmt.addItems([f for f in FORMATS if f != "tar"])
        self.fmt.currentTextChanged.connect(self._on_format)
        form.addRow("Convert to:", self.fmt)

        self.preset = QComboBox()
        for key in PRESETS:
            self.preset.addItem(PRESET_LABELS[key], key)
        self.preset.setCurrentIndex(self.preset.findData(self.settings.compression_preset))
        form.addRow("Compression:", self.preset)

        self.tgt_edit = QLineEdit()
        b2 = QPushButton("Browse")
        b2.setObjectName("secondary")
        b2.clicked.connect(self._browse_tgt)
        r2 = QHBoxLayout()
        r2.addWidget(self.tgt_edit, 1)
        r2.addWidget(b2)
        form.addRow("Output:", r2)

        self.tgt_pwd = QLineEdit()
        self.tgt_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self.tgt_pwd.setPlaceholderText("Optional password for the new archive")
        form.addRow("New password:", self.tgt_pwd)
        layout.addWidget(box)

        self.btn = QPushButton("Convert")
        self.btn.setObjectName("gold")
        self.btn.clicked.connect(self._run)
        layout.addWidget(self.btn)
        self.status = QLabel("")
        self.status.setStyleSheet("color: #a9b6cb;")
        layout.addWidget(self.status)
        layout.addStretch()
        self._on_format(self.fmt.currentText())

    # drag & drop
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.src_edit.setText(urls[0])

    def _on_format(self, fmt: str) -> None:
        self.tgt_pwd.setEnabled(fmt in ("7z", "zip"))
        if not self.tgt_pwd.isEnabled():
            self.tgt_pwd.clear()
        self._suggest_target()

    def _suggest_target(self) -> None:
        src = self.src_edit.text().strip()
        if not src:
            return
        p = Path(src)
        self.tgt_edit.setText(str(p.parent / (_strip_archive_ext(p.name) + EXTENSIONS[self.fmt.currentText()])))

    def _browse_src(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Source Archive", "", ARCHIVE_FILTER)
        if path:
            self.src_edit.setText(path)

    def _browse_tgt(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Converted Archive As", self.tgt_edit.text())
        if path:
            self.tgt_edit.setText(path)

    def _run(self) -> None:
        src = Path(self.src_edit.text().strip())
        tgt = Path(self.tgt_edit.text().strip())
        if not safe_is_file(src):
            QMessageBox.warning(self, "Missing source", "Choose a valid source archive.")
            return
        if not self.tgt_edit.text().strip():
            QMessageBox.warning(self, "Missing output", "Choose an output path.")
            return
        if tgt.resolve() == src.resolve():
            QMessageBox.warning(self, "Same file", "The output must differ from the source.")
            return
        if safe_exists(tgt) and QMessageBox.question(
            self, "Replace file?", f"{tgt.name} already exists. Replace it?"
        ) != QMessageBox.StandardButton.Yes:
            return
        fmt, preset = self.fmt.currentText(), self.preset.currentData()
        spwd, tpwd = self.src_pwd.text() or None, self.tgt_pwd.text() or None
        manager = self.manager

        def job(progress=None, cancel=None, pause=None):
            return manager.convert(
                src, tgt, format=fmt, preset=preset, password=spwd, target_password=tpwd or None,
                progress=progress, cancel=cancel, pause=pause,
            )

        j = get_job_queue().submit(f"Convert {src.name} → {tgt.name}", job)
        self.status.setText(f"Queued as job {j.id} — progress is in the Job Queue.")
